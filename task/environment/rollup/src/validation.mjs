function hasText(value) {
  return typeof value === "string" && value.trim().length > 0;
}

export function validateNormalizedEvent(event) {
  if (!hasText(event.partnerId)) {
    throw new Error("validation_failed partnerId");
  }
  if (!hasText(event.account)) {
    throw new Error(`validation_failed account partner=${event.partnerId}`);
  }
  if (typeof event.amount !== "number" || Number.isNaN(event.amount)) {
    throw new Error(`validation_failed amount partner=${event.partnerId}`);
  }
  if (!hasText(event.currency)) {
    throw new Error(`validation_failed currency partner=${event.partnerId}`);
  }
  if (!hasText(event.timestamp)) {
    throw new Error(`validation_failed timestamp partner=${event.partnerId}`);
  }
  if (!hasText(event.reference)) {
    throw new Error(`validation_failed reference partner=${event.partnerId}`);
  }
  if (!hasText(event.businessDate)) {
    throw new Error(`validation_failed businessDate partner=${event.partnerId}`);
  }
}
