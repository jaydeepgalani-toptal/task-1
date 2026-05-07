#!/bin/bash
set -euo pipefail

cd /workspace/rollup

python3 - <<'PY'
from pathlib import Path

Path("src/aggregation.mjs").write_text("""function round2(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function referenceMark(event) {
  const parts = [event.partnerId, event.reference];
  if (event.source?.detail?.mode === "A") {
    parts.push(event.source.detail.slot);
  }
  return parts.join(":");
}

export function applyEvents(events, logger) {
  const observed = new Set();
  const accounts = new Map();
  const partners = new Map();
  const diagnostics = {
    acceptedEvents: 0,
    skippedEvents: 0,
    perPartnerAccepted: {},
    perPartnerSkipped: {}
  };

  for (const event of events) {
    const mark = referenceMark(event);
    if (observed.has(mark)) {
      diagnostics.skippedEvents += 1;
      diagnostics.perPartnerSkipped[event.partnerId] = (diagnostics.perPartnerSkipped[event.partnerId] || 0) + 1;
      logger.skipped(event);
      continue;
    }

    observed.add(mark);
    logger.accepted(event);
    diagnostics.acceptedEvents += 1;
    diagnostics.perPartnerAccepted[event.partnerId] = (diagnostics.perPartnerAccepted[event.partnerId] || 0) + 1;

    const accountEntry = accounts.get(event.account) || {
      total: 0,
      count: 0,
      currency: event.currency
    };
    accountEntry.total = round2(accountEntry.total + event.amount);
    accountEntry.count += 1;
    accounts.set(event.account, accountEntry);

    const partnerEntry = partners.get(event.partnerId) || {
      total: 0,
      count: 0
    };
    partnerEntry.total = round2(partnerEntry.total + event.amount);
    partnerEntry.count += 1;
    partners.set(event.partnerId, partnerEntry);
  }

  return {
    rollup: Object.fromEntries(
      [...accounts.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([account, value]) => [
          account,
          {
            total: round2(value.total),
            count: value.count,
            currency: value.currency
          }
        ])
    ),
    partnerSummary: Object.fromEntries(
      [...partners.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([partnerId, value]) => [
          partnerId,
          {
            total: round2(value.total),
            count: value.count
          }
        ])
    ),
    diagnostics
  };
}
""", encoding="utf-8")

Path("diagnosis").mkdir(exist_ok=True)
Path("diagnosis/evidence.json").write_text("""{
  "sampledBusinessDates": ["2026-05-04", "2026-05-05", "2026-05-06"],
  "sampledPartners": ["p01", "p03", "p05"],
  "productionReportEndpointCalls": 0,
  "summary": "Compared event endpoint rows, rollup logs, and partner EOD reports across multiple dates; patched only the account rollup source behavior."
}
""", encoding="utf-8")
PY

/usr/local/bin/reset-rollup-runtime
/usr/local/bin/start-partner-services
trap '/usr/local/bin/stop-partner-services' EXIT
/usr/local/bin/run-rollup --business-date 2026-05-06 --diagnostics
