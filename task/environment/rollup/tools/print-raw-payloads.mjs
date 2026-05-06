import path from "node:path";
import { fileURLToPath } from "node:url";

import { compilePathReader, localBusinessDate } from "../src/payload-access.mjs";
import { loadRegistry } from "../src/registry.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const registry = loadRegistry(path.join(rootDir, "config", "partner-registry.json"));

for (const partner of registry.partners.filter((entry) => entry.enabled)) {
  const response = await fetch(`${partner.baseUrl}${partner.requestPath}`);
  const payload = await response.json();
  const readEventTs = compilePathReader(partner.sourceTsPath);
  const businessDates = new Set();
  const sourceDays = new Set();

  for (const event of payload.events) {
    const eventTs = readEventTs(event);
    sourceDays.add(String(eventTs).slice(0, 10));
    businessDates.add(localBusinessDate(eventTs, partner.settlement));
  }

  console.log(JSON.stringify({
    partner: partner.id,
    rawEventCount: payload.events.length,
    sourceDays: [...sourceDays].sort(),
    businessDates: [...businessDates].sort()
  }, null, 2));
}
