function minorAmount(raw) {
  const minor = raw.amountMinor ?? raw.amountMinorText;
  const parsed = Number(minor);
  if (raw.entryType === "refund") {
    return -Math.abs(parsed) / 100;
  }
  if (raw.entryType === "zero") {
    return 0;
  }
  return Math.abs(parsed) / 100;
}

export function normalizeLedgerEvent(raw, partner, context) {
  return {
    partnerId: partner.id,
    eventId: context.readEventId(raw),
    accountId: context.readAccountId(raw),
    amount: minorAmount(raw),
    currency: raw.currency || partner.currency,
    eventTs: context.readEventTs(raw),
    businessDate: context.resolveBusinessDate(raw)
  };
}
