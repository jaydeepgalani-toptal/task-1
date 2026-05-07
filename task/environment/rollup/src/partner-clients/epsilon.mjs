function postingAmount(raw) {
  const amount = Number(raw.posting.amountText);
  if (raw.posting.type === "refund" || raw.posting.type === "reversal") {
    return -Math.abs(amount);
  }
  if (raw.posting.type === "zero") {
    return 0;
  }
  return amount;
}

export async function fetchEvents(partner) {
  const response = await fetch(`${partner.baseUrl}${partner.requestPath}`);
  if (!response.ok) {
    throw new Error(`partner_fetch_failed partner=${partner.id} status=${response.status}`);
  }
  return response.json();
}

export function normalizeEvent(raw, partner, context) {
  return {
    partnerId: partner.id,
    eventIdentity: partner.eventIdentity,
    eventId: context.readEventId(raw),
    postingSequence: context.readPostingSequence(raw),
    accountId: context.readAccountId(raw),
    amount: postingAmount(raw),
    currency: raw.currency || partner.currency,
    eventTs: context.readEventTs(raw),
    businessDate: context.resolveBusinessDate(raw)
  };
}
