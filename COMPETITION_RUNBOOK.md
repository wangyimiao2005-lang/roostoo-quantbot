# Competition Runbook

## 1. Environment

Never commit secrets.  Set them only on the AWS instance:

```bash
export ROOSTOO_BASE_URL=https://mock-api.roostoo.com
export ROOSTOO_API_KEY='your_competition_key_here'
export ROOSTOO_SECRET_KEY='your_competition_secret_here'
```

## 2. Install + test

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

## 3. Authenticated dry run first

```bash
PYTHONPATH=src:research .venv/bin/python research/run_roostoo_readonly.py
PYTHONPATH=src:research .venv/bin/python research/run_competition_bot.py --mode DRY_RUN --once
```

Do not proceed if the read-only check cannot query the account's short-position
capability, because the frozen strategy is long/short.

## 4. Start autonomous competition mode

Only after the above checks are clean:

```bash
export ROOSTOO_COMPETITION_ACK=YES
PYTHONPATH=src:research .venv/bin/python research/run_competition_bot.py --mode COMPETITION
```

The launcher stays idle outside the strategy's 01:02–01:54 UTC execution window,
uses Roostoo server time before decisions, automatically runs the pre-registered final
gate at/after Oct 4 if needed, and relies on durable SQLite state to prevent duplicate
completed rebalances.

## 5. Logs

- `logs/competition_runtime.jsonl`: strategy/run result, targets, order responses.
- `logs/roostoo_api.jsonl`: method/path/success/failure only; no keys, signatures or params.
- `data/competition/dry_run_state.sqlite`: DRY_RUN state.
- `data/competition/runtime_state.sqlite`: COMPETITION-only durable rebalance state.
- `data/binance_competition_live/`: persisted live OHLCV tail.

Do not manually place competition trades.  Strategy/code changes during the live period
must be committed with a clear Git history before redeployment.

## Short capability verification (GENERAL/TEST account only)

The General/Test contract was live-verified on 2026-10-01.  Default verification is read-only:

```bash
python research/verify_roostoo_short_capability.py
```

Expected healthy path: signed `/v3/balance` returns `SpotWallet`/`MarginWallet`, and signed `GET /v6/short_positions` returns `Success=true`.  The verifier never prints credentials.

A guarded minimum v6 open/close re-test is available only for the General/Test account:

```bash
python research/verify_roostoo_short_capability.py \
  --execute-v6-min-test \
  --yes-general-test
```

This path does **not** call `/v3/place_order`. It opens one minimum `BTC/USD` short via `/v6/short_open`, reads the server-returned `ShortQty`, closes that exact quantity via `/v6/short_close`, and verifies the final short-position list is empty. Never run this write probe with competition credentials.

## Verified live short semantics

- Open input: `pair`, `collateral`.
- Open response: authoritative `ShortQty`, `Collateral`, `EntryPrice`, `OpenFee`.
- Close input: `pair`, `close_qty`.
- Full-close response includes `ClosedQty`, `CloseFee`, `RealizedPNL`, `FullyClosed`.
- Position reconciliation source: `/v6/short_positions`.
- Balance schema: `/v3/balance` uses `SpotWallet` and `MarginWallet`; `SpotWallet.USD.ShortCollateral` is cross-checked against the v6 position collateral sum.
- The verified test charged approximately 10 bps on both open and close, consistent with MARKET/taker execution.

Do not infer that requested collateral exactly equals realized exposure: amount precision can quantize `ShortQty`. Production reconciliation therefore uses the server-returned quantity rather than a theoretical collateral/price conversion.
