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
        assert at.radio[0].value == 'Trend analysis'
        assert any('75.68%' in item.value for item in at.info)
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
