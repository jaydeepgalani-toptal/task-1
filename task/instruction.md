Finance reports that the current business day’s generated account totals do not reconcile with partner end-of-day reports. The job completes successfully and writes valid JSON, but some account totals and transaction counts are wrong.

Diagnose and fix the rollup so the generated daily summary for the requested business day matches the provided partner reports consistently while preserving existing ingestion, validation, logging, routing, and error handling.

Do not hardcode report totals, edit fixtures or expected files, disable partners, bypass partner endpoints, modify tests, change runtime flags, or silence validation/logging. Keep the fix scoped to the actual cause shown by the partner payloads, registry metadata, and existing service behaviour.
