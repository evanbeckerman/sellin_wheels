"""Artificial numerical examples verify engine math, never establish trading returns."""
import numpy as np
import pandas as pd
import pytest

from pm_btc.research import Costs, Rule, metrics, minute_features, scenario_trades, wilson, run_research


def sample_features():
    prices = {i: 100.0 + i for i in range(16)}
    features = minute_features(prices, 10)
    return pd.DataFrame([{**features, "start_ts": 1000, "observed_contract_price": 0.8,
                          "observation_age_seconds": 20, "historical_ask": np.nan,
                          "historical_depth_usd": np.nan, "fee_rate": 0.07,
                          "prediction_correct": True}])


def test_future_prices_cannot_change_entry_features():
    prices = {i: 100 + i for i in range(16)}
    before = minute_features(prices, 10)
    for i in range(11, 16):
        prices[i] = 1000000 - i
    assert minute_features(prices, 10) == before
    assert before["trend_slope_usd_per_minute"] == pytest.approx(1)
    assert before["reversal_count"] == 0


def test_missing_interior_minute_abstains():
    p = {i: 100 + i for i in range(16)}
    del p[6]
    assert minute_features(p, 10) is None


def test_exact_100_dollar_budget_includes_fee_and_all_costs():
    trades = scenario_trades(sample_features(), Rule(10), Costs())
    row = trades.iloc[0]
    assert row.purchase_price == pytest.approx(0.81)
    assert row.shares * row.purchase_price + row.fee_paid == pytest.approx(100)
    assert row.net_profit == pytest.approx(row.shares - 100)


def test_strict_execution_does_not_invent_asks_or_depth():
    assert scenario_trades(sample_features(), Rule(10), strict=True).empty


def test_stale_history_and_missing_fees_prevent_scenario_trade():
    f = sample_features()
    f.loc[0, "observation_age_seconds"] = 91
    assert scenario_trades(f, Rule(10)).empty
    f.loc[0, "observation_age_seconds"] = 20
    f.loc[0, "fee_rate"] = np.nan
    assert scenario_trades(f, Rule(10)).empty


def test_loss_is_full_budget_and_drawdown_includes_initial_peak():
    f = sample_features()
    f.loc[0, "prediction_correct"] = False
    trades = scenario_trades(f, Rule(10))
    result = metrics(trades)
    assert result["total_net_profit"] == -100
    assert result["maximum_drawdown"] == 100
    assert result["average_loss_per_losing_trade"] == 100


def test_no_trades_have_no_profit_claim():
    result = metrics(pd.DataFrame())
    assert result["total_trades"] == 0
    assert result["total_net_profit"] is None
    assert wilson(0, 0) == [None, None]


def test_training_failure_leaves_optimized_holdout_unrun_and_freezes_costs(tmp_path, monkeypatch):
    f = sample_features()
    f["split"] = "development"
    f["slug"] = "artificial-test-only"
    f["winning_outcome"] = "Up"
    f["start_ts"] = 1760000400
    f["start_utc"] = "2025-10-09T10:20:00+00:00"
    audit = {"files": {}, "development_validation_split": "first 20 / final 10 complete local days",
             "timezone": "UTC", "start_date_inclusive": "2025-09-19", "expected_intervals": 2880,
             "collection_complete": False}
    monkeypatch.setattr("pm_btc.research.load_features", lambda _: (f, audit))
    report = run_research(tmp_path)
    assert report["frozen_experiment"]["rule"] is None
    assert report["validation"] is None
    assert report["real_world_profitability_demonstrated"] is False
    with pytest.raises(ValueError, match="Frozen experiment differs"):
        run_research(tmp_path, Costs(slippage=0.02))
