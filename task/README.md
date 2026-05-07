# Daily Account Rollup Task

This task exercises runtime debugging against a mostly sealed service boundary. The evaluated agent gets a Node.js rollup project in `/workspace/rollup`, helper scripts in `/usr/local/bin/`, and a stripped `bin/partner-service` runtime that exposes partner event, metrics, report, and health endpoints locally. The intended workflow is to run the rollup for sampled business dates, compare `out/daily-rollup.json`, `out/daily-summary.json`, `out/diagnostics.json`, and `logs/rollup.log` against the partner runtime APIs, identify the aggregation defect, patch the rollup source, and submit `diagnosis/evidence.json`.

## Seeded Defect

The bug is in `src/aggregation.mjs`, specifically `referenceMark(event)`. In the broken state it deduplicates on:

```js
`${event.partnerId}:${event.reference}`
```

That is too broad for the sealed partner runtime. Some same-partner, same-reference rows are legitimate distinct settling records, while others are redundant or non-settling variants. Because the dedupe mark only uses partner plus reference, valid rows are logged as `skippedEvent` and never reach the account rollup. The fix is narrow: adjust aggregation record identity so the valid distinct rows are preserved without changing unrelated ingestion, normalization, validation, logging, report writing, or helper scripts.

## Why This Is Non-Trivial

- The partner runtime is sealed: there are no visible fixture files, expected-output JSONs, or helper inspection tools in the image.
- The rollup succeeds in the broken state. Validation passes, partner event endpoints are called, and most accounts reconcile.
- The agent is allowed to query partner EOD reports for diagnosis, but production rollup must still derive output from event endpoints only.
- The verifier independently queries partner report endpoints after production runs, so hardcoding outputs or calling reports from production source is rejected.
- The instruction also requires `diagnosis/evidence.json`, so a solution that only patches the code but does not record investigation evidence still fails.

## What The Verifier Actually Checks

- `npm ci` succeeds, the CLI help surface works, and the helper scripts start the sealed partner services cleanly.
- For several business dates, production rollup calls each enabled partner’s event endpoint and zero report endpoints before the verifier starts querying reports.
- `out/daily-rollup.json` reconciles account-by-account to the verifier’s independently merged partner EOD totals and counts within `0.01`.
- `out/daily-summary.json` and `out/diagnostics.json` carry the correct business date, per-partner counts/totals, and internally consistent accepted/skipped counts.
- `logs/rollup.log` still contains neutral `acceptedEvent` and `skippedEvent` records through the existing logger.
- Validation still rejects malformed normalized events.
- Protected runtime files stay unchanged: `/workspace/rollup/README.md`, `package.json`, `package-lock.json`, `config/partner-registry.json`, `bin/partner-service`, and the helper scripts.
- `diagnosis/evidence.json` exists and contains `sampledBusinessDates`, `sampledPartners`, `reportComparisons`, `rawEventLogComparisons`, `rejectedHypotheses`, and `productionReportEndpointCalls`.

## Expected Solution Path

1. Use `/usr/local/bin/reset-rollup-runtime`, `/usr/local/bin/start-partner-services`, and `/usr/local/bin/run-rollup --business-date ... --diagnostics`.
2. Query partner `/events`, `/reports/eod`, and `/metrics` endpoints for a few dates and compare them to rollup outputs and `logs/rollup.log`.
3. Notice that some repeated same-partner references are valid distinct records while others are not.
4. Patch `src/aggregation.mjs` so the dedupe key reflects the actual logical record identity exposed by runtime payloads.
5. Re-run sampled dates, verify reconciliation, and write `diagnosis/evidence.json` from actual runtime observations.
