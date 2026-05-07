function round2(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function buildDedupKey(event) {
  return `${event.partnerId}:${event.eventId}`;
}

export function applyEvents(events, logger) {
  const seenKeys = new Set();
  const accountRollup = new Map();
  const partnerSummary = new Map();
  const diagnostics = {
    acceptedEvents: 0,
    duplicateEvents: 0,
    perPartnerAccepted: {},
    perPartnerDuplicates: {}
  };

  for (const event of events) {
    const dedupKey = buildDedupKey(event);
    if (seenKeys.has(dedupKey)) {
      diagnostics.duplicateEvents += 1;
      diagnostics.perPartnerDuplicates[event.partnerId] = (diagnostics.perPartnerDuplicates[event.partnerId] || 0) + 1;
      logger.info({
        stage: "aggregation",
        action: "duplicate_skipped",
        partner: event.partnerId,
        account: event.accountId,
        eventId: event.eventId,
        postingSequence: event.postingSequence || ""
      });
      continue;
    }

    seenKeys.add(dedupKey);
    logger.ingestion(event);
    diagnostics.acceptedEvents += 1;
    diagnostics.perPartnerAccepted[event.partnerId] = (diagnostics.perPartnerAccepted[event.partnerId] || 0) + 1;

    const accountEntry = accountRollup.get(event.accountId) || {
      total: 0,
      transactionCount: 0,
      currency: event.currency
    };
    accountEntry.total = round2(accountEntry.total + event.amount);
    accountEntry.transactionCount += 1;
    accountRollup.set(event.accountId, accountEntry);

    const partnerEntry = partnerSummary.get(event.partnerId) || {
      total: 0,
      transactionCount: 0
    };
    partnerEntry.total = round2(partnerEntry.total + event.amount);
    partnerEntry.transactionCount += 1;
    partnerSummary.set(event.partnerId, partnerEntry);
  }

  return {
    rollup: Object.fromEntries(
      [...accountRollup.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([accountId, value]) => [
          accountId,
          {
            total: round2(value.total),
            transactionCount: value.transactionCount,
            currency: value.currency
          }
        ])
    ),
    partnerSummary: Object.fromEntries(
      [...partnerSummary.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([partnerId, value]) => [
          partnerId,
          {
            total: round2(value.total),
            transactionCount: value.transactionCount
          }
        ])
    ),
    diagnostics
  };
}
