#!/bin/bash
set -euo pipefail

cd /workspace/rollup

python3 - <<'PY'
from pathlib import Path

files = {
    "src/registry.mjs": """import fs from "node:fs";

function requireText(value, label, partnerId) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`registry_invalid partner=${partnerId} field=${label}`);
  }
  return value;
}

function buildResolverSignature(partner) {
  return JSON.stringify({
    profile: partner.profile,
    eventIdPath: partner.eventIdPath,
    sourceTsPath: partner.sourceTsPath,
    accountPath: partner.accountPath,
    settlement: partner.settlement
  });
}

function normalizePartner(partner) {
  const profile = requireText(partner.profile, "profile", partner.id);
  const eventIdPath = requireText(partner.eventIdPath, "eventIdPath", partner.id);
  const sourceTsPath = requireText(partner.sourceTsPath, "sourceTsPath", partner.id);
  const accountPath = requireText(partner.accountPath, "accountPath", partner.id);
  const settlement = partner.settlement || {};
  const zone = requireText(settlement.zone, "settlement.zone", partner.id);
  const cutoffLocal = requireText(settlement.cutoffLocal, "settlement.cutoffLocal", partner.id);

  return {
    ...partner,
    profile,
    eventIdPath,
    sourceTsPath,
    accountPath,
    settlement: {
      zone,
      cutoffLocal
    },
    resolverSignature: buildResolverSignature({
      profile,
      eventIdPath,
      sourceTsPath,
      accountPath,
      settlement: {
        zone,
        cutoffLocal
      }
    })
  };
}

export function loadRegistry(registryPath) {
  const registry = JSON.parse(fs.readFileSync(registryPath, "utf8"));
  return {
    ...registry,
    partners: registry.partners.map(normalizePartner)
  };
}

export function enabledPartners(registry, explicitOrder = []) {
  const enabled = registry.partners
    .filter((partner) => partner.enabled)
    .sort((left, right) => left.sortOrder - right.sortOrder);

  if (explicitOrder.length === 0) {
    return enabled;
  }

  const byId = new Map(enabled.map((partner) => [partner.id, partner]));
  const ordered = [];

  for (const partnerId of explicitOrder) {
    if (byId.has(partnerId)) {
      ordered.push(byId.get(partnerId));
      byId.delete(partnerId);
    }
  }

  return [...ordered, ...byId.values()];
}
""",
    "src/payload-access.mjs": """const pathReaderCache = new Map();
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
    formatter.formatToParts(instant)
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

export function compilePathReader(pathExpression) {
  if (!pathReaderCache.has(pathExpression)) {
    const segments = pathExpression.split(".");
    pathReaderCache.set(pathExpression, (source) => segments.reduce((current, segment) => {
      if (current === undefined || current === null) {
        return undefined;
      }
      return current[segment];
    }, source));
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

function compileBusinessDateResolver(sourceTsPath, settlement) {
  const readEventTs = compilePathReader(sourceTsPath);
  return {
    readEventTs,
    resolveBusinessDate(raw) {
      return localBusinessDate(readEventTs(raw), settlement);
    }
  };
}

export function buildNormalizationContext(partner) {
  if (resolverCache.has(partner.resolverSignature)) {
    return resolverCache.get(partner.resolverSignature);
  }

  const readEventId = compilePathReader(partner.eventIdPath);
  const readAccountId = compilePathReader(partner.accountPath);
  const settlement = { ...partner.settlement };
  const businessResolver = compileBusinessDateResolver(partner.sourceTsPath, settlement);

  const context = {
    readEventId,
    readAccountId,
    readEventTs: businessResolver.readEventTs,
    resolveBusinessDate: businessResolver.resolveBusinessDate
  };

  resolverCache.set(partner.resolverSignature, context);
  return context;
}

export const getNormalizationContext = buildNormalizationContext;

export function resetResolverCache() {
  resolverCache.clear();
}
""",
    "src/partner-clients/index.mjs": """import { buildNormalizationContext } from "../payload-access.mjs";
import * as alpha from "./alpha.mjs";
import * as beta from "./beta.mjs";
import * as delta from "./delta.mjs";
import * as gamma from "./gamma.mjs";

const clients = {
  alpha,
  beta,
  gamma,
  delta
};

export async function fetchNormalizedPartnerEvents(partner) {
  const client = clients[partner.id];
  if (!client) {
    throw new Error(`unknown_partner ${partner.id}`);
  }

  const normalizationContext = buildNormalizationContext(partner);
  const payload = await client.fetchEvents(partner);
  return {
    fetchedCount: payload.events.length,
    events: payload.events.map((raw) => client.normalizeEvent(raw, partner, normalizationContext))
  };
}
""",
    "src/partner-clients/alpha.mjs": """function signedAmount(raw) {
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
    throw new Error(`fetch_failed partner=${partner.id} status=${response.status}`);
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
""",
    "src/partner-clients/gamma.mjs": """function amountFromNested(raw) {
  const amount = Number(raw.entry.amountText);
  if (raw.entry.code === "refund") {
    return -Math.abs(amount);
  }
  if (raw.entry.code === "zero") {
    return 0;
  }
  return Math.abs(amount);
}

export async function fetchEvents(partner) {
  const response = await fetch(`${partner.baseUrl}${partner.requestPath}`);
  if (!response.ok) {
    throw new Error(`fetch_failed partner=${partner.id} status=${response.status}`);
  }
  return response.json();
}

export function normalizeEvent(raw, partner, context) {
  return {
    partnerId: partner.id,
    eventId: context.readEventId(raw),
    accountId: context.readAccountId(raw),
    amount: amountFromNested(raw),
    currency: raw.currency || partner.currency,
    eventTs: context.readEventTs(raw),
    businessDate: context.resolveBusinessDate(raw)
  };
}
""",
    "src/partner-clients/shared-ledger.mjs": """function minorAmount(raw) {
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
  const { readEventId, readAccountId, readEventTs, resolveBusinessDate } = context;
  return {
    partnerId: partner.id,
    eventId: readEventId(raw),
    accountId: readAccountId(raw),
    amount: minorAmount(raw),
    currency: raw.currency || partner.currency,
    eventTs: readEventTs(raw),
    businessDate: resolveBusinessDate(raw)
  };
}
""",
    "src/workset.mjs": """export function isRequestedBusinessDay(event, requestedDay) {
  return typeof event.businessDate === "string" && event.businessDate === requestedDay;
}
""",
}

for relative_path, content in files.items():
  Path(relative_path).write_text(content, encoding="utf-8")
PY

/usr/local/bin/reset-rollup-runtime
/usr/local/bin/start-rollup-mocks
trap '/usr/local/bin/stop-rollup-mocks' EXIT
/usr/local/bin/run-rollup-job --diagnostics
node tools/inspect-rollup.mjs >/tmp/rollup-inspection.log
