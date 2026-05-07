Daily rollup totals and transaction counts intermittently disagree with partner end-of-day reports, even though ingestion completes, validation passes, every enabled partner endpoint is called, generated JSON is well-formed, and most accounts reconcile. Diagnose and fix the actual cause using the local runtime partner APIs and the rollup's own logs while preserving ingestion, validation, logging, routing, business-day filtering, report writing, and error handling.

Partner end-of-day reports may be used for investigation. Production rollup execution must derive its output from partner event endpoints only.

Do not hardcode outputs, edit protected files, modify tests, change runtime flags, disable or bypass partners, bypass partner endpoints, silence validation or logging, copy partner reports into rollup output, or change unrelated behavior.
