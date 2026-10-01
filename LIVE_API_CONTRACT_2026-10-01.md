# Roostoo Live API Contract Verification — 2026-10-01

Scope: **General/Test account only**. No Competition credential was used for the write probe.

## Read-only authentication

- `GET /v3/serverTime`: HTTP 200.
- `GET /v3/balance` signed with HMAC-SHA256: HTTP 200, `Success=true`.
- Live balance schema returned `SpotWallet` and `MarginWallet`.
- USD balance included `Free`, `Lock`, `PendingOrders`, and `ShortCollateral`.
- `GET /v6/short_positions`: HTTP 200, `Success=true`.

## Minimum v6 execution probe

Pair: `BTC/USD`.

1. `POST /v6/short_open` with `pair=BTC/USD` and minimum test `collateral` succeeded.
2. The response returned a server-authoritative `ShortQty`, `Collateral`, `EntryPrice`, and `OpenFee`.
3. `GET /v6/short_positions` showed the open short.
4. `POST /v6/short_close` used the **entire returned `ShortQty`** as `close_qty` and succeeded with `FullyClosed=true`.
5. Final `GET /v6/short_positions` returned an empty list.

Observed fee behavior on the probe was approximately **10 bps on open and 10 bps on close**, consistent with MARKET/taker execution.

## Production implications

- Do not implement shorting as a naked `/v3/place_order` SELL.
- Open short through `/v6/short_open(pair, collateral)`.
- Treat the returned `ShortQty` as authoritative; requested collateral can quantize to a different realized exposure because of `AmountPrecision`.
- Reconcile live shorts from `/v6/short_positions` before planning any remaining delta.
- Close through `/v6/short_close(pair, close_qty)` using quantity derived from live broker state.
- Parse `/v3/balance` from `SpotWallet` (legacy `Wallet` remains a compatibility fallback only).
- Reconstruct equity with short collateral exactly once and halt if `SpotWallet.USD.ShortCollateral` materially disagrees with the sum of v6 position collateral.

## Credential hygiene

The General/Test API key appeared in a copied terminal transcript during verification. Rotate/regenerate that **test** key before any further test-account use. No credential is stored in this repository.
