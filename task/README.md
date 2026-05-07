# Daily Account Rollup Task

This task exercises debugging a Node.js 20 rollup service under `/workspace/rollup`. The service fetches five partner feeds over local HTTP, normalizes them into canonical events, filters events for the requested business day, deduplicates accepted events, aggregates per-account totals, writes `out/daily-rollup.json` atomically, emits summary/diagnostic reports, and logs every accepted event to `logs/rollup.log`.

## What The Task Is Testing

The intended failure is not amount parsing, timezone filtering, endpoint routing, validation, or report writing. Those surfaces are present as plausible distractions, but the planted bug is in the meaning of a duplicate event.

The important files are:

- [task/environment/rollup/config/partner-registry.json](/workspace/task/environment/rollup/config/partner-registry.json), which carries each partner's `eventIdentity` metadata.
- [task/environment/rollup/src/aggregation.mjs](/workspace/task/environment/rollup/src/aggregation.mjs), which currently deduplicates all accepted events with a shallow `partnerId:eventId` key.
- [task/environment/rollup/src/payload-access.mjs](/workspace/task/environment/rollup/src/payload-access.mjs), which correctly compiles registry-driven readers, including optional `postingSequencePath`.
- [task/environment/rollup/src/partner-clients/epsilon.mjs](/workspace/task/environment/rollup/src/partner-clients/epsilon.mjs), which normalizes the ledger-posting partner.

Four partners use normal stable event identity:

- `alpha`: direct card feed, `America/New_York`, cutoff `18:00`
- `beta`: ledger-wire feed, `Europe/London`, cutoff `17:00`
- `gamma`: nested settle-pack feed, `Asia/Tokyo`, cutoff `16:00`
- `delta`: second ledger-wire feed, `America/Los_Angeles`, cutoff `14:30`

The fifth partner, `epsilon`, uses `eventIdentity: "ledger-posting"` with `postingSequencePath: "posting.sequence"`. For this partner, `ledger.id` is a stable ledger identity, not a unique posting identity. Multiple postings can legitimately share the same `ledger.id`:

- original sale
- same-day correction
- next-day or same-day reversal
- amended repost
- exact duplicate replay of one posting sequence

## Actual Failure Mode

The planted defect is in [task/environment/rollup/src/aggregation.mjs](/workspace/task/environment/rollup/src/aggregation.mjs):

```js
function buildDedupKey(event) {
  return `${event.partnerId}:${event.eventId}`;
}
```

That key is correct for stable-event partners, but too shallow for `epsilon`. It silently drops valid correction, reversal, and amended-repost postings that share the same `ledger.id` but have different `posting.sequence`. The job still succeeds, validation passes, endpoints are reached, JSON is well-formed, and most accounts reconcile. Only accounts touched by ledger-posting correction patterns are wrong.

The visible fixture also includes real duplicates for normal partners and for `epsilon`. A global "count every same-eventId row" fix is wrong; exact duplicates must still be skipped. A global "always include posting sequence when present" fix is also wrong; the verifier mutates stable-event partner metadata to ensure sequence-like fields do not change stable-event dedupe semantics.

## Expected Solution Path

The intended fix is small but semantic:

1. Compare generated outputs and accepted-event logs against the partner EOD reports.
2. Notice that `epsilon` has structurally valid events with repeated `ledger.id`, and that some repeats are corrections/reversals while one repeat is an exact duplicate posting sequence.
3. Read `eventIdentity` and `postingSequencePath` in the registry.
4. Change aggregation dedupe to use `partnerId:eventId:postingSequence` only for events whose normalized `eventIdentity` is `ledger-posting`.
5. Preserve `partnerId:eventId` dedupe for all stable-event partners.

The oracle in [task/solution/solve.sh](/workspace/task/solution/solve.sh) applies that narrow aggregation fix and runs the real local mock endpoints.

## Important Pitfalls For Reviewers

- There is no visible cross-partner `expected-rollup.json`; the verifier derives the authoritative mixed rollup by merging partner EOD reports.
- The aggregation layer must still skip real duplicates. The visible run has one duplicate per partner.
- The `epsilon` duplicate is same `ledger.id` and same `posting.sequence`; its correction/reversal/amended reposts use the same `ledger.id` but different sequences and must count.
- Hidden replay changes the `epsilon` ledger-posting pattern and includes an exact-cutoff exclusion.
- Hidden metadata mutation confirms `eventIdentity` drives dedupe semantics.
- Hidden stable-event mutation confirms sequence-like metadata must not globally alter normal partner dedupe.
- Validation and logging must remain active.
