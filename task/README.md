# Daily Account Rollup Task

This task contains a local Node.js rollup service under `/workspace/rollup`. The service reads partner configuration, calls enabled partner event endpoints, validates and normalizes returned records, selects records for a requested business day, aggregates account totals, writes JSON reports, and logs accepted and skipped records.

Use the local partner runtime through the provided scripts:

```bash
/usr/local/bin/reset-rollup-runtime
/usr/local/bin/start-partner-services
/usr/local/bin/run-rollup --business-date 2026-05-06 --diagnostics
```

Partner end-of-day reports are available from each configured partner's report endpoint for investigation. The production rollup must not call those report endpoints while generating output.

The useful artifacts during investigation are:

- `/workspace/rollup/out/daily-rollup.json`
- `/workspace/rollup/out/daily-summary.json`
- `/workspace/rollup/out/diagnostics.json`
- `/workspace/rollup/logs/rollup.log`
- the configured partner event endpoints
- the configured partner end-of-day report endpoints

Keep the fix in production source code under `/workspace/rollup/src`. Do not edit protected files, scripts, runtime binaries, configuration, tests, package metadata, or generated reports.
