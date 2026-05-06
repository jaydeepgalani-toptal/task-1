import path from "node:path";
import { fileURLToPath } from "node:url";

import { applyEvents } from "./aggregation.mjs";
import { createLogger } from "./logger.mjs";
import { fetchNormalizedPartnerEvents } from "./partner-clients/index.mjs";
import { enabledPartners, loadRegistry } from "./registry.mjs";
import { writeRollupReports } from "./report-writer.mjs";
import { validateNormalizedEvent } from "./validation.mjs";
import { isRequestedBusinessDay } from "./workset.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const entryPath = process.argv[1] ? path.resolve(process.argv[1]) : "";

function round2(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function parseArgs(argv) {
  return {
    diagnostics: argv.includes("--diagnostics"),
    help: argv.includes("--help")
  };
}

function usage() {
  console.log("daily-account-rollup [--diagnostics] [--help]");
}

export async function runRollupJob(options = {}) {
  const registryPath = options.registryPath || process.env.REGISTRY_PATH || path.join(rootDir, "config", "partner-registry.json");
  const outDir = path.join(rootDir, "out");
  const logPath = path.join(rootDir, "logs", "rollup.log");
  const registry = loadRegistry(registryPath);
  const orderOverride = options.partnerOrder
    || (process.env.PARTNER_ORDER || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
  const diagnosticsEnabled = options.diagnostics ?? false;
  const partners = enabledPartners(registry, orderOverride);
  const logger = createLogger(logPath);
  const allEvents = [];
  const fetchedCounts = {};
  const retainedCounts = {};

  logger.info({ stage: "parsing", action: "begin", businessDate: registry.businessDate });

  for (const partner of partners) {
    logger.info({ stage: "routing", partner: partner.id, url: `${partner.baseUrl}${partner.requestPath}` });
    const result = await fetchNormalizedPartnerEvents(partner);
    fetchedCounts[partner.id] = result.fetchedCount;
    logger.info({ stage: "validation", partner: partner.id, fetchedCount: result.fetchedCount });

    for (const event of result.events) {
      validateNormalizedEvent(event);
      if (isRequestedBusinessDay(event, registry.businessDate)) {
        allEvents.push(event);
        retainedCounts[partner.id] = (retainedCounts[partner.id] || 0) + 1;
      }
    }

    logger.info({ stage: "schema-mapping", partner: partner.id, normalizedCount: result.events.length });
  }

  logger.info({ stage: "aggregation", action: "begin", candidateEvents: allEvents.length });
  const aggregated = applyEvents(allEvents, logger);

  const totalAmount = round2(
    Object.values(aggregated.rollup).reduce((sum, value) => sum + value.total, 0)
  );
  const totalTransactions = Object.values(aggregated.rollup).reduce(
    (sum, value) => sum + value.transactionCount,
    0
  );
  const summary = {
    businessDate: registry.businessDate,
    accountCount: Object.keys(aggregated.rollup).length,
    transactionCount: totalTransactions,
    grandTotal: totalAmount,
    partners: aggregated.partnerSummary
  };
  const diagnostics = {
    businessDate: registry.businessDate,
    fetchedCounts,
    retainedCounts,
    acceptedEvents: aggregated.diagnostics.acceptedEvents,
    duplicateEvents: aggregated.diagnostics.duplicateEvents,
    perPartnerAccepted: aggregated.diagnostics.perPartnerAccepted,
    perPartnerDuplicates: aggregated.diagnostics.perPartnerDuplicates
  };

  logger.info({ stage: "summary-reporting", accountCount: summary.accountCount, transactionCount: summary.transactionCount });
  writeRollupReports(outDir, aggregated.rollup, summary, diagnostics);
  logger.info({ stage: "diagnostics", duplicateEvents: diagnostics.duplicateEvents, acceptedEvents: diagnostics.acceptedEvents });

  if (diagnosticsEnabled) {
    logger.info({ stage: "diagnostics", action: "extended" });
  }

  logger.info({ stage: "verification", action: "completed" });
  return { registry, summary, diagnostics };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    usage();
    return;
  }

  await runRollupJob({ diagnostics: args.diagnostics });
}

if (entryPath === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    const logPath = path.join(rootDir, "logs", "rollup.log");
    const logger = createLogger(logPath);
    logger.error({
      stage: "validation",
      action: "failed",
      error: error.message
    });
    process.exit(1);
  });
}
