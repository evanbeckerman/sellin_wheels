"""Verify real bundled-study navigation without an automatic bulk integrity scan."""
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def dashboard():
    if not list((ROOT / 'data').glob('*/research_report.json')):
        pytest.skip('Bundled study must be unpacked for dashboard integration checks')
    return AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30)


def test_results_render_without_scanning_raw_files(dashboard):
    with patch('pm_btc.collector.verify_artifacts', side_effect=AssertionError('Unexpected automatic file scan')):
        at = dashboard.run()
        assert not at.exception
        assert at.radio[0].value == 'Start here'
        assert any('75.68%' in item.value for item in at.info)
        at.radio[0].set_value('Trend analysis').run()
        assert any('613 / 810' in item.value for item in at.markdown)
        at.radio[0].set_value('Data quality').run()
        assert not at.exception
        assert any(button.label == 'Verify downloaded files' for button in at.button)


def test_other_pages_render_on_selection(dashboard):
    at = dashboard.run()
    for page in ['Market explorer', 'Development strategies', 'Frozen validation']:
        at.radio[0].set_value(page).run()
        assert not at.exception, [e.message for e in at.exception]
    assert any('No rule passed' in item.value for item in at.info)


def test_charts_use_finer_samples_and_previous_next_controls(dashboard):
    import json
    at = dashboard.run()
    at.radio[0].set_value('Charts').run()
    assert not at.exception
    assert any('61 original historical chart samples' in item.value for item in at.caption)
    chart = json.loads(at.get('plotly_chart')[0].proto.spec)
    recorded = chart['data'][0]
    assert recorded['x'][0] == 0 and recorded['x'][-1] == 900
    assert 15 in recorded['x']  # Finer than the minute CSV; no per-second reconstruction.
    interval = next(box for box in at.selectbox if box.key == 'charts_interval').value
    next(button for button in at.button if button.label == 'Next →').click().run()
    assert not at.exception
    assert next(box for box in at.selectbox if box.key == 'charts_interval').value != interval
    next(button for button in at.button if button.label == '← Previous').click().run()
    assert next(box for box in at.selectbox if box.key == 'charts_interval').value == interval
    next(box for box in at.checkbox if box.label == 'Show Up/Down contract history').set_value(True).run()
    assert not at.exception
    assert len(at.get('plotly_chart')) == 2
    assert any('Contract prices at the strategy decision times' in item.value for item in at.markdown)


def test_charts_with_missing_paths_show_boundaries_without_filling_gaps(dashboard):
    import json
    at = dashboard.run()
    at.radio[0].set_value('Charts').run()
    next(box for box in at.selectbox if box.key == 'charts_date').select('2026-09-19').run()
    assert not at.exception
    assert any('No recorded price path' in item.value for item in at.warning)
    chart = json.loads(at.get('plotly_chart')[0].proto.spec)
    assert chart['data'][0]['x'] == [0, None, 900]
    assert chart['data'][0]['connectgaps'] is False


def test_research_guide_has_no_prediction_game(dashboard):
    at = dashboard.run()
    assert 'Practice game' not in at.radio[0].options
    assert any('Compare historical strategies' == button.label for button in at.button)
    assert any('None yet' == metric.value for metric in at.metric)


def test_simple_lab_runs_and_bid_changes_require_a_new_test(dashboard):
    at = dashboard.run()
    at.radio[0].set_value('Development strategies').run()
    assert len(at.slider) == 1
    assert len(at.number_input) == 1
    assert at.slider[0].label == 'Bid amount per trade ($)'
    next(button for button in at.button if button.label == 'Test strategy').click().run()
    assert not at.exception
    assert any(metric.label == 'Win rate' and metric.value == '92.44%' for metric in at.metric)
    assert any(metric.label == 'Modeled average per calendar day' for metric in at.metric)
    at.slider[0].set_value(50).run()
    assert any('Changing a setting does not silently rerun' in item.value for item in at.info)
    next(button for button in at.button if button.label == 'Test strategy').click().run()
    assert not at.exception
    assert any(metric.label == 'Avg modeled result / $50 trade' for metric in at.metric)
