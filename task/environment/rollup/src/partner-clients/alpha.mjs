function signedAmount(raw) {
  const rawAmount = raw.amount ?? raw.amountValue;
  const amount = Number(rawAmount);
  if (raw.kind === "refund") {
    return -Math.abs(amount);
  }
  if (raw.kind === "zero") {
    return 0;
  }
  return Math.abs(amount);
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
    eventId: context.readEventId(raw),
    accountId: context.readAccountId(raw),
    amount: signedAmount(raw),
    currency: raw.currency || partner.currency,
    eventTs: context.readEventTs(raw),
    businessDate: context.resolveBusinessDate(raw)
  };
}
