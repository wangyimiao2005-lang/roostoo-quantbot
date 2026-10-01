# Competition readiness — 2026-10-01

This is a repository and code review record, not authorization to trade. The General/Test API facts below come from the existing `LIVE_API_CONTRACT_2026-10-01.md` validation record; this repository-preparation task sent no live Roostoo requests.

## Passed

- [x] Trend 8/24 baseline, funding challenger and final selection rules remain frozen. `research/verify_b2e_freeze.py` passes; the B2E, funding and gate manifests and their recorded source hashes match.
- [x] Full local test suite passes (see the latest test result in the repository handoff); project imports and Python compile check pass.
- [x] Prior General/Test validation: `/v3/serverTime`, `/v3/exchangeInfo`, authenticated `/v3/balance`, and `/v6/short_positions` passed.
- [x] Prior General/Test minimum `/v6/short_open` and full-quantity `/v6/short_close` passed; the final test short-position list was empty. The recorded fees were consistent with 10 bps per side.
- [x] Production broker statically supports `SpotWallet`/`MarginWallet`, reads `SpotWallet.USD.ShortCollateral`, and reconciles it with v6 position collateral.
- [x] Production broker obtains short quantity from live `/v6/short_positions`; the runner refreshes broker positions before reductions and after writes, including on restart. Full short closure uses the observed `ShortQty`.
- [x] Amount precision and minimum-order checks, a bounded rounding allowance for post-trade reconciliation, stale/misaligned-bar halts, pending-order checks, and `HALT_NEW_RISK` behavior are present.
- [x] Roostoo API calls are guarded at 28 per rolling minute, under the stated 30-call limit. Write endpoints are not automatically retried after an uncertain response.
- [x] Repository scan found no real credential values in files selected for the initial commit; `.env.example` and documentation contain placeholders only. Runtime logs, caches and SQLite state are excluded from Git.

## Pending before Competition mode

- [ ] Organizer AWS account invitation and Sydney-region deployment using `Hackathon-Starter-Template`.
- [ ] Session Manager access, dependency installation and process restart/supervision check on AWS.
- [ ] Assigned Competition credentials injected securely; authenticated read-only check and one-cycle `DRY_RUN` completed on that account and host.
- [ ] Inspect AWS `DRY_RUN` logs, planned orders, account reconciliation and persisted state; complete final pre-live safety check.
- [ ] Confirm organizer timing if official sources remain inconsistent.
- [ ] After the sealed holdout is released, run the preregistered final strategy gate exactly once and retain its hash-locked output.
- [ ] Publish/push this local repository to an official GitHub remote when explicitly authorized.

`DRY_RUN` remains the recommended first operational mode. It performs authenticated reads and produces planned orders without sending order writes. The exact command and setup are in [README.md](../README.md) and `COMPETITION_RUNBOOK.md`.
