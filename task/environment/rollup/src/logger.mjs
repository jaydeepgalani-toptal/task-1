import fs from "node:fs";
import path from "node:path";

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function formatField([key, value]) {
  return `${key}=${String(value).replace(/\s+/g, "_")}`;
}

export function createLogger(logPath) {
  ensureDir(path.dirname(logPath));

  function write(level, fields) {
    const line = [
      `ts=${new Date().toISOString()}`,
      `level=${level}`,
      ...Object.entries(fields).map(formatField)
    ].join(" ");
    console.log(line);
    fs.appendFileSync(logPath, `${line}\n`, "utf8");
  }

  return {
    info(fields) {
      write("info", fields);
    },
    error(fields) {
      write("error", fields);
    },
    ingestion(event) {
      write("info", {
        stage: "ingestion",
        partner: event.partnerId,
        account: event.accountId,
        eventId: event.eventId,
        postingSequence: event.postingSequence || "",
        amount: event.amount.toFixed(2),
        currency: event.currency
      });
    }
  };
}
