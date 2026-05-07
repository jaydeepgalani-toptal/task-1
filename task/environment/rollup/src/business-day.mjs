function nextDate(value) {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

function parseCutoff(value) {
  const [hour, minute] = value.split(":").map((part) => Number(part));
  return { hour, minute };
}

export function selectBusinessDate(timestamp, settlementCutoff) {
  const instant = new Date(timestamp);
  if (Number.isNaN(instant.getTime())) {
    return "";
  }

  const date = instant.toISOString().slice(0, 10);
  const cutoff = parseCutoff(settlementCutoff);
  const hour = instant.getUTCHours();
  const minute = instant.getUTCMinutes();

  if (hour > cutoff.hour || (hour === cutoff.hour && minute >= cutoff.minute)) {
    return nextDate(date);
  }

  return date;
}
