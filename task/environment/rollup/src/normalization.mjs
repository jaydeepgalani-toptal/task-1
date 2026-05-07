import { selectBusinessDate } from "./business-day.mjs";

const readers = new Map();

export function readField(source, expression) {
  if (!readers.has(expression)) {
    const parts = expression.split(".");
    readers.set(expression, (value) =>
      parts.reduce((current, part) => {
        if (current === undefined || current === null) {
          return undefined;
        }
        return current[part];
      }, value)
    );
  }

  return readers.get(expression)(source);
}

function parseAmount(value) {
  if (typeof value === "number") {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    return Number(value);
  }
  return Number.NaN;
}

export function normalizeEvent(source, partner) {
  const timestamp = readField(source, partner.timestampField);
  return {
    partnerId: partner.partnerId,
    account: readField(source, partner.accountField),
    amount: parseAmount(readField(source, partner.amountField)),
    timestamp,
    reference: readField(source, partner.referenceField),
    currency: partner.currency,
    businessDate: selectBusinessDate(timestamp, partner.settlementCutoff),
    source
  };
}
