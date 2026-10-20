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
from pm_btc.research import Costs, Rule, metrics, minute_features, scenario_trades

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
        m2.metric("Strategy combinations compared", frozen["grid_size"])
        m3.metric("Rule selected for validation", "Yes" if frozen["rule"] else "None yet")
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
        st.subheader("Development data only")
        st.warning("Execution scenario: historical observations are real; the fill, spread, slippage and available $100 liquidity are assumptions. These results do not verify executable profits.")
        feature_path = directory / "features.csv"
        if not feature_path.exists():
            st.info("Development controls become available after analysis has produced validated features.")
        else:
            features = load_csv(directory, "features.csv", text_columns=False)
            development = features[features.split == "development"]
            a, b, c = st.columns(3)
            entry = a.selectbox("Entry minute", [10, 11, 12, 13])
            slope = a.number_input("Minimum trend slope (basis points/minute)", min_value=0.0, value=0.25, step=0.25)
            distance = a.number_input("Minimum distance in trend direction (basis points)", min_value=0.0, value=0.0, step=1.0)
            momentum = b.number_input("Minimum 3-minute momentum (basis points)", min_value=0.0, value=0.0, step=1.0)
            volatility = b.number_input("Maximum volatility (basis points)", min_value=0.01, value=100.0, step=1.0)
            minimum = b.slider("Minimum observed contract price", 0.01, 0.99, 0.50, 0.01)
            maximum = c.slider("Maximum observed contract price", 0.01, 0.99, 0.95, 0.01)
            half_spread = c.number_input("Assumed half-spread ($/share)", min_value=0.0, value=0.005, step=0.005, format="%.3f")
            slippage = c.number_input("Assumed slippage ($/share)", min_value=0.0, value=0.005, step=0.005, format="%.3f")
            strict = st.checkbox("Require observed historical ask and sufficient depth", value=True)
            rule = Rule(entry, slope, distance, momentum, volatility, minimum, maximum)
            trades = scenario_trades(development, rule, Costs(half_spread=half_spread, slippage=slippage), strict=strict)
            if trades.empty:
                st.info("No qualifying trades with these data requirements. Historical ask/depth evidence is currently unavailable.")
            else:
                result = metrics(trades)
                st.dataframe(pd.DataFrame([{"Metric": k, "Value": str(v)} for k, v in result.items()]), hide_index=True, width="stretch")
                curve = trades[["start_utc", "net_profit"]].copy()
                curve["Cumulative scenario P&L"] = curve.net_profit.cumsum()
                curve["Scenario drawdown"] = np.maximum.accumulate(np.r_[0.0, curve["Cumulative scenario P&L"]])[1:] - curve["Cumulative scenario P&L"]
                st.plotly_chart(px.line(curve, x="start_utc", y=["Cumulative scenario P&L", "Scenario drawdown"]), width="stretch")
                st.download_button("Download development scenario trades", trades.to_csv(index=False), "development_scenario_trades.csv")
            ranking_path = directory / "training_strategies.csv"
            if ranking_path.exists():
                st.subheader("Historical strategy comparison · development data only")
                ranking = load_csv(directory, "training_strategies.csv", text_columns=False)
                st.caption("Compare the available evidence, not just the highest win rate. Rows are ranked by the fixed statistical screen, then modeled return. These are candidate rules, not proven winners.")
                readable = ranking[["rule_id", "entry_minute", "total_trades", "win_percentage",
                                    "average_contract_purchase_price", "total_net_profit",
                                    "maximum_drawdown", "expected_value_per_trade", "qualifies"]].rename(columns={
                    "rule_id": "Rule ID", "entry_minute": "Entry minute", "total_trades": "Trades reviewed",
                    "win_percentage": "Correct direction (%)", "average_contract_purchase_price": "Avg purchase price ($)",
                    "total_net_profit": "Modeled result ($)", "maximum_drawdown": "Largest modeled drawdown ($)",
                    "expected_value_per_trade": "Avg modeled result/trade ($)", "qualifies": "Passed evidence screen"})
                st.dataframe(readable, hide_index=True, width="stretch")
                with st.expander("Inspect every rule threshold and detailed metric"):
                    st.dataframe(ranking, hide_index=True, width="stretch")
                comparison = ranking.groupby("entry_minute", as_index=False).agg(best_training_scenario_profit=("total_net_profit", "max"), qualifying_rules=("qualifies", "sum"))
                st.dataframe(comparison, hide_index=True, width="stretch")
                st.download_button("Download every training strategy", ranking_path.read_bytes(), "training_strategies.csv")
        st.caption("Changing these controls affects development data only. It does not alter the frozen validation rule. Each trade uses a $100 total debit including the modeled fee; ROI is return on deployed trade capital, not a funded-account return.")
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
