# Daily Account Rollup

This workspace contains a local account rollup service. Start the local partner services, run the rollup for a business date, then inspect generated reports and logs under `out/` and `logs/`.

```bash
/usr/local/bin/start-partner-services
/usr/local/bin/run-rollup --business-date 2026-05-06 --diagnostics
```

Partner report endpoints may be queried during investigation. The production rollup should generate its output from partner event endpoints.

Submit `/workspace/rollup/diagnosis/evidence.json` with the runtime evidence used. It must include `sampledBusinessDates` with at least three dates, `sampledPartners` with at least two partners, non-empty `reportComparisons`, non-empty `rawEventLogComparisons`, at least two `rejectedHypotheses`, and `productionReportEndpointCalls` set to `0`.
