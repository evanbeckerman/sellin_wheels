"""Local research dashboard. All unavailable observations remain explicitly missing."""
import json
from pathlib import Path

import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st

from pm_btc.collector import verify_artifacts
from pm_btc.research import Costs, Rule, load_features, metrics, minute_features, scenario_trades

ROOT = Path(__file__).resolve().parent


def load_csv(directory, filename):
    # Token identifiers can exceed integer precision: retain exact strings.
    return pd.read_csv(directory / filename, dtype=str, keep_default_na=False)


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
    st.write(f"**{audit['start_date_inclusive']} through {audit['end_date_exclusive']} (exclusive)** · {audit['timezone']}")
    st.caption("Calendar-day boundaries use the selected timezone; all CSV timestamps are UTC.")
    if not audit["analysis_ready"]:
        st.warning("Data collection is incomplete. No prediction accuracy or profitability results are available.")
    columns = st.columns(4)
    columns[0].metric("Actual markets downloaded", f"{audit['actual_markets_downloaded']:,}", help="Expected time slots do not count as downloaded markets.")
    columns[1].metric("Expected intervals", f"{audit['expected_intervals']:,}")
    columns[2].metric("BTC observations", f"{audit['reference_samples_available']:,} / {audit['reference_samples_required']:,}")
    columns[3].metric("Contract observations", f"{audit['contract_history_observations']:,}")
    quality, explorer, research, strategies, validation = st.tabs(["Data quality", "Market explorer", "Trend analysis", "Development strategies", "Frozen validation"])
    with quality:
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
        failures = verify_artifacts(directory)
        if failures:
            st.error("Saved artifact integrity check failed: " + "; ".join(failures))
        else:
            st.success("Saved CSV and cached response hashes match. This verifies file integrity, not market completeness.")
        issues = load_csv(directory, "issues.csv")
        if not issues.empty:
            st.dataframe(issues, hide_index=True, width="stretch")
        st.subheader("CSV exports")
        for filename in audit["files"]:
            st.download_button(filename, (directory / filename).read_bytes(), file_name=filename, mime="text/csv", key=filename)
        st.download_button("Download completeness audit", selected.read_bytes(), file_name="audit.json", mime="application/json")
    with explorer:
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
    with research:
        report_path = directory / "research_report.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else None
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
    with strategies:
        st.subheader("Development data only")
        st.warning("Execution scenario: historical observations are real; the fill, spread, slippage and available $100 liquidity are assumptions. These results do not verify executable profits.")
        feature_path = directory / "features.csv"
        if not feature_path.exists():
            st.info("Development controls become available after analysis has produced validated features.")
        else:
            features = pd.read_csv(feature_path)
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
                st.write("Prespecified training search (ranked by the fixed selection screen, then scenario P&L)")
                ranking = pd.read_csv(ranking_path)
                st.dataframe(ranking.head(40), hide_index=True, width="stretch")
                comparison = ranking.groupby("entry_minute", as_index=False).agg(best_training_scenario_profit=("total_net_profit", "max"), qualifying_rules=("qualifies", "sum"))
                st.dataframe(comparison, hide_index=True, width="stretch")
                st.download_button("Download every training strategy", ranking_path.read_bytes(), "training_strategies.csv")
        st.caption("Changing these controls affects development data only. It does not alter the frozen validation rule. Each trade uses a $100 total debit including the modeled fee; ROI is return on deployed trade capital, not a funded-account return.")
    with validation:
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
