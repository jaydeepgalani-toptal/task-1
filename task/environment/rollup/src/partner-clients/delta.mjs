import { normalizeLedgerEvent } from "./shared-ledger.mjs";

export async function fetchEvents(partner) {
  const response = await fetch(`${partner.baseUrl}${partner.requestPath}`);
  if (!response.ok) {
    throw new Error(`partner_fetch_failed partner=${partner.id} status=${response.status}`);
  }
  return response.json();
}

export function normalizeEvent(raw, partner, context) {
  return normalizeLedgerEvent(raw, partner, context);
}
