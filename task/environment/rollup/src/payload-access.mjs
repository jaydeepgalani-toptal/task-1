const pathReaderCache = new Map();
const formatterCache = new Map();
const resolverCache = new Map();

function nextDate(dateString) {
  const value = new Date(`${dateString}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
}

function parseCutoffLocal(value) {
  const [hours, minutes] = value.split(":").map((part) => Number(part));
  return { hours, minutes };
}

function zonedParts(isoValue, zone) {
  const instant = new Date(isoValue);
  if (Number.isNaN(instant.getTime())) {
    return null;
  }

  let formatter = formatterCache.get(zone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23"
    });
    formatterCache.set(zone, formatter);
  }

  const values = Object.fromEntries(
    formatter
      .formatToParts(instant)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value])
  );

  return {
    date: `${values.year}-${values.month}-${values.day}`,
    hours: Number(values.hour),
    minutes: Number(values.minute),
    seconds: Number(values.second)
  };
}

function contextCacheKey(partner) {
  return JSON.stringify({
    profile: partner.profile,
    eventIdentity: partner.eventIdentity,
    eventIdPath: partner.eventIdPath,
    postingSequencePath: partner.postingSequencePath || "",
    accountPath: partner.accountPath,
    sourceTsPath: partner.sourceTsPath,
    settlement: partner.settlement
  });
}

export function compilePathReader(pathExpression) {
  if (!pathReaderCache.has(pathExpression)) {
    const segments = pathExpression.split(".");
    pathReaderCache.set(pathExpression, (source) =>
      segments.reduce((current, segment) => {
        if (current === undefined || current === null) {
          return undefined;
        }
        return current[segment];
      }, source)
    );
  }

  return pathReaderCache.get(pathExpression);
}

export function localBusinessDate(eventTs, settlement) {
  const parts = zonedParts(eventTs, settlement.zone);
  if (!parts) {
    return "";
  }

  const cutoff = parseCutoffLocal(settlement.cutoffLocal);
  if (
    parts.hours > cutoff.hours ||
    (parts.hours === cutoff.hours && parts.minutes >= cutoff.minutes)
  ) {
    return nextDate(parts.date);
  }

  return parts.date;
}

export function getNormalizationContext(partner) {
  const key = contextCacheKey(partner);
  if (resolverCache.has(key)) {
    return resolverCache.get(key);
  }
  
  const readEventId = compilePathReader(partner.eventIdPath);
  const readAccountId = compilePathReader(partner.accountPath);
  const readPostingSequence = partner.postingSequencePath
    ? compilePathReader(partner.postingSequencePath)
    : () => undefined;
  const readEventTs = compilePathReader(partner.sourceTsPath);
  const settlement = { ...partner.settlement };

  const context = {
    readEventId,
    readAccountId,
    readPostingSequence,
    readEventTs,
    resolveBusinessDate(raw) {
      return localBusinessDate(readEventTs(raw), settlement);
    }
  };

  resolverCache.set(key, context);
  return context;
}

export function resetResolverCache() {
  resolverCache.clear();
}
