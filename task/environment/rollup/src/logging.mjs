import fs from "node:fs";
import path from "node:path";

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

export function createLogger(logPath) {
  ensureDir(path.dirname(logPath));

  function write(payload) {
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      ...payload
    });
    console.log(line);
    fs.appendFileSync(logPath, `${line}\n`, "utf8");
  }

  function eventFields(name, event) {
    return {
      event: name,
      partnerId: event.partnerId,
      businessDate: event.businessDate,
      account: event.account,
      amount: event.amount.toFixed(2),
      timestamp: event.timestamp,
      reference: event.reference
    };
  }

  return {
    info(fields) {
      write(fields);
    },
    error(fields) {
      write({ event: "error", ...fields });
    },
    accepted(event) {
      write(eventFields("acceptedEvent", event));
    },
    skipped(event) {
      write(eventFields("skippedEvent", event));
    }
  };
}
