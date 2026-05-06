import http from "node:http";
import fs from "node:fs";
import path from "node:path";

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--partner") {
      args.partner = argv[index + 1];
      index += 1;
    } else if (value === "--port") {
      args.port = Number(argv[index + 1]);
      index += 1;
    } else if (value === "--fixtures-root") {
      args.fixturesRoot = argv[index + 1];
      index += 1;
    } else if (value === "--state-dir") {
      args.stateDir = argv[index + 1];
      index += 1;
    }
  }
  return args;
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function initialState(partner) {
  return {
    partner,
    requests: {
      total: 0,
      events: 0,
      metrics: 0,
      health: 0,
      reset: 0
    },
    requestLog: []
  };
}

function loadState(filePath, partner) {
  if (!fs.existsSync(filePath)) {
    return initialState(partner);
  }
  return readJson(filePath);
}

const args = parseArgs(process.argv.slice(2));
if (!args.partner || !args.port) {
  console.error("usage: node mock/server.mjs --partner <id> --port <port> [--fixtures-root <dir>] [--state-dir <dir>]");
  process.exit(1);
}

const partner = args.partner;
const fixturesRoot = args.fixturesRoot || "/workspace/rollup/fixtures/current";
const stateDir = args.stateDir || "/workspace/rollup/runtime/mock-state";
const statePath = path.join(stateDir, `${partner}.json`);

ensureDir(stateDir);

function recordRequest(method, requestPath) {
  const state = loadState(statePath, partner);
  state.requests.total += 1;
  if (requestPath === "/events") {
    state.requests.events += 1;
  } else if (requestPath === "/metrics") {
    state.requests.metrics += 1;
  } else if (requestPath === "/health") {
    state.requests.health += 1;
  } else if (requestPath === "/reset") {
    state.requests.reset += 1;
  }
  state.requestLog.push({
    method,
    path: requestPath,
    timestamp: new Date().toISOString()
  });
  writeJson(statePath, state);
}

function eventsPayload() {
  const filePath = path.join(fixturesRoot, "partner-events", `${partner}.json`);
  return readJson(filePath);
}

const server = http.createServer((request, response) => {
  recordRequest(request.method || "GET", request.url || "/");

  if (request.url === "/health") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ ok: true, partner }));
    return;
  }

  if (request.url === "/metrics") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(loadState(statePath, partner)));
    return;
  }

  if (request.url === "/reset") {
    writeJson(statePath, initialState(partner));
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ ok: true, partner }));
    return;
  }

  if (request.url === "/events") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(eventsPayload()));
    return;
  }

  response.writeHead(404, { "content-type": "application/json" });
  response.end(JSON.stringify({ ok: false, error: "not_found" }));
});

server.listen(args.port, "127.0.0.1", () => {
  console.log(`mock server listening partner=${partner} port=${args.port} fixturesRoot=${fixturesRoot}`);
});
