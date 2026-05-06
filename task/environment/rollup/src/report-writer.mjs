import fs from "node:fs";
import path from "node:path";

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function writeAtomically(filePath, payload) {
  ensureDir(path.dirname(filePath));
  const tempPath = `${filePath}.tmp`;
  fs.writeFileSync(tempPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  fs.renameSync(tempPath, filePath);
}

export function writeRollupReports(outDir, rollup, summary, diagnostics) {
  writeAtomically(path.join(outDir, "daily-rollup.json"), rollup);
  writeAtomically(path.join(outDir, "daily-summary.json"), summary);
  writeAtomically(path.join(outDir, "diagnostics.json"), diagnostics);
}
