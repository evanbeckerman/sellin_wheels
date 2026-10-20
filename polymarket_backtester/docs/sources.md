# Source verification and limitations

All production requests in this application are public GETs. No API key is needed for the sources successfully used here. A signing key does not remedy blocked network access and is never read by this application.

## Polymarket market metadata

`GET https://gamma-api.polymarket.com/events?slug=btc-updown-15m-<unix_start>` and repeated slug filters return actual events, markets, descriptions, resolution-source URLs, ordered outcome/token pairs, resolved outcome prices, fee schedules, and reported `eventMetadata.priceToBeat` / `finalPrice` when available.

Creation/startDate is not used as the trading interval start. Slug time, `eventStartTime` when present, and `endDate` are checked. Closed state alone and near-1 probabilities do not establish resolution. Winning outcomes require resolved status and exact binary outcome prices.

## Historical contract observations

`GET https://clob.polymarket.com/prices-history?market=<token>&startTs=<start>&endTs=<end>&fidelity=1`

Official specification: https://docs.polymarket.com/api-spec/clob-openapi.yaml, `/prices-history`. It describes historical prices and minute fidelity, not historical bid/ask snapshots. Actual returned observation times often do not fall exactly on entry-minute boundaries. The collector saves all observations and reports exact-minute values only when an exact timestamp exists; separate prior observations retain their age and timestamp.

The same specification's `/book` endpoint returns an order book with a current timestamp, without a historical-time request parameter. A book fetched now cannot reconstruct the book at a past minute. No live books are substituted for historical execution evidence.

Alternative actual prints: `GET https://data-api.polymarket.com/trades?market=<condition_id>&limit=500&offset=<offset>`. Condition IDs and token IDs are validated, duplicated prints are removed, and capped/failed pagination is explicitly incomplete. Print size is executed volume, not available entry liquidity.

## Bitcoin reference path

The actual downloaded descriptions specify `https://data.chain.link/streams/btc-usd-twap-60s-streams`, with Up on an ending reference value greater than or equal to the opening value. Their `cryptoMarketConfig` identifies `btc-15m-twap-60`, enabled TWAP and a 60-second lookback. The collector must not substitute Chainlink spot, Binance or Coinbase.

The public market page loads `/_next/static/immutable/chunks/0kudcjn9upp-6.js`. Its historical chart request uses:

```
GET https://polymarket.com/api/crypto/price-history
    ?symbol=BTC
    &eventStartTime=<ISO UTC interval start>
    &variant=fifteen
    &endDate=<ISO UTC interval end>
    &twapEnabled=true
    &twapLookbackSeconds=60
```

This is a site endpoint verified from published frontend code, not a documented stable historical-data service. Observed responses contain `{timestamp: <milliseconds>, value: <price>}` points, often 15 seconds apart. Only exact-minute points are used. Requests and response hashes are retained in the dataset.

A checked real example at 2026-10-18 08:00–08:15 UTC returned opening **81578.47483492653** and closing **81576.1658737267**, matching both the resolved event's metadata and `/api/crypto/crypto-price` with the same TWAP flags. Without TWAP flags, that latter route returned different values, confirming why a generic BTC spot feed is unsuitable.

The `crypto-price` route rejected an older requested interval with `Timestamp too old for Chainlink API (max 30 days)`; `price-history` returned an empty array there. Other historical paths were partial. These are retained as genuine data gaps rather than estimated.

Official streaming client, inspected as supplementary source research:
https://github.com/Polymarket/real-time-data-client/blob/418cce9a05bdd7b74b1cef7af18727cfff5b4b8b/README.md
documents distinct spot/Chainlink channels and an initial connection data dump. It does not establish availability of a complete 30-day historical TWAP archive. Current docs also describe migration to PolyBolt; a live subscription cannot recover missing past snapshots.

## Fees

https://docs.polymarket.com/trading/fees.md and https://docs.polymarket.com/market-data/market-details.md describe market-specific schedules. The downloaded resolved markets include a `crypto_fees_v2` schedule with rate 0.07, exponent 1 and taker-only fees. Scenario calculations use the individual record, not a hard-coded assumption that every past market has today's fee. Unknown fee configurations are excluded. The fetched archived configuration is not independently versioned evidence that a fee never changed, so that limitation is disclosed.

## Alternative historical sources investigated

The public PyPI package `dome-api-sdk` 1.0.0 documents a Dome API `/crypto-prices/chainlink` endpoint with millisecond time filters and an API-key requirement. Its documented currency-pair history does not by itself establish that it archives this exact **60-second TWAP** stream. It is not connected, no credentials have been sent, and it is not used to fill gaps. A suitable licensed archive must identify the exact stream and original timestamps and pass endpoint/outcome checks before use. A Polymarket API key is not a Dome credential.

On-chain exchange fills or third-party trade archives could supplement executed contract prints; they do not reconstruct unfilled bids, asks or order-book depth. Missing historical liquidity needs an actual historical order-book archive, not fabricated spreads or inferred size.
