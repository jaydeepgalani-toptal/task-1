Daily account rollup totals and transaction counts intermittently disagree with partner end-of-day reports. The rollup job completes successfully, validation passes, every enabled partner endpoint is called, generated JSON is well-formed, and most accounts reconcile, but some accounts are consistently off for certain business dates.

Diagnose the actual cause using the local partner runtime APIs, partner EOD reports, generated rollup outputs, diagnostics, and the rollup’s own logs. Patch the rollup so production output is derived only from partner event endpoints and reconciles with partner EOD reports across the requested business dates.

Partner EOD report endpoints may be used for investigation, but production rollup execution must not call them.

Submit diagnosis/evidence.json with a concise record of the runtime evidence used: sampled business dates, sampled partners, report comparisons, raw-event/log comparisons, rejected hypotheses, and confirmation that production rollup made zero report-endpoint calls. The artifact must include sampledBusinessDates with at least three dates, sampledPartners with at least two partners, and productionReportEndpointCalls set to 0.

Do not hardcode outputs, edit protected files or tests, change runtime flags, disable partners, bypass partner endpoints, silence validation or logging, copy EOD reports into rollup output, or change unrelated behavior.
