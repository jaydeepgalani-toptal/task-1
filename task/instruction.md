Finance reports that daily account rollup totals are intermittently wrong for some business days. The job completes successfully, validation passes, every partner endpoint is called, generated JSON is well-formed, and most accounts reconcile, but some totals and transaction counts disagree with partner end-of-day reports.

Diagnose and fix the rollup so the generated daily summary for the requested business day matches the provided partner reports consistently while preserving existing ingestion, validation, logging, routing, business-day filtering, duplicate handling, and error handling.

Do not hardcode report totals, edit fixtures or expected files, disable partners, bypass partner endpoints, modify tests, change runtime flags, silence validation/logging, or count all repeated event identifiers blindly. Keep the fix scoped to the actual cause shown by the partner payloads, registry metadata, accepted-event logs, and existing service behaviour.
