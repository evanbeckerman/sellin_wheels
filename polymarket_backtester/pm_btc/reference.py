"""Historical reference data from the same public route used by Polymarket's chart.

The TWAP parameters were verified against the site's published JavaScript.
No Binance substitution, interpolation, forward fill, or synthetic minute bars.
"""
from .normalize import finite_number
from .window import iso

POLY = "https://polymarket.com"


def fetch_reference(http, market):
    method = market.get("reference_method")
    if method not in {"chainlink_btc_usd_twap_60s", "chainlink_btc_usd_spot"}:
        raise ValueError("Reference method has not been verified from market rules")
    params = {"symbol": "BTC", "eventStartTime": iso(market["start_ts"]),
              "variant": "fifteen", "endDate": iso(market["start_ts"] + 900)}
    if method == "chainlink_btc_usd_twap_60s":
        params.update(twapEnabled="true", twapLookbackSeconds=60)
    payload, receipt = http.get(POLY + "/api/crypto/price-history", params)
    if not isinstance(payload, list):
        raise ValueError("Reference history must be an array")
    samples = {}
    for point in payload:
        ms = finite_number(point.get("timestamp"))
        value = finite_number(point.get("value"), low=0)
        if ms is None or ms != int(ms) or value is None or value <= 0:
            raise ValueError("Malformed reference observation")
        if ms in samples and samples[ms] != value:
            raise ValueError("Conflicting reference observations")
        samples[int(ms)] = value
    # Verify endpoints against official event metadata wherever both exist.
    checks = []
    for minute, key in ((0, "opening_price"), (15, "settlement_price")):
        reference = samples.get((market["start_ts"] + minute * 60) * 1000)
        reported = market.get(key)
        if reference is not None and reported is not None:
            # Sub-cent tolerance for serialization, not a synthetic price adjustment.
            if abs(reference - reported) > 0.005:
                raise ValueError(f"Reference {key} differs from resolved event metadata")
            checks.append(key)
    rows = []
    for minute in range(16):
        timestamp = market["start_ts"] + minute * 60
        value = samples.get(timestamp * 1000)
        status = "exact_official_chart_observation" if value is not None else "missing_verified_reference_observation"
        source_hash = receipt["sha256"] if value is not None else ""
        # These are actual reported boundary values, never estimated interior prices.
        if value is None and minute in (0, 15):
            value = market.get("opening_price" if minute == 0 else "settlement_price")
            if value is not None:
                status = "reported_event_metadata_boundary"
                source_hash = market.get("source_sha256", "")
        rows.append({"slug": market["slug"], "minute": minute, "target_ts": timestamp,
                     "target_utc": iso(timestamp), "price": value, "reference_type": method,
                     "status": status, "source_sha256": source_hash})
    # The 1–10 minute trend needs those exact observations plus the reported boundaries.
    # Later entry times have their own additional completeness requirements.
    verified = bool(checks) and all(rows[i]["price"] is not None for i in [*range(11), 15])
    return rows, verified
