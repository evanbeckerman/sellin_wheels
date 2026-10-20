"""Research on real observations; modeled execution is always labeled a scenario.

No order submission, position management, or wallet implementation lives here.
"""
import hashlib
import itertools
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest, norm

from .collector import verify_artifacts, write_json


@dataclass(frozen=True)
class Costs:
    budget: float = 100.0  # total debit, including taker fees
    half_spread: float = 0.005  # ASSUMPTION, dollars/share, not observed history
    slippage: float = 0.005  # ASSUMPTION, dollars/share
    max_quote_age_seconds: int = 90


@dataclass(frozen=True)
class Rule:
    entry_minute: int
    min_slope_bps: float = 0
    min_distance_bps: float = 0
    min_momentum_3_bps: float = 0
    max_volatility_bps: float = 100
    min_contract_price: float = 0.5
    max_contract_price: float = 0.95


def minute_features(prices, entry):
    """Trend uses minutes 1–10 only. Entry features use no observation after entry."""
    required = set(range(11)) | set(range(entry - 5, entry + 1))
    if not all(i in prices and np.isfinite(prices[i]) and prices[i] > 0 for i in required):
        return None
    opening = prices[0]
    x = np.arange(1, 11, dtype=float)
    y = np.array([prices[i] for i in range(1, 11)])
    slope, intercept = np.polyfit(x, y, 1)
    direction = int(np.sign(slope))
    changes = np.diff(y)
    signs = np.sign(changes[changes != 0])
    reversal_mask = signs[1:] != signs[:-1]
    nonzero_changes = changes[changes != 0]
    trend_prediction = "Up" if direction > 0 else "Down" if direction < 0 else "Abstain"
    returns = np.diff(y) / y[:-1] * 10000
    fitted = slope * x + intercept
    total = np.sum((y - y.mean()) ** 2)
    result = {
        "entry_minute": entry, "trend_slope_usd_per_minute": float(slope),
        "trend_intercept": float(intercept), "trend_slope_bps_per_minute": float(slope / opening * 10000),
        "trend_r_squared": float(1 - np.sum((y - fitted) ** 2) / total) if total else 0.0,
        "predicted_outcome": trend_prediction,
        "distance_usd": prices[entry] - opening,
        "distance_bps": (prices[entry] / opening - 1) * 10000,
        "percentage_change": (prices[entry] / opening - 1) * 100,
        "volatility_bps": float(np.std(returns, ddof=1)),
        "trend_consistency": float(np.mean(np.sign(changes) == direction)) if direction else 0.0,
        "reversal_count": int(np.sum(reversal_mask)),
        "reversal_magnitude_usd": float(np.sum(np.abs(nonzero_changes[1:][reversal_mask]))),
        "time_remaining_seconds": (15 - entry) * 60,
    }
    for lag in (1, 2, 3, 5):
        result[f"momentum_{lag}_bps"] = (prices[entry] / prices[entry - lag] - 1) * 10000
    return result


def load_features(directory):
    directory = Path(directory)
    failures = verify_artifacts(directory)
    if failures:
        raise ValueError("; ".join(failures))
    audit = json.loads((directory / "audit.json").read_text())
    eligible = set(audit.get("analysis_eligible_slugs", []))
    markets = pd.read_csv(directory / "markets.csv", dtype=str, keep_default_na=False)
    refs = pd.read_csv(directory / "reference_minutes.csv", dtype={"slug": str})
    targets = pd.read_csv(directory / "contract_targets.csv", dtype={"slug": str, "token_id": str})
    quote_lookup = {(r.slug, r.outcome, int(r.minute)): r for r in targets.itertuples()}
    refs_lookup = {slug: dict(zip(group.minute, group.price)) for slug, group in refs.groupby("slug")}
    rows = []
    for market in markets.itertuples():
        if market.slug not in eligible or market.winning_outcome not in {"Up", "Down"}:
            continue
        prices = refs_lookup.get(market.slug, {})
        for entry in (10, 11, 12, 13):
            features = minute_features(prices, entry)
            if features is None or features["predicted_outcome"] == "Abstain":
                continue
            q = quote_lookup.get((market.slug, features["predicted_outcome"], entry))
            fee_rate, fee_exponent = None, None
            metadata = json.loads(market.fee_metadata_json or "{}")
            if metadata.get("feesEnabled") is False:
                fee_rate, fee_exponent = 0.0, 1
            elif metadata.get("feesEnabled") is True:
                schedule = metadata.get("feeSchedule") or {}
                # Only the observed and documented exponent-1 schedule is supported.
                if schedule.get("exponent") == 1 and schedule.get("takerOnly") is True:
                    fee_rate, fee_exponent = float(schedule["rate"]), 1
            row = {"slug": market.slug, "start_ts": int(market.start_ts), "start_utc": market.start_utc,
                   "split": market.split, "winning_outcome": market.winning_outcome,
                   "prediction_correct": features["predicted_outcome"] == market.winning_outcome,
                   "reference_method": market.reference_method, "fee_rate": fee_rate,
                   "fee_exponent": fee_exponent, **features}
            row.update(observed_contract_price=float(q.last_observation_price) if q is not None and pd.notna(q.last_observation_price) else np.nan,
                       observation_age_seconds=float(q.last_observation_age_seconds) if q is not None and pd.notna(q.last_observation_age_seconds) else np.nan,
                       observation_ts=float(q.last_observation_ts) if q is not None and pd.notna(q.last_observation_ts) else np.nan,
                       historical_ask=float(q.historical_ask) if q is not None and pd.notna(q.historical_ask) else np.nan,
                       historical_depth_usd=float(q.historical_depth_usd) if q is not None and pd.notna(q.historical_depth_usd) else np.nan)
            rows.append(row)
    return pd.DataFrame(rows), audit


def apply_rule(features, rule):
    if features.empty:
        return features.copy()
    f = features
    sign = np.where(f.predicted_outcome == "Up", 1, -1)
    mask = ((f.entry_minute == rule.entry_minute)
            & (f.trend_slope_bps_per_minute.abs() >= rule.min_slope_bps)
            & (f.distance_bps * sign >= rule.min_distance_bps)
            & (f.momentum_3_bps * sign >= rule.min_momentum_3_bps)
            & (f.volatility_bps <= rule.max_volatility_bps)
            & f.observed_contract_price.between(rule.min_contract_price, rule.max_contract_price))
    return f[mask].copy()


def scenario_trades(features, rule, costs=Costs(), strict=False):
    f = apply_rule(features, rule)
    if f.empty:
        return f
    f = f[(f.observation_age_seconds <= costs.max_quote_age_seconds)
          & (f.observation_age_seconds >= 0) & f.fee_rate.notna()].copy()
    if strict:
        f = f[f.historical_ask.notna() & (f.historical_depth_usd >= costs.budget)].copy()
        f["purchase_price"] = f.historical_ask
    else:
        f["purchase_price"] = f.observed_contract_price + costs.half_spread + costs.slippage
    f = f[f.purchase_price.between(0.00001, 0.99999)].copy()
    # Fee schedule comes from the resolved market's archived metadata. Its historical
    # immutability is not independently proven; this assumption is part of the scenario.
    f["fee_per_share"] = f.fee_rate * f.purchase_price * (1 - f.purchase_price)
    f["shares"] = costs.budget / (f.purchase_price + f.fee_per_share)
    f["capital"] = costs.budget
    f["fee_paid"] = f.shares * f.fee_per_share
    f["payout"] = np.where(f.prediction_correct, f.shares, 0.0)
    f["net_profit"] = f.payout - f.capital
    f["break_even_probability"] = f.purchase_price + f.fee_per_share
    f["execution_basis"] = "historical_ask_and_depth" if strict else "ASSUMED_FILL_USING_REAL_HISTORY"
    return f.sort_values("start_ts")


def wilson(wins, total, alpha=0.05):
    if not total:
        return [None, None]
    z = norm.ppf(1 - alpha / 2)
    p = wins / total
    center = (p + z * z / (2 * total)) / (1 + z * z / total)
    radius = z * np.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return [float(max(0, center - radius)), float(min(1, center + radius))]


def metrics(trades):
    n = len(trades)
    if not n:
        return {"total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                "win_percentage": None, "total_net_profit": None, "roi": None,
                "maximum_drawdown": None, "profit_factor": None, "expected_value_per_trade": None}
    wins = trades[trades.prediction_correct]
    losses = trades[~trades.prediction_correct]
    profit = trades.net_profit
    equity = np.r_[0.0, profit.cumsum().to_numpy()]
    loss_total = -profit[profit < 0].sum()
    return {
        "total_trades": n, "winning_trades": len(wins), "losing_trades": len(losses),
        "win_percentage": float(100 * len(wins) / n), "win_rate_wilson_95": wilson(len(wins), n),
        "average_contract_purchase_price": float(trades.purchase_price.mean()),
        "average_profit_per_winning_trade": float(wins.net_profit.mean()) if len(wins) else None,
        "average_loss_per_losing_trade": float(-losses.net_profit.mean()) if len(losses) else None,
        "total_net_profit": float(profit.sum()), "roi": float(profit.sum() / trades.capital.sum()),
        "maximum_drawdown": float(np.max(np.maximum.accumulate(equity) - equity)),
        "profit_factor": float(profit[profit > 0].sum() / loss_total) if loss_total else None,
        "expected_value_per_trade": float(profit.mean()),
        "break_even_win_rate_share_weighted": float(trades.capital.sum() / trades.shares.sum()),
        "total_fees": float(trades.fee_paid.sum()),
    }


def bootstrap_days(trades, all_day_labels, samples=10000, alpha=0.05):
    """Resample complete days including days without trades, retaining within-day dependence."""
    if trades.empty:
        return {"ev_interval": [None, None], "days": len(all_day_labels), "positive_ev_reliable": False}
    grouped = trades.assign(day=trades.local_day).groupby("day").agg(profit=("net_profit", "sum"), n=("net_profit", "size"))
    grouped = grouped.reindex(all_day_labels, fill_value=0)
    rng = np.random.default_rng(20261019)
    indices = rng.integers(0, len(grouped), size=(samples, len(grouped)))
    profits = grouped.profit.to_numpy()[indices].sum(axis=1)
    counts = grouped.n.to_numpy()[indices].sum(axis=1)
    values = profits[counts > 0] / counts[counts > 0]
    interval = np.quantile(values, [alpha / 2, 1 - alpha / 2]).tolist() if len(values) else [None, None]
    return {"ev_interval": interval, "days": len(grouped), "positive_ev_reliable": bool(interval[0] is not None and interval[0] > 0),
            "method": "whole-day block bootstrap; execution assumptions are not covered by this interval"}


def rule_grid():
    # Prespecified, small search; never regenerated using validation outcomes.
    return [Rule(entry, slope, distance, momentum, vol, 0.5, cap)
            for entry, slope, distance, momentum, vol, cap in itertools.product(
                (10, 11, 12, 13), (0, 0.25, 0.75), (0, 3), (0, 1), (3, 100), (0.85, 0.95))]


def add_local_day(features, timezone):
    f = features.copy()
    if not f.empty:
        f["local_day"] = pd.to_datetime(f.start_ts, unit="s", utc=True).dt.tz_convert(timezone).dt.strftime("%Y-%m-%d")
    return f


def run_research(directory, costs=Costs()):
    directory = Path(directory)
    features, audit = load_features(directory)
    if features.empty:
        raise ValueError("No real markets have a validated 1–10 minute reference path; research remains blocked")
    if audit["development_validation_split"] != "first 20 / final 10 complete local days":
        raise ValueError("Research requires the fixed 30-day window")
    features = add_local_day(features, audit["timezone"])
    features.to_csv(directory / "features.csv", index=False)
    development = features[features.split == "development"].copy()
    # The selection loop receives only development rows. Holdout rows are accessed after freezing.
    grid = rule_grid()
    signature = hashlib.sha256(json.dumps({"files": audit["files"], "costs": asdict(costs),
        "engine_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, sort_keys=True).encode()).hexdigest()
    frozen_path = directory / "frozen_research.json"
    training_rows = []
    for number, rule in enumerate(grid):
        trades = scenario_trades(development, rule, costs)
        m = metrics(trades)
        lower = wilson(m["winning_trades"], m["total_trades"], alpha=0.05 / len(grid))[0]
        # Search-adjusted screening plus a conservative bound using the largest per-trade
        # break-even threshold. This is not proof of executable returns.
        conservative_be = float(trades.break_even_probability.max()) if not trades.empty else 1.0
        qualifies = m["total_trades"] >= 60 and lower is not None and lower > conservative_be and (m["total_net_profit"] or 0) > 0
        training_rows.append({"rule_id": number, **asdict(rule), **{k: v for k, v in m.items() if not isinstance(v, list)},
                              "search_adjusted_win_lower_bound": lower, "qualifies": qualifies})
    rankings = pd.DataFrame(training_rows).sort_values(["qualifies", "total_net_profit"], ascending=False, na_position="last")
    rankings.to_csv(directory / "training_strategies.csv", index=False)
    if frozen_path.exists():
        frozen = json.loads(frozen_path.read_text())
        if frozen["signature"] != signature:
            raise ValueError("Frozen experiment differs from these inputs or costs. Do not retune using this exposed holdout.")
    else:
        candidates = rankings[rankings.qualifies]
        chosen_id = int(candidates.iloc[0].rule_id) if len(candidates) else None
        frozen = {"signature": signature, "rule": asdict(grid[chosen_id]) if chosen_id is not None else None,
                  "rule_id": chosen_id, "costs": asdict(costs), "grid_size": len(grid),
                  "selection_data": "development only", "selection_rule": "at least 60 training trades, positive scenario P&L, Bonferroni-adjusted Wilson lower bound above maximum per-trade break-even probability",
                  "status": "frozen_before_holdout_evaluation"}
        write_json(frozen_path, frozen)
    validation = features[features.split == "validation"].copy()
    training_baseline = development[development.entry_minute == 10]
    majority = "Up" if (training_baseline.winning_outcome == "Up").sum() >= (training_baseline.winning_outcome == "Down").sum() else "Down"
    baseline = {}
    for split, group in (("development", development), ("validation", validation)):
        # Prespecified minute-10 slope predictor, not a tuned strategy.
        f = group[group.entry_minute == 10]
        n, wins = len(f), int(f.prediction_correct.sum())
        baseline[split] = {"markets": n, "correct": wins, "accuracy": wins / n if n else None,
                           "wilson_95": wilson(wins, n),
                           "binomial_p_vs_50_percent": float(binomtest(wins, n, 0.5, alternative="greater").pvalue) if n else None,
                           "up_outcome_fraction": float((f.winning_outcome == "Up").mean()) if n else None,
                           "caution": "Binomial p-value assumes independent markets; serial dependence and class imbalance matter. Accuracy is not profitability."}
        constant_correct = f.winning_outcome == majority
        trend_only = int((f.prediction_correct & ~constant_correct).sum())
        constant_only = int((~f.prediction_correct & constant_correct).sum())
        discordant = trend_only + constant_only
        baseline[split].update(training_majority_prediction=majority,
                               majority_baseline_accuracy=float(constant_correct.mean()) if n else None,
                               paired_p_vs_training_majority=float(binomtest(trend_only, discordant, 0.5, alternative="greater").pvalue) if discordant else None)
        start = pd.Timestamp(audit["start_date_inclusive"])
        days = range(20) if split == "development" else range(20, 30)
        labels = [(start + pd.Timedelta(days=d)).strftime("%Y-%m-%d") for d in days]
        accuracy_blocks = f.assign(net_profit=f.prediction_correct.astype(float))
        baseline[split]["day_block_accuracy_interval_95"] = bootstrap_days(accuracy_blocks, labels)["ev_interval"]
    report = {"data_window_complete": audit.get("collection_complete", False), "eligible_markets": int(features.slug.nunique()),
              "excluded_markets": audit["expected_intervals"] - features.slug.nunique(),
              "baseline_first_10_minute_trend": baseline, "frozen_experiment": frozen,
              "execution_status": "UNVERIFIED: historical asks and depth are unavailable; all P&L below is a modeled execution scenario using real source observations",
              "real_world_profitability_demonstrated": False, "validation": None}
    if frozen["rule"] is not None:
        rule = Rule(**frozen["rule"])
        train_trades = scenario_trades(development, rule, costs)
        validation_trades = scenario_trades(validation, rule, costs)
        selected = pd.concat([train_trades, validation_trades], ignore_index=True)
        selected.to_csv(directory / "selected_scenario_trades.csv", index=False)
        start = pd.Timestamp(audit["start_date_inclusive"])
        validation_days = [(start + pd.Timedelta(days=d)).strftime("%Y-%m-%d") for d in range(20, 30)]
        report["validation"] = {"metrics": metrics(validation_trades), "day_bootstrap": bootstrap_days(validation_trades, validation_days),
                                "strict_executable_trades": len(scenario_trades(validation, rule, costs, strict=True)),
                                "training_metrics": metrics(train_trades)}
    else:
        report["conclusion"] = "No rule passed the prespecified training advantage screen. No optimized strategy was evaluated on the holdout."
    write_json(directory / "research_report.json", report)
    return report
