"""Local research dashboard. All unavailable observations remain explicitly missing."""
import json
import hashlib
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from pm_btc.collector import verify_artifacts
from pm_btc.research import Costs, Rule, metrics, minute_features, scenario_trades, wilson

ROOT = Path(__file__).resolve().parent


@st.cache_data(show_spinner=False)
def cached_csv(path, modified_ns, text_columns=True):
    if not text_columns:
        return pd.read_csv(path)
    # Token identifiers can exceed integer precision: retain exact strings.
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def load_csv(directory, filename, text_columns=True):
    path = directory / filename
    return cached_csv(str(path), path.stat().st_mtime_ns, text_columns)


def development_rows(features, start_date):
    """This exploratory search never receives held-out outcomes or later dates."""
    start = pd.Timestamp(start_date)
    cutoff = (start + pd.Timedelta(days=20)).strftime("%Y-%m-%d")
    return features[(features.split == "development") & (features.local_day >= str(start.date()))
                    & (features.local_day < cutoff)].copy()


def distance_rule_trades(features, targets, start_date, entry_minute, minimum_gap, costs=Costs(), require_trend=False):
    """Follow the side of the opening target, with a dollar gap and no hidden trend filters."""
    if entry_minute not in (10, 11, 12, 13) or not np.isfinite(minimum_gap) or minimum_gap < 0:
        raise ValueError("Choose entry minute 10–13 and a nonnegative dollar gap")
    f = development_rows(features, start_date)
    f = f[(f.entry_minute == entry_minute) & (f.distance_usd.abs() >= minimum_gap) & (f.distance_usd != 0)].copy()
    trend_direction = f.predicted_outcome.copy()
    f["predicted_outcome"] = np.where(f.distance_usd > 0, "Up", "Down")
    if require_trend:
        f = f[f.predicted_outcome == trend_direction].copy()
    eligible = len(f)
    f["prediction_correct"] = f.predicted_outcome == f.winning_outcome
    q = targets[["slug", "minute", "outcome", "last_observation_price", "last_observation_age_seconds",
                 "last_observation_ts", "historical_ask", "historical_depth_usd"]].copy()
    q["minute"] = pd.to_numeric(q.minute)
    if q.duplicated(["slug", "minute", "outcome"]).any():
        raise ValueError("Duplicate entry-time price records")
    f = f.drop(columns=["observed_contract_price", "observation_age_seconds", "observation_ts",
                        "historical_ask", "historical_depth_usd"], errors="ignore")
    f = f.merge(q, left_on=["slug", "entry_minute", "predicted_outcome"],
                right_on=["slug", "minute", "outcome"], how="left", validate="one_to_one")
    for source, target in [("last_observation_price", "observed_contract_price"),
                           ("last_observation_age_seconds", "observation_age_seconds"),
                           ("last_observation_ts", "observation_ts"), ("historical_ask", "historical_ask"),
                           ("historical_depth_usd", "historical_depth_usd")]:
        f[target] = pd.to_numeric(f[source], errors="coerce")
    # Existing scenario engine handles fees, stale observations and a $100 total debit.
    # Momentum, volatility, slope and contract-price thresholds are disabled for this two-input rule.
    rule = Rule(entry_minute, 0, 0, -float("inf"), float("inf"), 0.0, 1.0)
    return scenario_trades(f, rule, costs), eligible


def daily_rule_results(trades, start_date):
    days = pd.date_range(start_date, periods=20, freq="D").strftime("%Y-%m-%d")
    if trades.empty:
        return pd.DataFrame({"Date": days, "Trades": 0, "Modeled net result ($)": 0.0})
    grouped = trades.groupby("local_day").agg(**{"Trades": ("net_profit", "size"), "Modeled net result ($)": ("net_profit", "sum")})
    grouped = grouped.reindex(days, fill_value=0)
    grouped.index.name = "Date"
    return grouped.reset_index()


def open_lab_chart(slug, day):
    st.session_state.charts_date = day
    st.session_state.charts_interval = slug
    st.session_state.dashboard_view = "Charts"


def show_simple_lab(directory, audit):
    st.subheader("Strategy Lab · build a rule, test history, review the score")
    st.write("**Above target → Up. Below target → Down. Inside your minimum gap → skip.** The gap is Bitcoin's dollar distance from its opening target, not the contract's bid/ask spread.")
    path = directory / "features.csv"
    if not path.exists():
        st.info("Validated historical features are needed before testing this rule.")
        return
    a, b, c = st.columns(3)
    entry = a.selectbox("Entry minute", [10, 11, 12, 13], key="lab_entry")
    gap = b.number_input("Minimum gap from opening target ($)", min_value=0.0, value=50.0, step=10.0, key="lab_gap")
    bid = c.slider("Bid amount per trade ($)", min_value=10, max_value=1000, value=100, step=10, key="lab_bid")
    require_trend = st.checkbox("Require the first-10-minute trend to agree", value=False)
    st.caption(f"Example: with a ${gap:,.0f} gap, enter Up at least ${gap:,.0f} above the target or Down at least ${gap:,.0f} below it. Equality to the target is skipped. Only the first 20 days are tested.")
    settings = (str(directory), entry, gap, bid, require_trend)
    if st.button("Test strategy", type="primary"):
        with st.spinner("Reviewing the actual development markets…"):
            features = load_csv(directory, "features.csv", text_columns=False)
            targets = load_csv(directory, "contract_targets.csv", text_columns=False)
            trades, matched = distance_rule_trades(features, targets, audit["start_date_inclusive"], entry, gap, Costs(budget=bid), require_trend)
            base = development_rows(features, audit["start_date_inclusive"])
            available = int(base[base.entry_minute == entry].slug.nunique())
            result = metrics(trades)
        st.session_state.lab_result = dict(settings=settings, trades=trades, matched=matched, available=available, metrics=result)
        history = st.session_state.setdefault("lab_history", {})
        history[settings] = {"Entry minute": entry, "Minimum gap ($)": gap, "Bid amount ($)": bid, "Trend agreement": require_trend,
            "Trades": result["total_trades"], "Wins": result["winning_trades"], "Losses": result["losing_trades"],
            "Win rate (%)": result["win_percentage"], "Avg modeled result/trade ($)": result.get("expected_value_per_trade"),
            "Total modeled result ($)": result.get("total_net_profit"),
            "Modeled avg/day ($)": result["total_net_profit"] / 20 if result["total_net_profit"] is not None else None,
            "Modeled ROI (%)": result["roi"] * 100 if result["roi"] is not None else None,
            "95% win-rate lower bound (%)": wilson(result["winning_trades"], result["total_trades"])[0] * 100 if result["total_trades"] else None,
            "60+ trade sample": result["total_trades"] >= 60}
    saved = st.session_state.get("lab_result")
    if not saved or saved["settings"] != settings:
        st.info("Choose your settings and click Test strategy. Changing a setting does not silently rerun or change the previous result.")
    else:
        trades, result = saved["trades"], saved["metrics"]
        n = result["total_trades"]
        st.progress(1.0, text="Rule chosen → development history tested → score ready")
        st.write(f"**{saved['matched']:,} markets reached the gap** out of {saved['available']:,} with eligible data at this entry minute. **{saved['matched'] - n:,} matches were excluded** because usable prices, fee data or execution assumptions were insufficient.")
        st.caption(f"The rule skipped {saved['available'] - saved['matched']:,} eligible markets. The requested development window contains 1,920 intervals; missing reference observations reduce the available sample to {saved['available']:,} at this entry time.")
        if not n:
            st.info("No testable trades matched. No win rate or profit result can be reported.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Win rate", f"{result['win_percentage']:.2f}%")
            c2.metric("Wins", result["winning_trades"])
            c3.metric("Losses", result["losing_trades"])
            c4.metric("Trades tested", n)
            p1, p2, p3 = st.columns(3)
            p1.metric(f"Avg modeled result / ${bid} trade", f"${result['expected_value_per_trade']:,.2f}")
            p2.metric("Total modeled result", f"${result['total_net_profit']:,.2f}")
            p3.metric("Largest modeled drawdown", f"${result['maximum_drawdown']:,.2f}")
            lower, upper = wilson(result["winning_trades"], n)
            st.caption(f"Descriptive 95% win-rate interval: {lower:.1%}–{upper:.1%}. It assumes independent trades and is not adjusted for trying multiple settings.")
            if n < 60:
                st.info("Small sample: fewer than 60 trades. A high percentage here may be chance.")
            if result["win_percentage"] >= 80:
                st.write("**80% development target reached.** This is an in-sample observation, not a validated future win rate.")
            with st.expander("All test metrics"):
                st.dataframe(pd.DataFrame([{"Metric": key, "Value": str(value)} for key, value in result.items()]), hide_index=True, width="stretch")
            curve = trades[["start_utc", "net_profit"]].copy()
            curve["Cumulative modeled result"] = curve.net_profit.cumsum()
            st.plotly_chart(px.line(curve, x="start_utc", y="Cumulative modeled result"), width="stretch")
            daily = daily_rule_results(trades, audit["start_date_inclusive"])
            st.subheader("Daily income estimate · historical scenario")
            d1, d2, d3 = st.columns(3)
            d1.metric("Modeled average per calendar day", f"${daily['Modeled net result ($)'].mean():,.2f}")
            d2.metric("Best modeled day", f"${daily['Modeled net result ($)'].max():,.2f}")
            d3.metric("Worst modeled day", f"${daily['Modeled net result ($)'].min():,.2f}")
            st.caption("Average = this test's modeled net result divided by all 20 development calendar days, including zero-trade days. This is a historical daily scenario, not a forecast or guarantee of future income. Missing data and changing market conditions limit the estimate.")
            st.plotly_chart(px.bar(daily, x="Date", y="Modeled net result ($)"), width="stretch")
            st.download_button("Download daily scenario results", daily.to_csv(index=False), "daily_strategy_scenario.csv")
            with st.expander("Review the matching markets and exact rule details"):
                st.write("Direction is selected by above/below target at entry. The trend agreement filter is " + ("ON: the minutes 1–10 regression must point the same way." if require_trend else "OFF: no slope filter is applied.") + " A zero gap includes either side but skips exact equality.")
                st.dataframe(trades[["slug", "start_utc", "distance_usd", "predicted_outcome", "winning_outcome",
                                     "observed_contract_price", "observation_age_seconds", "purchase_price", "net_profit"]], hide_index=True, width="stretch")
                slug = st.selectbox("Historical interval to inspect", trades.slug.tolist())
                match = trades[trades.slug == slug].iloc[0]
                st.button("Open this result in Charts", on_click=open_lab_chart, args=(slug, match.local_day))
                st.download_button("Download this test's trades", trades.to_csv(index=False), "distance_rule_development_trades.csv")
    tried = [row for key, row in st.session_state.get("lab_history", {}).items() if key[0] == str(directory)]
    if tried:
        st.subheader("Compare the rules you have tested")
        table = pd.DataFrame(tried).sort_values(["60+ trade sample", "Win rate (%)", "Trades"], ascending=False, na_position="last")
        st.dataframe(table, hide_index=True, width="stretch")
        st.caption("Rules with at least 60 trades rank first, then by win percentage. A 100% score from only a few trades is not stronger evidence. Modeled ROI allows comparisons across different bid amounts; dollar results alone scale with the stake.")
        st.download_button("Download my rule comparison", table.to_csv(index=False), "my_development_rules.csv")
    st.warning(f"All dollar results assume fills from real historical observations plus 0.5¢/share half-spread, 0.5¢/share slippage, archived fees, a ${bid} total debit including fees and sufficient liquidity. Quotes older than 90 seconds are excluded. Historical asks/depth are missing, so real-world profitability is unverified. Raising the bid scales this scenario; it does not establish that larger fills were available.")
    st.caption("Tests and scores use development data only. The frozen validation result is unchanged. Trying more settings increases overfitting risk; selecting a new strategy requires new future validation. Your comparison list lasts only for this browser session unless downloaded.")


def optional_price(value):
    try:
        number = float(value)
        return number if np.isfinite(number) and number > 0 else None
    except (ValueError, TypeError):
        return None


@st.cache_data(show_spinner=False)
def recorded_chart_data(directory_name, slug, start_utc, end_utc, method, opening, settlement):
    """Read one already-downloaded response directly, without scanning raw/ or fetching data."""
    directory = Path(directory_name)
    start_ms = int(pd.Timestamp(start_utc).timestamp() * 1000)
    params = dict(symbol="BTC", eventStartTime=start_utc, variant="fifteen", endDate=end_utc)
    if method == "chainlink_btc_usd_twap_60s":
        params.update(twapEnabled="true", twapLookbackSeconds=60)
    url = "https://polymarket.com/api/crypto/price-history?" + urlencode(params)
    receipt_path = directory / "raw" / (hashlib.sha256(url.encode()).hexdigest() + ".receipt.json")
    rows, note, raw_count = [], "", 0
    if method not in {"chainlink_btc_usd_twap_60s", "chainlink_btc_usd_spot"}:
        note = "The historical reference method is unverified for this interval."
    elif receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        body_name = receipt.get("body_file", "")
        if receipt.get("url") != url or not body_name or Path(body_name).name != body_name:
            raise ValueError("The saved chart receipt does not match this interval")
        body = (directory / "raw" / body_name).read_bytes()
        if hashlib.sha256(body).hexdigest() != receipt["sha256"]:
            raise ValueError("The saved chart response failed its integrity check")
        payload = json.loads(body)
        if not isinstance(payload, list):
            raise ValueError("Unexpected historical chart response")
        seen = {}
        for sample in payload:
            timestamp = float(sample["timestamp"])
            price = optional_price(sample["value"])
            if not np.isfinite(timestamp) or price is None:
                raise ValueError("Invalid historical chart sample")
            if start_ms <= timestamp <= start_ms + 900000:
                if timestamp in seen and seen[timestamp] != price:
                    raise ValueError("Conflicting historical chart samples")
                seen[timestamp] = price
        for timestamp, price in sorted(seen.items()):
            rows.append(dict(second=(timestamp - start_ms) / 1000, price=price, source="Recorded historical chart"))
        raw_count = len(rows)
    else:
        note = "The finer historical chart response is unavailable; showing recorded minute observations only."
        minutes = load_csv(directory, "reference_minutes.csv")
        for sample in minutes[minutes.slug == slug].itertuples():
            price = optional_price(sample.price)
            if price is not None:
                rows.append(dict(second=int(sample.minute) * 60, price=price, source="Recorded minute / reported boundary"))
    for second, reported, label in [(0, opening, "Reported opening"), (900, settlement, "Reported settlement")]:
        value = optional_price(reported)
        existing = next((r for r in rows if r["second"] == second), None)
        if value is not None:
            if existing and abs(existing["price"] - value) > 0.005:
                raise ValueError(f"Historical chart disagrees with the {label.lower()} price")
            if not existing:
                rows.append(dict(second=second, price=value, source=label))
    frame = pd.DataFrame(rows, columns=["second", "price", "source"]).sort_values("second").reset_index(drop=True)
    return frame, raw_count, note


def interval_figure(samples, opening=None):
    """Connect neighboring recorded observations; explicitly break lines across gaps."""
    fig = go.Figure()
    if not samples.empty:
        spacing = np.diff(samples.second.to_numpy())
        spacing = spacing[spacing > 0]
        cadence = min(float(np.median(spacing)), 60.0) if len(spacing) else 0
        x, y, labels = [], [], []
        previous = None
        for row in samples.itertuples():
            if previous is not None and row.second - previous > 1.5 * cadence:
                x.append(None)
                y.append(None)
                labels.append("")
            x.append(row.second)
            y.append(row.price)
            labels.append(f"{int(row.second) // 60:02d}:{int(row.second) % 60:02d} · {row.source}")
            previous = row.second
        fig.add_scatter(x=x, y=y, text=labels, mode="lines+markers", name="BTC reference",
                        connectgaps=False, line=dict(color="#f7931a", width=2), marker=dict(size=4),
                        hovertemplate="%{text}<br>$%{y:,.2f}<extra></extra>")
    target = optional_price(opening)
    if target is not None:
        fig.add_hline(y=target, line_dash="dash", line_color="#6b7280", annotation_text=f"Price to beat ${target:,.2f}")
    fig.update_layout(height=480, margin=dict(l=20, r=20, t=35, b=35), hovermode="closest",
                      xaxis=dict(title="Time since market opened (mm:ss)", range=[0, 900],
                                 tickvals=list(range(0, 901, 60)), ticktext=[f"{i:02d}:00" for i in range(16)]),
                      yaxis=dict(title="BTC reference price ($)", tickformat=",.2f"))
    return fig


def move_chart_interval(options, delta):
    current = options.index(st.session_state.get("charts_interval", options[0]))
    st.session_state.charts_interval = options[max(0, min(len(options) - 1, current + delta))]


def open_view(name):
    st.session_state.dashboard_view = name


def show_welcome(audit, report):
    st.subheader("Strategy research · your review checklist")
    st.write("The goal is to find rules that work on real historical markets, after costs, and then check them on unseen data. Start by reviewing individual charts; compare candidate rules next.")
    if report:
        frozen = report["frozen_experiment"]
        m1, m2, m3 = st.columns(3)
        m1.metric("Markets downloaded", f"{audit['actual_markets_downloaded']:,}")
        m2.metric("Original strategy combinations compared", frozen["grid_size"])
        m3.metric("Original rule selected for validation", "Yes" if frozen["rule"] else "None yet")
        st.progress(1.0 if report.get("validation") else 2 / 3,
                    text="Research stages: review data → compare rules → validate a qualified rule")
        if not frozen["rule"]:
            st.info("Current checkpoint: the historical comparisons are available, but no rule passed the prespecified statistical screen. Positive modeled returns alone are not enough to select a strategy.")
    a, b, c = st.columns(3)
    with a:
        st.markdown("### 1 · Review the intervals")
        st.write("The orange line shows recorded Bitcoin prices. The dashed line is the opening price to beat. Empty stretches mean missing data.")
        st.button("Open Charts", on_click=open_view, args=("Charts",))
    with b:
        st.markdown("### 2 · Compare strategy rules")
        st.write("Compare entry times, trend strength and price filters using the first 20 days. Review trade counts, win rates and modeled returns together.")
        st.button("Compare historical strategies", on_click=open_view, args=("Development strategies",))
    with c:
        st.markdown("### 3 · Check the evidence")
        st.write("A selected rule must survive the final 10 days without retuning. Review missing data, execution assumptions and uncertainty before drawing conclusions.")
        st.button("Review validation decision", on_click=open_view, args=("Frozen validation",))
    if report:
        result = report["baseline_first_10_minute_trend"]["validation"]
        if result["accuracy"] is not None:
            st.write(f"**Baseline finding:** the basic trend predictor was right {result['accuracy']:.1%} of the time on usable validation markets—roughly 3 out of 4. This does not establish a profitable trading rule.")
    st.caption("Historical strategy research only. No wallet, deposits, live signals or trades are connected.")
    with st.expander("Plain-English glossary"):
        st.write("**Opening target / price to beat:** the reference price at the start of a 15-minute market. Up wins if settlement is at least this price; otherwise Down wins.")
        st.write("**Settlement:** the final reference price used to decide the winner. A tie counts as Up.")
        st.write("**Trend:** whether the recorded prices generally rise or fall.")
        st.write("**Momentum:** how much the price changed recently. **Volatility:** how much it bounced around.")
        st.write("**Contract price:** what one Up or Down share costs. A winning share pays $1; a losing one pays $0, before accounting for purchase costs and fees.")
        st.write("**Development data:** the first 20 days used to explore ideas. **Validation data:** the last 10 days used to check a fixed idea.")
        st.write("**Basis point:** 0.01%. **Modeled return:** a calculation using real observed prices plus assumptions about execution, not proof of a fill or profit.")


def show_charts(directory, audit):
    st.subheader("Charts · review a 15-minute interval")
    markets = load_csv(directory, "markets.csv").copy()
    markets = markets[markets.discovery_status == "found"].sort_values("start_ts")
    if markets.empty:
        st.info("No downloaded intervals are available to chart.")
        return
    local_start = pd.to_datetime(markets.start_utc, utc=True).dt.tz_convert(audit["timezone"])
    local_end = pd.to_datetime(markets.end_utc, utc=True).dt.tz_convert(audit["timezone"])
    markets["local_date"] = local_start.dt.strftime("%Y-%m-%d")
    markets["interval_label"] = local_start.dt.strftime("%H:%M:%S") + " – " + local_end.dt.strftime("%H:%M:%S")
    dates = sorted(markets.local_date.unique())
    day = st.selectbox("Date", dates, index=len(dates) - 1, key="charts_date")
    intervals = markets[markets.local_date == day]
    options = intervals.slug.tolist()
    labels = dict(zip(intervals.slug, intervals.interval_label))
    if st.session_state.get("charts_interval") not in options:
        st.session_state.charts_interval = options[0]
    slug = st.selectbox("15-minute interval", options, format_func=labels.get, key="charts_interval")
    index = options.index(slug)
    left, middle, right = st.columns([1, 3, 1])
    left.button("← Previous", disabled=index == 0, on_click=move_chart_interval, args=(options, -1))
    middle.caption(f"Interval {index + 1} of {len(options)} · {audit['timezone']}")
    right.button("Next →", disabled=index == len(options) - 1, on_click=move_chart_interval, args=(options, 1))
    record = intervals[intervals.slug == slug].iloc[0]
    st.write(f"**{day} · {labels[slug]}** · {record.reference_method.replace('_', ' ')}")
    opening, settlement = optional_price(record.opening_price), optional_price(record.settlement_price)
    a, b, c = st.columns(3)
    a.metric("Opening target", f"${opening:,.2f}" if opening is not None else "Unavailable")
    b.metric("Settlement", f"${settlement:,.2f}" if settlement is not None else "Unavailable")
    c.metric("Winning outcome", record.winning_outcome or "Unavailable")
    try:
        samples, raw_count, note = recorded_chart_data(str(directory), slug, record.start_utc, record.end_utc,
                                                     record.reference_method, record.opening_price, record.settlement_price)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        st.error(f"Cannot display this interval's recorded chart: {exc}")
        return
    if note:
        st.info(note)
    if not any(0 < second < 900 for second in samples.second):
        st.warning("No recorded price path is available inside this interval. Only reported boundary prices can be shown.")
    fig = interval_figure(samples, record.opening_price)
    if st.checkbox("Show minutes 1–10 trend line", value=True):
        references = load_csv(directory, "reference_minutes.csv")
        subset = references[references.slug == slug]
        prices = {int(row.minute): optional_price(row.price) for row in subset.itertuples()}
        if all(prices.get(i) is not None for i in range(11)):
            fitted = minute_features(prices, 10)
            if fitted:
                x = np.arange(1, 11)
                fig.add_scatter(x=x * 60, y=fitted["trend_slope_usd_per_minute"] * x + fitted["trend_intercept"],
                                mode="lines", name="Minutes 1–10 regression", line=dict(color="#2563eb", dash="dot"))
                matched = fitted["predicted_outcome"] == record.winning_outcome
                st.write(f"**First-10-minute trend:** {fitted['predicted_outcome']} · **Actual ending:** {record.winning_outcome or 'Unavailable'} · **Direction check:** {'Matched' if matched else 'Did not match'}")
    if st.checkbox("Mark entry minutes 10–13", value=True):
        for minute in (10, 11, 12, 13):
            fig.add_vline(x=minute * 60, line_dash="dot", line_color="#cbd5e1",
                          annotation_text=f"{minute}m", annotation_position="top")
    st.plotly_chart(fig, width="stretch")
    st.caption(f"{raw_count} original historical chart samples; {len(samples)} displayed observations including any reported boundaries. The time axis is in seconds. Historical samples are often 15 seconds apart, not every second. Lines connect neighboring observations; missing stretches are left disconnected.")
    if st.checkbox("Show Up/Down contract history"):
        history = load_csv(directory, "contract_history.csv")
        history = history[history.slug == slug].copy()
        if history.empty:
            st.info("No historical contract observations are available for this interval.")
        else:
            history["second"] = pd.to_numeric(history.timestamp) - int(record.start_ts)
            history["price"] = pd.to_numeric(history.price)
            st.plotly_chart(px.scatter(history, x="second", y="price", color="outcome",
                                      labels={"second": "Seconds since market opened", "price": "Observed contract price ($)"}), width="stretch")
            st.caption("These are actual historical observations, not executable bid/ask quotes.")
        targets = load_csv(directory, "contract_targets.csv")
        targets = targets[targets.slug == slug][["minute", "outcome", "exact_history_price", "last_observation_price", "last_observation_age_seconds"]].rename(columns={
            "minute": "Entry minute", "outcome": "Side", "exact_history_price": "Exact timestamp price ($)",
            "last_observation_price": "Last recorded price ($)", "last_observation_age_seconds": "Observation age (seconds)"})
        st.write("**Contract prices at the strategy decision times**")
        st.dataframe(targets.replace("", "Unavailable"), hide_index=True, width="stretch")
        st.caption("A $0.80 contract price means 80 cents per share before fees. The last recorded price may be stale; its age is shown. Blank exact-timestamp prices are not estimated. This table does not establish a purchasable ask or a $100 fill.")
    with st.expander("Recorded samples and download"):
        st.dataframe(samples, hide_index=True, width="stretch")
        st.download_button("Download this interval's observations", samples.to_csv(index=False), f"{slug}_chart.csv", "text/csv")


def main():
    st.set_page_config(page_title="Bitcoin 15-minute research", layout="wide")
    st.title("Bitcoin 15-minute research")
    st.caption("Real source data only · read-only research · no wallet connection")
    datasets = sorted((ROOT / "data").glob("*/audit.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not datasets:
        st.info("No collection has run yet. Run the collector using the command in README.md.")
        return
    selected = st.sidebar.selectbox("Collection window", datasets, format_func=lambda p: p.parent.name)
    directory = selected.parent
    audit = json.loads(selected.read_text())
    report_path = directory / "research_report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else None
    st.write(f"**{audit['start_date_inclusive']} through {audit['end_date_exclusive']} (exclusive)** · {audit['timezone']}")
    st.caption("Calendar-day boundaries use the selected timezone; all CSV timestamps are UTC.")
    if not audit["analysis_ready"]:
        st.warning("Some Bitcoin reference observations are missing. Available results use validated markets only; real-world profitability has not been demonstrated.")
    columns = st.columns(4)
    columns[0].metric("Actual markets downloaded", f"{audit['actual_markets_downloaded']:,}", help="Expected time slots do not count as downloaded markets.")
    columns[1].metric("Expected intervals", f"{audit['expected_intervals']:,}")
    columns[2].metric("BTC observations", f"{audit['reference_samples_available']:,} / {audit['reference_samples_required']:,}")
    columns[3].metric("Contract observations", f"{audit['contract_history_observations']:,}")
    if report:
        result = report["baseline_first_10_minute_trend"]["validation"]
        if result["accuracy"] is not None:
            st.info(f"Available validation result: {result['accuracy']:.2%} direction accuracy — {result['correct']:,} correct out of {result['markets']:,} usable markets. This is prediction accuracy, not a profit claim.")
    page = st.radio("View", ["Start here", "Charts", "Data quality", "Market explorer", "Trend analysis", "Development strategies", "Frozen validation"],
                    index=0, horizontal=True, label_visibility="collapsed", key="dashboard_view")
    # Render only the selected page. st.tabs eagerly executed every page, including
    # an expensive full integrity scan before any trend results could be sent.
    if page == "Start here":
        show_welcome(audit, report)
    elif page == "Charts":
        show_charts(directory, audit)
    elif page == "Data quality":
        st.subheader("Source access")
        for name, result in audit["api_probes"].items():
            st.write(f"**{name}**: {result['status']}")
            if result.get("detail"):
                st.code(result["detail"], language=None)
        if audit["status"] == "network_blocked":
            st.info("Polymarket access is blocked by this cloud environment's network policy. Enable the API domains in environment settings and rerun collection.")
        st.subheader("Coverage and missing data")
        coverage = pd.DataFrame([
            {"Requirement": "Actual market metadata", "Available": audit["actual_markets_downloaded"], "Required": audit["expected_intervals"]},
            {"Requirement": "Resolved outcomes", "Available": audit["resolved_winners"], "Required": audit["expected_intervals"]},
            {"Requirement": "BTC minute observations (0–15)", "Available": audit["reference_samples_available"], "Required": audit["reference_samples_required"]},
            {"Requirement": "Exact entry history observations", "Available": audit["exact_entry_history_observations"], "Required": audit["entry_observations_required"]},
            {"Requirement": "Historical order-book snapshots", "Available": audit["historical_orderbook_snapshots"], "Required": audit["entry_observations_required"]},
        ])
        st.dataframe(coverage, hide_index=True, width="stretch")
        st.caption("A historical contract-price observation or trade print does not establish that $100 could have been filled at that price.")
        st.caption("Full integrity verification reads thousands of files and may take several minutes. It runs only when you request it.")
        if st.button("Verify downloaded files"):
            with st.spinner("Checking saved files. Other views do not require this check."):
                failures = verify_artifacts(directory)
            if failures:
                st.error("Saved artifact integrity check failed: " + "; ".join(failures))
            else:
                st.success("Saved CSV and cached response hashes match. This verifies file integrity, not market completeness.")
        issues = load_csv(directory, "issues.csv")
        if not issues.empty:
            st.dataframe(issues, hide_index=True, width="stretch")
        st.subheader("CSV exports")
        filename = st.selectbox("CSV to download", list(audit["files"]))
        st.download_button("Download selected CSV", (directory / filename).read_bytes(), file_name=filename, mime="text/csv")
        st.download_button("Download completeness audit", selected.read_bytes(), file_name="audit.json", mime="application/json")
    elif page == "Market explorer":
        markets = load_csv(directory, "markets.csv")
        found_only = st.checkbox("Show only downloaded markets", value=True)
        view = markets[markets.discovery_status == "found"] if found_only else markets
        st.dataframe(view[["slug", "start_utc", "end_utc", "split", "discovery_status", "winning_outcome", "rules_status"]], hide_index=True, width="stretch")
        if view.empty:
            st.info("No actual markets have been downloaded. Turn off the filter to inspect the expected-interval checklist.")
        else:
            slug = st.selectbox("Market or expected interval", view.slug)
            record = markets[markets.slug == slug].iloc[0]
            st.write(f"**Source status:** {record.discovery_status} · **Winning outcome:** {record.winning_outcome or 'unavailable'}")
            if record.rules:
                with st.expander("Market settlement rules", expanded=False):
                    st.write(record.rules)
                    st.write("Resolution source:", record.resolution_source)
            references = load_csv(directory, "reference_minutes.csv")
            references = references[references.slug == slug].copy()
            references["price"] = pd.to_numeric(references["price"], errors="coerce")
            references["minute"] = pd.to_numeric(references["minute"])
            if references.price.notna().any():
                fig = px.scatter(references, x="minute", y="price", hover_data=["status"], labels={"price": "Reported BTC price ($)", "minute": "Minute"})
                prices = dict(zip(references.minute, references.price))
                feature = minute_features(prices, 10)
                if feature:
                    x = np.arange(1, 11)
                    fig.add_scatter(x=x, y=feature["trend_slope_usd_per_minute"] * x + feature["trend_intercept"], mode="lines", name="Minutes 1–10 regression")
                    fig.add_hline(y=prices[0], line_dash="dot", annotation_text="Opening reference")
                    st.write(f"**First-10-minute trend:** {feature['predicted_outcome']} · **Actual outcome:** {record.winning_outcome or 'unavailable'}")
                st.plotly_chart(fig, width="stretch")
                st.caption("Only actual reported observations are plotted. Missing prices are not interpolated.")
            else:
                st.info("The verified Bitcoin reference path is unavailable for this interval.")
            st.dataframe(references, hide_index=True, width="stretch")
            quotes = load_csv(directory, "contract_targets.csv")
            st.dataframe(quotes[quotes.slug == slug], hide_index=True, width="stretch")
    elif page == "Trend analysis":
        if report:
            st.subheader("Does the first 10 minutes predict settlement?")
            for split, result in report["baseline_first_10_minute_trend"].items():
                accuracy = result["accuracy"]
                st.write(f"**{split.title()}**: {result['correct']:,} / {result['markets']:,} correct" + (f" ({accuracy:.2%})" if accuracy is not None else ""))
                ci = result["wilson_95"]
                if ci[0] is not None:
                    st.caption(f"95% Wilson interval: {ci[0]:.2%}–{ci[1]:.2%}; this interval assumes independent markets.")
            st.info(f"{report['excluded_markets']:,} markets are excluded because required reference observations or validation checks are missing. Accuracy alone does not demonstrate a trading advantage.")
            st.caption("The baseline is the sign of the regression slope over minutes 1–10. A flat slope abstains. The final outcome is used only as the label.")
        else:
            st.info("Run the analysis command after collection. Only actual markets with validated reference paths can enter research.")
        for limitation in audit["limitations"]:
            st.write("• " + limitation)
    elif page == "Development strategies":
        show_simple_lab(directory, audit)
    elif page == "Frozen validation":
        if report:
            st.write("The first 20 calendar days determine one fixed rule. The last 10 days are evaluated only after that rule is saved. A failed training screen leaves the optimized holdout unrun.")
            st.json(report["frozen_experiment"])
            if report["validation"]:
                st.json(report["validation"])
                st.warning("Any positive P&L is conditional on the execution assumptions. Ten days provide limited independent evidence, and missing data may bias the sample. Real-world profitability has not been demonstrated.")
            else:
                st.info(report.get("conclusion", "No selected strategy is available."))
            st.download_button("Download research report", report_path.read_bytes(), "research_report.json")
        else:
            st.info("No validation has been run.")


if __name__ == "__main__":
    main()
