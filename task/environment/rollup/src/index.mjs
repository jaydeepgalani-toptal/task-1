import path from "node:path";
import { fileURLToPath } from "node:url";

import { applyEvents } from "./aggregation.mjs";
import { getJson } from "./http-client.mjs";
import { createLogger } from "./logging.mjs";
import { normalizeEvent } from "./normalization.mjs";
import { enabledPartners, loadRegistry } from "./registry.mjs";
import { writeRollupReports } from "./report-writer.mjs";
import { validateNormalizedEvent } from "./validation.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const entryPath = process.argv[1] ? path.resolve(process.argv[1]) : "";

function round2(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function parseArgs(argv) {
  const args = {
    diagnostics: false,
    help: false,
    businessDate: process.env.BUSINESS_DATE || "2026-05-06"
  };

  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--diagnostics") {
      args.diagnostics = true;
    } else if (value === "--help") {
      args.help = true;
    } else if (value === "--business-date") {
      args.businessDate = argv[index + 1];
      index += 1;
    }
  }

  return args;
}

function usage() {
  console.log("daily-account-rollup [--business-date YYYY-MM-DD] [--diagnostics] [--help]");
}

function eventsUrl(partner, businessDate) {
  const url = new URL(partner.eventsPath, partner.baseUrl);
  url.searchParams.set("businessDate", businessDate);
  return url.toString();
}

export async function runRollupJob(options = {}) {
  const registryPath = options.registryPath || process.env.REGISTRY_PATH || path.join(rootDir, "config", "partner-registry.json");
  const businessDate = options.businessDate || process.env.BUSINESS_DATE || "2026-05-06";
  const outDir = path.join(rootDir, "out");
  const logPath = path.join(rootDir, "logs", "rollup.log");
  const registry = loadRegistry(registryPath);
  const partners = enabledPartners(registry);
  const logger = createLogger(logPath);
  const allEvents = [];
  const fetchedCounts = {};
  const retainedCounts = {};

  logger.info({ event: "begin", businessDate });

  for (const partner of partners) {
    logger.info({ event: "request", partnerId: partner.partnerId });
    const payload = await getJson(eventsUrl(partner, businessDate));
    const normalized = payload.events.map((source) => normalizeEvent(source, partner));
    fetchedCounts[partner.partnerId] = normalized.length;

    for (const event of normalized) {
      validateNormalizedEvent(event);
      if (event.businessDate === businessDate) {
        allEvents.push(event);
        retainedCounts[partner.partnerId] = (retainedCounts[partner.partnerId] || 0) + 1;
      }
    }
  }

  const aggregated = applyEvents(allEvents, logger);
  const totalAmount = round2(
    Object.values(aggregated.rollup).reduce((sum, value) => sum + value.total, 0)
  );
  const totalCount = Object.values(aggregated.rollup).reduce(
    (sum, value) => sum + value.count,
    0
  );
  const summary = {
    businessDate,
    accountCount: Object.keys(aggregated.rollup).length,
    count: totalCount,
    total: totalAmount,
    partners: aggregated.partnerSummary
  };
  const diagnostics = {
    businessDate,
    fetchedCounts,
    retainedCounts,
    acceptedEvents: aggregated.diagnostics.acceptedEvents,
    skippedEvents: aggregated.diagnostics.skippedEvents,
    perPartnerAccepted: aggregated.diagnostics.perPartnerAccepted,
    perPartnerSkipped: aggregated.diagnostics.perPartnerSkipped
  };

  writeRollupReports(outDir, aggregated.rollup, summary, diagnostics);
  logger.info({ event: "completed", businessDate, accountCount: summary.accountCount, count: summary.count });
  return { registry, summary, diagnostics };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    usage();
    return;
  }

  await runRollupJob({ businessDate: args.businessDate, diagnostics: args.diagnostics });
}

if (entryPath === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    const logPath = path.join(rootDir, "logs", "rollup.log");
    const logger = createLogger(logPath);
    logger.error({ message: error.message });
    process.exit(1);
  });
}
