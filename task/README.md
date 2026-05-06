# Daily Account Rollup Task

This task exercises debugging a Node.js 20 rollup service under `/workspace/rollup`. The service fetches four partner feeds over local HTTP, normalizes them into canonical events, filters events for the requested business day, aggregates per-account totals, writes `out/daily-rollup.json` atomically, emits summary/diagnostic reports, and logs every accepted event to `logs/rollup.log`.

## What The Task Is Testing

The task is no longer about a missing business-day field or a missing `partnerId` in dedupe. The intended failure lives in the compiled normalization context used by the partner clients:

- [task/environment/rollup/src/registry.mjs](/workspace/task/environment/rollup/src/registry.mjs) loads each partner’s `profile`, `sourceTsPath`, `accountPath`, and `settlement` metadata.
- [task/environment/rollup/src/payload-access.mjs](/workspace/task/environment/rollup/src/payload-access.mjs) compiles path readers plus a partner-local business-day resolver and caches that compiled context.
- [task/environment/rollup/src/partner-clients/index.mjs](/workspace/task/environment/rollup/src/partner-clients/index.mjs) retrieves the cached context and passes it into the partner adapters.
- [task/environment/rollup/src/partner-clients/shared-ledger.mjs](/workspace/task/environment/rollup/src/partner-clients/shared-ledger.mjs) is shared by both `beta` and `delta`, which is why cache scope matters.
- [task/environment/rollup/src/workset.mjs](/workspace/task/environment/rollup/src/workset.mjs) filters by the canonical `businessDate` produced during normalization, not by raw payload fields.

The visible fixture is designed so that `beta` and `delta` share the same `profile` (`ledger-wire-v2`) but do not share the same resolver inputs:

- `beta`: `sourceTsPath=record.eventTs`, `accountPath=record.accountRef`, `settlement.zone=Europe/London`, `settlement.cutoffLocal=17:00`
- `delta`: `sourceTsPath=mirror.eventTs`, `accountPath=mirror.accountRef`, `settlement.zone=America/Los_Angeles`, `settlement.cutoffLocal=14:30`

`alpha` and `gamma` use different profiles and act as controls.

## Actual Failure Mode

The planted defect is that [task/environment/rollup/src/registry.mjs](/workspace/task/environment/rollup/src/registry.mjs) emits `resolverCacheKey` from `partner.profile` only, and [task/environment/rollup/src/payload-access.mjs](/workspace/task/environment/rollup/src/payload-access.mjs) keys the compiled resolver cache on that value.

That means:

- mixed runs seeded by `beta` cause `delta` to reuse `beta`’s `record.*` readers and London cutoff
- fresh mixed runs seeded by `delta` cause `beta` to reuse `delta`’s `mirror.*` readers and Los Angeles cutoff
- partner-isolated runs pass, because only one `ledger-wire-v2` partner is enabled
- two consecutive runs in the same Node process expose stale cached resolver state even if the second run reverses partner order

The broken outputs are intentionally different by order:

- default visible order (`alpha,beta,gamma,delta`) incorrectly keeps `delta` accounts `acct-441` and `acct-466` and misses `acct-150`, `acct-430`, and one `acct-860` contribution
- fresh reversed order (`delta,beta,gamma,alpha`) incorrectly pushes `beta` onto `mirror.*`, producing `acct-940`, `acct-960`, and `acct-970`

The aggregation layer is already correct. [task/environment/rollup/src/aggregation.mjs](/workspace/task/environment/rollup/src/aggregation.mjs) dedupes on `partnerId`, `accountId`, and `eventId`, and the fixture includes legitimate cross-partner shared event ids (`shared-100`, `shared-300`, `shared-860`) so any solver that removes partner identity will fail.

## Expected Solution Path

The intended fix is to scope the compiled normalization context by the full resolver inputs, not by surface/profile alone:

1. Inspect the visible mixed-run mismatch in `out/daily-rollup.json`, `out/daily-summary.json`, and `logs/rollup.log`.
2. Notice that isolated partners reconcile but mixed runs do not, and that reversing the partner order changes which accounts are wrong.
3. Trace how `beta` and `delta` share `ledger-wire-v2` in the registry while differing on `sourceTsPath`, `accountPath`, `settlement.zone`, and `settlement.cutoffLocal`.
4. Fix the compiled resolver signature so the cache keys on the full normalization config and continue threading that compiled context through the partner client/adapter path without changing amount parsing, currency handling, validation, logging, routing, or report writing.

The oracle in [task/solution/solve.sh](/workspace/task/solution/solve.sh) applies that narrow source fix across the registry, payload access, shared ledger adapter path, and workset boundary, then runs the real service through the local mock endpoints.

## Important Pitfalls For Reviewers

- There is no visible `fixtures/expected/expected-rollup.json` anymore. The verifier derives the authoritative mixed expected rollup by merging the visible partner EOD files under [task/environment/rollup/fixtures/expected/partner-eod](/workspace/task/environment/rollup/fixtures/expected/partner-eod).
- The helper under [task/environment/rollup/tools/print-raw-payloads.mjs](/workspace/task/environment/rollup/tools/print-raw-payloads.mjs) only prints per-partner source-day and business-day ranges. It does not dump the exact failing events or name the correct field choice.
- The hidden held-out replay swaps the legitimate `sourceTsPath`/`accountPath` combinations used by `beta` and `delta`, changes the account mix, and includes one exact-cutoff exclusion per partner. A visible-fixture-only patch or a hardcoded timezone/cutoff fix will fail there.
- The verifier mutates a copied registry to change `delta`’s `settlement.cutoffLocal` and expects the mixed-run output to change accordingly. That check catches hardcoded settlement logic and stale cache-key fixes.
- The verifier also imports `runRollupJob()` twice inside one Node process. [task/environment/rollup/src/index.mjs](/workspace/task/environment/rollup/src/index.mjs) is import-safe so the tests can exercise that cache lifetime directly.
- Validation must remain active. The verifier mutates a copied `gamma` fixture to blank `payload.accountRef` and expects `validation_failed` to surface through the existing logger.
