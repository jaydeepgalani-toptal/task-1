function hasText(value) {
  return typeof value === "string" && value.trim().length > 0;
}

export function validateNormalizedEvent(event) {
  if (!hasText(event.partnerId)) {
    throw new Error("validation_failed partnerId");
  }
  if (!hasText(event.eventId)) {
    throw new Error(`validation_failed eventId partner=${event.partnerId}`);
  }
  if (event.eventIdentity === "ledger-posting" && !hasText(event.postingSequence)) {
    throw new Error(`validation_failed postingSequence partner=${event.partnerId} eventId=${event.eventId}`);
  }
  if (!hasText(event.accountId)) {
    throw new Error(`validation_failed accountId partner=${event.partnerId} eventId=${event.eventId}`);
  }
  if (typeof event.amount !== "number" || Number.isNaN(event.amount)) {
    throw new Error(`validation_failed amount partner=${event.partnerId} eventId=${event.eventId}`);
  }
  if (!hasText(event.currency)) {
    throw new Error(`validation_failed currency partner=${event.partnerId} eventId=${event.eventId}`);
  }
  if (!hasText(event.eventTs)) {
    throw new Error(`validation_failed eventTs partner=${event.partnerId} eventId=${event.eventId}`);
  }
  if (!hasText(event.businessDate)) {
    throw new Error(`validation_failed businessDate partner=${event.partnerId} eventId=${event.eventId}`);
  }
}
