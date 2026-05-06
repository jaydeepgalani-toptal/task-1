import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const logPath = path.join(rootDir, "logs", "rollup.log");
const outPath = path.join(rootDir, "out", "inspection-summary.json");

function round2(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function parseLine(line) {
  const tokens = Object.fromEntries(
    line
      .split(" ")
      .filter(Boolean)
      .map((token) => {
        const index = token.indexOf("=");
        if (index === -1) {
          return [token, ""];
        }
        return [token.slice(0, index), token.slice(index + 1)];
      })
  );
  return tokens;
}

const summary = { partners: {} };
for (const line of fs.readFileSync(logPath, "utf8").split("\n")) {
  if (!line.includes("stage=ingestion")) {
    continue;
  }
  const fields = parseLine(line);
  const partner = fields.partner;
  const amount = Number(fields.amount);
  const partnerEntry = summary.partners[partner] || { total: 0, transactionCount: 0 };
  partnerEntry.total = round2(partnerEntry.total + amount);
  partnerEntry.transactionCount += 1;
  summary.partners[partner] = partnerEntry;
}

fs.writeFileSync(outPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
console.log(JSON.stringify(summary, null, 2));
