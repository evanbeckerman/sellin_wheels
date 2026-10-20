"""Numerical fixtures verify the distance rule, not a claim of investment performance."""
import pandas as pd
import pytest

from app import daily_rule_results, distance_rule_trades
from pm_btc.research import Costs


def data():
    rows, quotes = [], []
    for i, (distance, trend) in enumerate([(50, 'Up'), (-50, 'Up'), (49, 'Down'), (0, 'Up')]):
        slug = f'artificial-{i}'
        rows.append(dict(slug=slug, split='development', local_day='2025-09-20', entry_minute=10,
                         start_ts=1000+i*900, predicted_outcome=trend, winning_outcome='Down',
                         prediction_correct=False, distance_usd=distance, distance_bps=distance,
                         momentum_3_bps=100, trend_slope_bps_per_minute=1, volatility_bps=2, fee_rate=0.07))
        for side, price in [('Up', 0.8), ('Down', 0.2)]:
            quotes.append(dict(slug=slug, minute=10, outcome=side, last_observation_price=price,
                               last_observation_age_seconds=5, last_observation_ts=1000+i*900+595,
                               historical_ask=None, historical_depth_usd=None))
    return pd.DataFrame(rows), pd.DataFrame(quotes)


def test_gap_is_dollars_inclusive_and_uses_the_correct_side_price():
    f, q = data()
    trades, matched = distance_rule_trades(f, q, '2025-09-19', 10, 50)
    assert matched == len(trades) == 2
    down = trades[trades.distance_usd < 0].iloc[0]
    assert down.predicted_outcome == 'Down'
    assert down.observed_contract_price == pytest.approx(0.2)
    assert down.purchase_price == pytest.approx(0.21)
    assert bool(down.prediction_correct)


def test_zero_gap_skips_exact_target_and_optional_trend_is_separate():
    f, q = data()
    all_trades, _ = distance_rule_trades(f, q, '2025-09-19', 10, 0)
    assert len(all_trades) == 3
    aligned, _ = distance_rule_trades(f, q, '2025-09-19', 10, 50, require_trend=True)
    assert len(aligned) == 1 and aligned.iloc[0].predicted_outcome == 'Up'


def test_holdout_rows_cannot_change_results():
    f, q = data()
    before, _ = distance_rule_trades(f, q, '2025-09-19', 10, 50)
    extra = f.iloc[[0]].assign(slug='held-out', split='validation', local_day='2025-10-15')
    after, _ = distance_rule_trades(pd.concat([f, extra]), q, '2025-09-19', 10, 50)
    pd.testing.assert_frame_equal(before, after)


def test_bid_scales_the_scenario_and_daily_average_includes_zero_trade_days():
    f, q = data()
    small, _ = distance_rule_trades(f, q, '2025-09-19', 10, 50, Costs(budget=50))
    large, _ = distance_rule_trades(f, q, '2025-09-19', 10, 50, Costs(budget=100))
    assert large.net_profit.sum() == pytest.approx(2*small.net_profit.sum())
    assert (large.capital == 100).all()
    daily = daily_rule_results(large, '2025-09-19')
    assert len(daily) == 20
    assert (daily.Trades == 0).sum() == 19
    assert daily['Modeled net result ($)'].mean() == pytest.approx(large.net_profit.sum()/20)


def test_no_matches_and_bad_settings():
    f, q = data()
    empty, matched = distance_rule_trades(f, q, '2025-09-19', 10, 10000)
    assert empty.empty and matched == 0
    with pytest.raises(ValueError):
        distance_rule_trades(f, q, '2025-09-19', 9, 50)
