"""Artificial API fixtures test data handling only. They are never used as research data."""
import json
from datetime import date

import httpx
import pytest

from pm_btc.collector import collect, verify_artifacts
from pm_btc.normalize import contract_target, historical_observations, normalize_market
from pm_btc.transport import PublicHTTP, SourceError
from pm_btc.window import Window, iso


def event(start):
    slug = f"btc-updown-15m-{start}"
    return {"slug": slug, "eventMetadata": {"priceToBeat": 100, "finalPrice": 100}, "markets": [{
        "slug": slug, "id": "test-market", "question": "Bitcoin Up or Down - fixture only",
        "endDate": iso(start + 900), "outcomes": '["Down", "Up"]', "clobTokenIds": '["22", "11"]',
        "conditionId": "fixture-condition", "closed": True, "umaResolutionStatus": "resolved",
        "outcomePrices": '["0", "1"]',
        "description": "Up if greater than or equal to the opening value. Chainlink BTC/USD stream.",
        "resolutionSource": "https://data.chain.link/streams/btc-usd",
    }]}


def test_window_has_2880_slots_and_20_10_split():
    w = Window(date(2025, 10, 19))
    assert len(w.slots) == 2880
    assert w.start_date == date(2025, 9, 19)
    assert sum(w.split(s) == "development" for s in w.slots) == 1920
    assert sum(w.split(s) == "validation" for s in w.slots) == 960
    assert iso(w.start_ts).endswith("08:00:00+00:00")
    assert w.slots[-1] + 900 == w.end_ts


def test_outcomes_map_to_tokens_in_source_order_and_ties_go_up():
    e = event(1700000100)
    row = normalize_market(e, 1700000100, "development")
    assert row["up_token_id"] == "11" and row["down_token_id"] == "22"
    assert row["winning_outcome"] == "Up" and row["settlement_check"] == "consistent"


def test_closed_or_high_probability_is_not_proof_of_resolution():
    e = event(1700000100)
    e["markets"][0]["umaResolutionStatus"] = "disputed"
    assert normalize_market(e, 1700000100, "development")["winning_outcome"] == ""
    e["markets"][0]["umaResolutionStatus"] = "resolved"
    e["markets"][0]["outcomePrices"] = '["0.001", "0.999"]'
    assert normalize_market(e, 1700000100, "development")["winning_outcome"] == ""


def test_unverified_reference_is_not_used_and_mismatch_is_reported():
    e = event(1700000100)
    e["eventMetadata"]["finalPrice"] = 99
    assert normalize_market(e, 1700000100, "development")["settlement_check"] == "MISMATCH"
    e["markets"][0]["description"] = "Binance prices, strictly greater."
    row = normalize_market(e, 1700000100, "development")
    assert row["rules_status"] == "manual_review_required"
    assert row["opening_price"] is None


@pytest.mark.parametrize("field,value", [("endDate", iso(1700000100 + 901)), ("outcomes", '["Yes", "No"]'), ("clobTokenIds", '["11", "11"]')])
def test_reject_wrong_interval_or_outcomes(field, value):
    e = event(1700000100)
    e["markets"][0][field] = value
    with pytest.raises(ValueError):
        normalize_market(e, 1700000100, "development")


def test_contract_sampling_never_looks_ahead_or_interpolates():
    m = {"start_ts": 1000, "slug": "test", "up_token_id": "1"}
    observations = historical_observations({"history": [{"t": 1599, "p": 0.6}, {"t": 1601, "p": 0.9}]}, "1", 1000, 1900, "hash")
    target = contract_target(observations, m, "Up", 10)
    assert target["exact_history_price"] is None
    assert target["last_observation_price"] == 0.6
    assert target["last_observation_age_seconds"] == 1
    assert target["historical_ask"] is None


@pytest.mark.parametrize("price", [1.1, -0.1, "NaN", "Infinity", True])
def test_bad_history_prices_are_rejected(price):
    with pytest.raises(ValueError):
        historical_observations({"history": [{"t": 1000, "p": price}]}, "1", 1000, 1900, "hash")


def test_conflicting_history_not_silently_overwritten():
    with pytest.raises(ValueError):
        historical_observations({"history": [{"t": 1000, "p": 0.5}, {"t": 1000, "p": 0.6}]}, "1", 1000, 1900, "hash")


def test_proxy_denial_is_a_visible_incomplete_run(tmp_path):
    def deny(request):
        raise httpx.ProxyError("403 Forbidden", request=request)
    http = PublicHTTP(tmp_path / "http", client=httpx.Client(transport=httpx.MockTransport(deny)), interval=0)
    result = collect(Window(date(2025, 10, 19)), tmp_path, http=http, progress=lambda _: None)
    assert result["status"] == "network_blocked"
    assert result["expected_intervals"] == 2880 and result["actual_markets_downloaded"] == 0
    assert not result["analysis_ready"] and not result["execution_backtest_ready"]
    assert verify_artifacts(result["dataset_directory"]) == []
    assert result["reference_samples_available"] == result["contract_history_observations"] == 0


def test_actual_response_cache_integrity_is_checked(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"history": []})))
    http = PublicHTTP(tmp_path, client=client, interval=0)
    _, receipt = http.get("https://example.com/history")
    (tmp_path / "raw" / receipt["body_file"]).write_text("tampered")
    with pytest.raises(SourceError, match="integrity"):
        http.get("https://example.com/history")


def test_successful_metadata_and_real_observation_handling_without_claiming_execution(tmp_path):
    w = Window(date(2025, 10, 19), days=30)
    start = w.start_ts
    def handle(request):
        if request.url.path == "/events":
            return httpx.Response(200, json=[event(start)])
        if request.url.path == "/prices-history":
            return httpx.Response(200, json={"history": [{"t": start + 600, "p": 0.7}]})
        if request.url.path == "/trades":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json="OK")
    http = PublicHTTP(tmp_path / w.key, client=httpx.Client(transport=httpx.MockTransport(handle)), interval=0)
    result = collect(w, tmp_path, max_markets=1, http=http, progress=lambda _: None)
    assert result["actual_markets_downloaded"] == 1 and result["requested_intervals"] == 1
    assert result["expected_intervals"] == 2880
    assert result["historical_contract_endpoint_verified"] is True
    assert result["contract_history_observations"] == 2
    assert result["exact_entry_history_observations"] == 2
    assert result["reference_samples_available"] == 2
    assert result["execution_backtest_ready"] is False
    assert verify_artifacts(result["dataset_directory"]) == []


def test_dataset_tamper_is_reported(tmp_path):
    def deny(request):
        raise httpx.ProxyError("403 Forbidden", request=request)
    http = PublicHTTP(tmp_path / "raw", client=httpx.Client(transport=httpx.MockTransport(deny)), interval=0)
    result = collect(Window(date(2025, 10, 19), days=1), tmp_path, http=http, progress=lambda _: None)
    path = tmp_path / Window(date(2025, 10, 19), days=1).key / "markets.csv"
    path.write_text("tampered")
    assert verify_artifacts(result["dataset_directory"]) == ["CSV integrity failure: markets.csv"]
