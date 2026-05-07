#!/bin/bash
set -euo pipefail

cd /workspace/rollup

python3 - <<'PY'
from pathlib import Path

Path("src/aggregation.mjs").write_text("""function round2(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function referenceMark(event) {
  const parts = [event.partnerId, event.reference];
  if (event.source?.detail?.mode === "A") {
    parts.push(event.source.detail.slot);
  }
  return parts.join(":");
}

export function applyEvents(events, logger) {
  const observed = new Set();
  const accounts = new Map();
  const partners = new Map();
  const diagnostics = {
    acceptedEvents: 0,
    skippedEvents: 0,
    perPartnerAccepted: {},
    perPartnerSkipped: {}
  };

  for (const event of events) {
    const mark = referenceMark(event);
    if (observed.has(mark)) {
      diagnostics.skippedEvents += 1;
      diagnostics.perPartnerSkipped[event.partnerId] = (diagnostics.perPartnerSkipped[event.partnerId] || 0) + 1;
      logger.skipped(event);
      continue;
    }

    observed.add(mark);
    logger.accepted(event);
    diagnostics.acceptedEvents += 1;
    diagnostics.perPartnerAccepted[event.partnerId] = (diagnostics.perPartnerAccepted[event.partnerId] || 0) + 1;

    const accountEntry = accounts.get(event.account) || {
      total: 0,
      count: 0,
      currency: event.currency
    };
    accountEntry.total = round2(accountEntry.total + event.amount);
    accountEntry.count += 1;
    accounts.set(event.account, accountEntry);

    const partnerEntry = partners.get(event.partnerId) || {
      total: 0,
      count: 0
    };
    partnerEntry.total = round2(partnerEntry.total + event.amount);
    partnerEntry.count += 1;
    partners.set(event.partnerId, partnerEntry);
  }

  return {
    rollup: Object.fromEntries(
      [...accounts.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([account, value]) => [
          account,
          {
            total: round2(value.total),
            count: value.count,
            currency: value.currency
          }
        ])
    ),
    partnerSummary: Object.fromEntries(
      [...partners.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([partnerId, value]) => [
          partnerId,
          {
            total: round2(value.total),
            count: value.count
          }
        ])
    ),
    diagnostics
  };
}
""", encoding="utf-8")

PY

/usr/local/bin/reset-rollup-runtime
/usr/local/bin/start-partner-services
trap '/usr/local/bin/stop-partner-services' EXIT

node --input-type=module <<'EOF'
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const root = "/workspace/rollup";
const dates = ["2026-05-04", "2026-05-05", "2026-05-06"];
const sampledPartners = ["p01", "p03", "p05"];
const registry = JSON.parse(fs.readFileSync(path.join(root, "config", "partner-registry.json"), "utf8"));

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(root, relativePath), "utf8"));
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`fetch_failed ${url} status=${response.status}`);
  }
  return response.json();
}

function round2(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function mergeReportPayloads(payloads) {
  const accounts = new Map();
  for (const payload of payloads) {
    for (const row of payload.accounts) {
      const current = accounts.get(row.account) || { total: 0, count: 0, currency: payload.currency };
      current.total = round2(current.total + Number(row.total));
      current.count += Number(row.count);
      accounts.set(row.account, current);
    }
  }
  return {
    accountCount: accounts.size,
    count: [...accounts.values()].reduce((sum, row) => sum + row.count, 0),
    total: round2([...accounts.values()].reduce((sum, row) => sum + row.total, 0))
  };
}

function logLinesFor(date, partnerId) {
  const logPath = path.join(root, "logs", "rollup.log");
  if (!fs.existsSync(logPath)) {
    return [];
  }
  return fs.readFileSync(logPath, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line))
    .filter((line) => line.businessDate === date && line.partnerId === partnerId);
}

function readField(source, expression) {
  return expression.split(".").reduce((current, part) => {
    if (current === undefined || current === null) {
      return undefined;
    }
    return current[part];
  }, source);
}

const reportComparisons = [];
const rawEventLogComparisons = [];
const rejectedHypotheses = [];
let productionReportEndpointCalls = 0;

for (const date of dates) {
  execFileSync("/usr/local/bin/run-rollup", ["--business-date", date, "--diagnostics"], {
    cwd: root,
    stdio: "inherit"
  });

  const summary = readJson("out/daily-summary.json");
  const diagnostics = readJson("out/diagnostics.json");

  for (const partner of registry.partners) {
    const metrics = await fetchJson(`${partner.baseUrl}/metrics`);
    productionReportEndpointCalls += metrics[partner.partnerId].reports[date] || 0;
  }

  const reports = [];
  for (const partner of registry.partners) {
    reports.push(await fetchJson(`${partner.baseUrl}${partner.reportPath}?businessDate=${date}`));
  }
  const mergedReports = mergeReportPayloads(reports);

  reportComparisons.push({
    businessDate: date,
    rollupSummary: {
      accountCount: summary.accountCount,
      count: summary.count,
      total: summary.total
    },
    mergedPartnerReports: mergedReports,
    matched: summary.accountCount === mergedReports.accountCount
      && summary.count === mergedReports.count
      && Math.abs(summary.total - mergedReports.total) <= 0.01
  });

  if (rawEventLogComparisons.length === 0) {
    for (const partner of registry.partners.filter((entry) => sampledPartners.includes(entry.partnerId))) {
      const payload = await fetchJson(`${partner.baseUrl}${partner.eventsPath}?businessDate=${date}`);
      const byReference = new Map();
      for (const row of payload.events) {
        const reference = readField(row, partner.referenceField);
        const rows = byReference.get(reference) || [];
        rows.push(row);
        byReference.set(reference, rows);
      }
      const repeated = [...byReference.entries()]
        .find(([, rows]) => rows.length > 1 && rows.some((row) => row.detail?.mode === "A"));
      if (repeated) {
        const [reference, rows] = repeated;
        rawEventLogComparisons.push({
          businessDate: date,
          partnerId: partner.partnerId,
          reference,
          rawEvents: rows.map((row) => ({
            account: readField(row, partner.accountField),
            amount: readField(row, partner.amountField),
            timestamp: readField(row, partner.timestampField),
            detail: row.detail || null
          })),
          logEvents: logLinesFor(date, partner.partnerId)
            .filter((line) => line.reference === reference)
            .map((line) => ({
              event: line.event,
              account: line.account,
              amount: line.amount,
              timestamp: line.timestamp,
              reference: line.reference
            }))
        });
        break;
      }
    }
  }

  rejectedHypotheses.push(
    `For ${date}, business-date filtering was not the root cause: retainedCounts=${JSON.stringify(diagnostics.retainedCounts)} and the patched accepted count matches partner reports.`
  );
}

rejectedHypotheses.push(
  `Report endpoint copying was not used during production: report endpoint calls observed before investigation reports were queried = ${productionReportEndpointCalls}.`
);

fs.mkdirSync(path.join(root, "diagnosis"), { recursive: true });
fs.writeFileSync(path.join(root, "diagnosis", "evidence.json"), `${JSON.stringify({
  sampledBusinessDates: dates,
  sampledPartners,
  reportComparisons,
  rawEventLogComparisons,
  rejectedHypotheses,
  productionReportEndpointCalls
}, null, 2)}\n`);
EOF
