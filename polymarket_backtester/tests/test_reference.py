from pm_btc.reference import fetch_reference


class ReferenceFixture:
    """Artificial reference response for validation tests only."""
    def get(self, url, params):
        assert params["twapEnabled"] == "true" and params["twapLookbackSeconds"] == 60
        # Actual values in this test are arbitrary fixtures, never research data.
        return [{"timestamp": (1000 + i * 60) * 1000, "value": 100 + i}
                for i in range(15)], {"sha256": "artificial-fixture"}


def test_missing_final_chart_point_uses_actual_reported_boundary_only():
    market = {"slug": "fixture", "start_ts": 1000, "opening_price": 100, "settlement_price": 115,
              "reference_method": "chainlink_btc_usd_twap_60s", "source_sha256": "metadata-fixture"}
    rows, eligible = fetch_reference(ReferenceFixture(), market)
    assert eligible
    assert rows[15]["price"] == 115
    assert rows[15]["status"] == "reported_event_metadata_boundary"
    assert rows[15]["source_sha256"] == "metadata-fixture"
