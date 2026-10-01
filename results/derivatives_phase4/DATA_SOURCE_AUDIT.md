# Phase 4 Data Source Audit

Repository inspection found no derivatives cache, exchange-futures client, CoinGlass configuration, or non-Roostoo credentials. Existing Roostoo credentials are not read or printed.

| Provider | Dataset | Coverage / suitability | Auth | Notes |
|---|---|---|---|---|
| Binance Futures | `/fapi/v1/fundingRate` | Public, paginated, 8-hour settlement records; tested through 2026-09-20 only | No | Reproducible; timestamps are settlement/publication times. |
| Binance Futures | Open-interest statistics | Insufficient: endpoint documents recent/one-month history | No | Not suitable for 2025–2026 research. |
| Binance Futures | Liquidations | No official historical aggregate endpoint with required depth | No | Unavailable. |
| Bybit / OKX | Not downloaded | No configured client or verified reproducible archive | Varies | Not used. |
| CoinGlass | Not downloaded | No credential/configuration found | Paid/API key | Unavailable. |

All external requests are in `EXTERNAL_REQUEST_LOG.csv`; each is capped before 2026-09-21 UTC. Symbol mapping uses USDⓈ-M perpetual symbols identical to the B1 `USDT` tickers. Funding is sparse (normally 8-hourly) and causally forward-filled only **after** settlement; it is never backward-filled.
