import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


ROOT = Path("/workspace/rollup")
CURRENT_FIXTURES = ROOT / "fixtures" / "current" / "partner-events"
PARTNER_EOD_DIR = ROOT / "fixtures" / "expected" / "partner-eod"
REGISTRY = ROOT / "config" / "partner-registry.json"
ROLLUP_OUT = ROOT / "out" / "daily-rollup.json"
SUMMARY_OUT = ROOT / "out" / "daily-summary.json"
DIAGNOSTICS_OUT = ROOT / "out" / "diagnostics.json"
INSPECTION_OUT = ROOT / "out" / "inspection-summary.json"
LOG_PATH = ROOT / "logs" / "rollup.log"
PACKAGE_JSON = ROOT / "package.json"

PARTNERS = ("alpha", "beta", "gamma", "delta")

ROOT_HASHES = {
    "config/partner-registry.json": "6122b1fb40ba286f238d178bb720dd7c4008964d03287a1cc0d66430212c293d",
    "fixtures/current/partner-events/alpha.json": "a8360d145ea5fa1a6e4200d6533c2bd96d4c332eba2d63be1b12211da6d0995a",
    "fixtures/current/partner-events/beta.json": "a2a0a83353ff51f6584210d50a945596248ebac7259d5a1ac199ecaf65b07c4b",
    "fixtures/current/partner-events/gamma.json": "128796fa1e17d0738848a0c492a03c26e6c1a24ff5634511af88e6e53deded67",
    "fixtures/current/partner-events/delta.json": "8bdad7601496287e129e0a90efa21724bf4c7eab7845fa419a52270599029621",
    "fixtures/expected/partner-eod/alpha.json": "edd9264d04764e735089e5ae2fcd808bfd10891716226f6ebe1f8307f4a30559",
    "fixtures/expected/partner-eod/beta.json": "feccb5fffa3e0039f9da9ac38db19851c11d2fa651bd68b9c6534e534e50bce2",
    "fixtures/expected/partner-eod/gamma.json": "7977b80985403e620fe36ddce6b11f4ced087173da1128135f9573679c1f148d",
    "fixtures/expected/partner-eod/delta.json": "1312c9a3c0271eddb99d8276a37f63f69a30b0ca18bbe35d9c99357ac9bac284",
    "package.json": "afbb2a1134511aca799685c28dcba19b702180fb0996d2b265fdb9ca0e427889",
    "tools/inspect-rollup.mjs": "37a7dd4302ab93f4540d0a22f239dc403c5f74251565ea028bcf91431e9aea79",
    "tools/print-raw-payloads.mjs": "28501cdcaefc1ba7dfbe25ea8467b5958d02f20430064003e45aa560ebed0e91",
}

SCRIPT_HASHES = {
    "/usr/local/bin/reset-rollup-runtime": "404432a3e56a3fcd45c6deb17fff1c3457795a387f93665ade7a821cd851ff27",
    "/usr/local/bin/start-rollup-mocks": "14df39fba845a9e8a9ca3ef0de75998cfa7d9f88016d49b8322947da9d5032d1",
    "/usr/local/bin/stop-rollup-mocks": "f27db74b160ae8f04d9a8a42399c6875a184b9a28c185de4c373e8b690156bf7",
    "/usr/local/bin/run-rollup-job": "8ca0e63159f2fd6f9773e567ee3d8506861617d1da00a29d17ed1e8164d55479",
}


def run(cmd, *, cwd=None, env=None, check=True):
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def canonical_json_bytes(path: Path) -> bytes:
    return json.dumps(read_json(path), sort_keys=True, separators=(",", ":")).encode("utf-8")


def read_path(source, path_expression: str):
    current = source
    for segment in path_expression.split("."):
        if current is None:
            return None
        current = current.get(segment)
    return current


def parse_cutoff(cutoff_local: str):
    hours, minutes = cutoff_local.split(":")
    return int(hours), int(minutes)


def local_business_date(event_ts: str, zone: str, cutoff_local: str) -> str:
    moment = datetime.fromisoformat(event_ts.replace("Z", "+00:00"))
    local_time = moment.astimezone(ZoneInfo(zone))
    cutoff_hour, cutoff_minute = parse_cutoff(cutoff_local)
    business_day = local_time.date()
    if (local_time.hour, local_time.minute, local_time.second, local_time.microsecond) >= (
        cutoff_hour,
        cutoff_minute,
        0,
        0,
    ):
        business_day += timedelta(days=1)
    return business_day.isoformat()


def signed_amount(raw: dict, partner_id: str) -> float:
    if partner_id == "alpha":
        amount = float(raw.get("amount", raw.get("amountValue")))
        if raw["kind"] == "refund":
            return round(-abs(amount), 2)
        if raw["kind"] == "zero":
            return 0.0
        return round(abs(amount), 2)

    if partner_id in {"beta", "delta"}:
        amount_minor = float(raw.get("amountMinor", raw.get("amountMinorText")))
        if raw["entryType"] == "refund":
            return round(-abs(amount_minor) / 100.0, 2)
        if raw["entryType"] == "zero":
            return 0.0
        return round(abs(amount_minor) / 100.0, 2)

    amount = float(raw["entry"]["amountText"])
    if raw["entry"]["code"] == "refund":
        return round(-abs(amount), 2)
    if raw["entry"]["code"] == "zero":
        return 0.0
    return round(abs(amount), 2)


def authoritative_events(fixtures_root: Path, registry_path: Path):
    registry = read_json(registry_path)
    accepted = []

    for partner in sorted(
        (entry for entry in registry["partners"] if entry["enabled"]),
        key=lambda entry: entry["sortOrder"],
    ):
        payload = read_json(fixtures_root / f"{partner['id']}.json")
        for raw in payload["events"]:
            event_ts = read_path(raw, partner["sourceTsPath"])
            account_id = read_path(raw, partner["accountPath"])
            canonical = {
                "partnerId": partner["id"],
                "eventId": read_path(raw, partner.get("eventIdPath", "eventId")),
                "accountId": account_id,
                "amount": signed_amount(raw, partner["id"]),
                "currency": raw.get("currency", partner["currency"]),
                "eventTs": event_ts,
                "businessDate": local_business_date(
                    event_ts,
                    partner["settlement"]["zone"],
                    partner["settlement"]["cutoffLocal"],
                ),
            }
            if canonical["businessDate"] == registry["businessDate"]:
                accepted.append(canonical)

    return accepted


def rollup_from_events(events):
    result = {}
    for event in events:
        entry = result.setdefault(
            event["accountId"],
            {"total": 0.0, "transactionCount": 0, "currency": event["currency"]},
        )
        entry["total"] = round(entry["total"] + event["amount"], 2)
        entry["transactionCount"] += 1
    return {account: result[account] for account in sorted(result)}


def rollup_from_events_with_dedupe(events):
    seen = set()
    retained = []
    for event in events:
        dedup_key = f"{event['partnerId']}:{event['accountId']}:{event['eventId']}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        retained.append(event)
    return rollup_from_events(retained)


def rollup_from_partner_eod(eod_dir: Path):
    merged = {}
    for partner in PARTNERS:
        payload = read_json(eod_dir / f"{partner}.json")["accounts"]
        for account_id, value in payload.items():
            entry = merged.setdefault(
                account_id,
                {"total": 0.0, "transactionCount": 0, "currency": value["currency"]},
            )
            entry["total"] = round(entry["total"] + value["total"], 2)
            entry["transactionCount"] += value["transactionCount"]
    return {account: merged[account] for account in sorted(merged)}


def partner_totals_from_eod(eod_dir: Path):
    totals = {}
    for partner in PARTNERS:
        accounts = read_json(eod_dir / f"{partner}.json")["accounts"]
        totals[partner] = {
            "total": round(sum(item["total"] for item in accounts.values()), 2),
            "transactionCount": sum(item["transactionCount"] for item in accounts.values()),
        }
    return totals


def parse_log_fields(line: str):
    fields = {}
    for token in line.strip().split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        fields[key] = value
    return fields


def ingestion_lines():
    return [
        parse_log_fields(line)
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines()
        if "stage=ingestion" in line
    ]


def logged_event_tuples():
    return sorted(
        (
            line["partner"],
            line["eventId"],
            line["account"],
            f"{float(line['amount']):.2f}",
            line["currency"],
        )
        for line in ingestion_lines()
    )


def expected_event_tuples(events):
    return sorted(
        (
            event["partnerId"],
            event["eventId"],
            event["accountId"],
            f"{event['amount']:.2f}",
            event["currency"],
        )
        for event in events
    )


def compute_log_partner_totals():
    totals = {}
    for line in ingestion_lines():
        entry = totals.setdefault(line["partner"], {"total": 0.0, "transactionCount": 0})
        entry["total"] = round(entry["total"] + float(line["amount"]), 2)
        entry["transactionCount"] += 1
    return totals


def load_request_state(partner: str):
    return read_json(ROOT / "runtime" / "mock-state" / f"{partner}.json")


def clean_outputs():
    shutil.rmtree(ROOT / "out", ignore_errors=True)
    shutil.rmtree(ROOT / "logs", ignore_errors=True)
    (ROOT / "out").mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)


@contextmanager
def mock_servers(fixtures_root=None):
    start_cmd = ["/usr/local/bin/start-rollup-mocks"]
    if fixtures_root is not None:
        start_cmd.extend(["--fixtures-root", str(fixtures_root)])
    run(["/usr/local/bin/reset-rollup-runtime"])
    run(start_cmd)
    try:
        yield
    finally:
        run(["/usr/local/bin/stop-rollup-mocks"])


def rollup_env(*, registry_path=None, partner_order=None):
    env = os.environ.copy()
    if registry_path is not None:
        env["REGISTRY_PATH"] = str(registry_path)
    if partner_order is not None:
        env["PARTNER_ORDER"] = partner_order
    return env


def run_rollup(*, registry_path=None, partner_order=None, diagnostics=False, check=True):
    command = ["/usr/local/bin/run-rollup-job"]
    if diagnostics:
        command.append("--diagnostics")
    return run(
        command,
        env=rollup_env(registry_path=registry_path, partner_order=partner_order),
        check=check,
    )


def run_same_process(specs):
    env = os.environ.copy()
    env["RUN_SPECS"] = json.dumps(specs)
    script = """
import fs from "node:fs";
import path from "node:path";

const specs = JSON.parse(process.env.RUN_SPECS);
const root = process.cwd();
const mod = await import("file://" + path.join(root, "src/index.mjs"));
const results = [];

for (const spec of specs) {
  await mod.runRollupJob(spec);
  results.push(JSON.parse(fs.readFileSync(path.join(root, "out", "daily-rollup.json"), "utf8")));
}

console.log("RESULT=" + JSON.stringify(results));
"""
    result = run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        env=env,
        check=False,
    )
    marker = next(
        (line for line in reversed(result.stdout.splitlines()) if line.startswith("RESULT=")),
        None,
    )
    payload = json.loads(marker.removeprefix("RESULT=")) if marker else None
    return result, payload


def assert_rollup_matches_expected(expected_rollup):
    actual = read_json(ROLLUP_OUT)
    assert set(actual) == set(expected_rollup)

    for account_id, expected_value in expected_rollup.items():
        actual_value = actual[account_id]
        assert set(actual_value) == {"total", "transactionCount", "currency"}
        assert isinstance(actual_value["total"], (int, float))
        assert not isinstance(actual_value["total"], bool)
        assert abs(actual_value["total"] - expected_value["total"]) <= 0.01
        assert actual_value["transactionCount"] == expected_value["transactionCount"]
        assert actual_value["currency"] == expected_value["currency"]


def write_temp_registry(payload):
    handle = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
    try:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        return Path(handle.name)
    finally:
        handle.close()


def build_held_out_fixture(temp_root: Path):
    current_root = temp_root / "current"
    fixtures_root = current_root / "partner-events"
    expected_root = temp_root / "expected" / "partner-eod"
    registry_path = temp_root / "config" / "partner-registry.json"
    fixtures_root.mkdir(parents=True, exist_ok=True)
    expected_root.mkdir(parents=True, exist_ok=True)
    registry = read_json(REGISTRY)

    for partner in registry["partners"]:
        if partner["id"] == "beta":
            partner["sourceTsPath"] = "mirror.eventTs"
            partner["accountPath"] = "mirror.accountRef"
        elif partner["id"] == "delta":
            partner["sourceTsPath"] = "record.eventTs"
            partner["accountPath"] = "record.accountRef"

    write_json(registry_path, registry)

    held_out_payloads = {
        "alpha": {
            "businessDate": "2026-05-06",
            "partner": "alpha",
            "events": [
                {
                    "eventId": "shared-h100",
                    "accountId": "acct-h100",
                    "kind": "credit",
                    "amount": 11.0,
                    "currency": "USD",
                    "eventTs": "2026-05-06T15:00:00Z",
                },
                {
                    "eventId": "ha-200",
                    "accountId": "acct-h200",
                    "kind": "refund",
                    "amount": 3.5,
                    "currency": "USD",
                    "eventTs": "2026-05-06T21:59:59Z",
                },
                {
                    "eventId": "ha-300",
                    "accountId": "acct-h300",
                    "kind": "zero",
                    "amount": 0,
                    "currency": "USD",
                    "eventTs": "2026-05-06T10:00:00Z",
                },
                {
                    "eventId": "shared-h860",
                    "accountId": "acct-h860",
                    "kind": "credit",
                    "amount": 1.75,
                    "currency": "USD",
                    "eventTs": "2026-05-06T16:30:00Z",
                },
                {
                    "eventId": "ha-cut",
                    "accountId": "acct-hcuta",
                    "kind": "credit",
                    "amount": 2.0,
                    "currency": "USD",
                    "eventTs": "2026-05-06T22:00:00Z",
                },
            ],
        },
        "beta": {
            "businessDate": "2026-05-06",
            "partner": "beta",
            "events": [
                {
                    "eventId": "shared-h100",
                    "record": {"accountRef": "acct-b910", "eventTs": "2026-05-06T10:00:00Z"},
                    "mirror": {"accountRef": "acct-h100", "eventTs": "2026-05-06T15:30:00Z"},
                    "entryType": "sale",
                    "amountMinor": 900,
                    "currency": "USD",
                },
                {
                    "eventId": "hb-400",
                    "record": {"accountRef": "acct-b920", "eventTs": "2026-05-06T13:00:00Z"},
                    "mirror": {"accountRef": "acct-h400", "eventTs": "2026-05-06T08:15:00Z"},
                    "entryType": "refund",
                    "amountMinor": 275,
                    "currency": "USD",
                },
                {
                    "eventId": "hb-710",
                    "record": {"accountRef": "acct-b930", "eventTs": "2026-05-06T23:30:00Z"},
                    "mirror": {"accountRef": "acct-h710", "eventTs": "2026-05-06T15:59:59Z"},
                    "entryType": "sale",
                    "amountMinor": 111,
                    "currency": "USD",
                },
                {
                    "eventId": "shared-h860",
                    "record": {"accountRef": "acct-b940", "eventTs": "2026-05-06T20:00:00Z"},
                    "mirror": {"accountRef": "acct-h860", "eventTs": "2026-05-06T14:00:00Z"},
                    "entryType": "sale",
                    "amountMinor": 125,
                    "currency": "USD",
                },
                {
                    "eventId": "hb-zero",
                    "record": {"accountRef": "acct-b950", "eventTs": "2026-05-06T18:30:00Z"},
                    "mirror": {"accountRef": "acct-h410", "eventTs": "2026-05-06T09:00:00Z"},
                    "entryType": "zero",
                    "amountMinor": 0,
                    "currency": "USD",
                },
                {
                    "eventId": "hb-cut",
                    "record": {"accountRef": "acct-b960", "eventTs": "2026-05-06T09:00:00Z"},
                    "mirror": {"accountRef": "acct-hcutb", "eventTs": "2026-05-06T16:00:00Z"},
                    "entryType": "sale",
                    "amountMinor": 200,
                    "currency": "USD",
                },
            ],
        },
        "gamma": {
            "businessDate": "2026-05-06",
            "partner": "gamma",
            "events": [
                {
                    "eventId": "hg-200",
                    "clock": {"eventTs": "2026-05-06T05:00:00Z"},
                    "payload": {"accountRef": "acct-h200"},
                    "entry": {"code": "sale", "amountText": "7.00"},
                    "currency": "USD",
                },
                {
                    "eventId": "shared-h300",
                    "clock": {"eventTs": "2026-05-06T04:30:00Z"},
                    "payload": {"accountRef": "acct-h300"},
                    "entry": {"code": "refund", "amountText": "1.50"},
                    "currency": "USD",
                },
                {
                    "eventId": "hg-500a",
                    "clock": {"eventTs": "2026-05-06T02:00:00Z"},
                    "payload": {"accountRef": "acct-h500"},
                    "entry": {"code": "zero", "amountText": "0.00"},
                    "currency": "USD",
                },
                {
                    "eventId": "hg-500b",
                    "clock": {"eventTs": "2026-05-06T06:59:59Z"},
                    "payload": {"accountRef": "acct-h500"},
                    "entry": {"code": "refund", "amountText": "2.25"},
                    "currency": "USD",
                },
                {
                    "eventId": "hg-cut",
                    "clock": {"eventTs": "2026-05-06T07:00:00Z"},
                    "payload": {"accountRef": "acct-hcutg"},
                    "entry": {"code": "sale", "amountText": "6.00"},
                    "currency": "USD",
                },
            ],
        },
        "delta": {
            "businessDate": "2026-05-06",
            "partner": "delta",
            "events": [
                {
                    "eventId": "shared-h150",
                    "record": {"accountRef": "acct-h150", "eventTs": "2026-05-06T20:00:00Z"},
                    "mirror": {"accountRef": "acct-d910", "eventTs": "2026-05-06T09:00:00Z"},
                    "entryType": "sale",
                    "amountMinorText": "500",
                    "currency": "USD",
                },
                {
                    "eventId": "hd-430",
                    "record": {"accountRef": "acct-h430", "eventTs": "2026-05-06T21:29:59Z"},
                    "mirror": {"accountRef": "acct-d920", "eventTs": "2026-05-06T12:00:00Z"},
                    "entryType": "refund",
                    "amountMinorText": "125",
                    "currency": "USD",
                },
                {
                    "eventId": "hd-440",
                    "record": {"accountRef": "acct-h440", "eventTs": "2026-05-06T18:00:00Z"},
                    "mirror": {"accountRef": "acct-d930", "eventTs": "2026-05-06T13:00:00Z"},
                    "entryType": "zero",
                    "amountMinorText": "0",
                    "currency": "USD",
                },
                {
                    "eventId": "shared-h860",
                    "record": {"accountRef": "acct-h860", "eventTs": "2026-05-06T16:00:00Z"},
                    "mirror": {"accountRef": "acct-d940", "eventTs": "2026-05-06T08:00:00Z"},
                    "entryType": "sale",
                    "amountMinorText": "240",
                    "currency": "USD",
                },
                {
                    "eventId": "hd-cut",
                    "record": {"accountRef": "acct-hcutd", "eventTs": "2026-05-06T21:30:00Z"},
                    "mirror": {"accountRef": "acct-d950", "eventTs": "2026-05-06T10:00:00Z"},
                    "entryType": "sale",
                    "amountMinorText": "300",
                    "currency": "USD",
                },
            ],
        },
    }

    for partner, payload in held_out_payloads.items():
        write_json(fixtures_root / f"{partner}.json", payload)

    accepted = authoritative_events(fixtures_root, registry_path)
    by_partner = {partner: [] for partner in PARTNERS}
    for event in accepted:
        by_partner[event["partnerId"]].append(event)
    for partner, events in by_partner.items():
        write_json(expected_root / f"{partner}.json", {"partner": partner, "accounts": rollup_from_events(events)})

    return current_root, registry_path, expected_root, accepted


@pytest.fixture(scope="session", autouse=True)
def npm_ci():
    result = run(["npm", "ci"], cwd=ROOT)
    assert result.returncode == 0


def test_build_and_helper_scripts_work():
    # Spec: the project installs, the CLI is discoverable, and the helper scripts start the real service successfully.
    help_result = run(["node", "src/index.mjs", "--help"], cwd=ROOT)
    assert "daily-account-rollup" in help_result.stdout

    with mock_servers():
        result = run_rollup()
        assert result.returncode == 0
        assert ROLLUP_OUT.exists()


def test_mixed_run_matches_visible_partner_reports_and_logs():
    # Spec: normal mixed runs match the authoritative cross-partner result and accepted-event log set.
    expected_events = authoritative_events(CURRENT_FIXTURES, REGISTRY)
    expected_rollup = rollup_from_partner_eod(PARTNER_EOD_DIR)

    with mock_servers():
        result = run_rollup(diagnostics=True)
        assert result.returncode == 0
        assert_rollup_matches_expected(expected_rollup)

        diagnostics = read_json(DIAGNOSTICS_OUT)
        assert diagnostics["acceptedEvents"] == 17
        assert diagnostics["duplicateEvents"] == 0
        assert diagnostics["fetchedCounts"] == {"alpha": 5, "beta": 6, "gamma": 5, "delta": 5}
        assert diagnostics["retainedCounts"] == {"alpha": 4, "beta": 5, "gamma": 4, "delta": 4}

        assert logged_event_tuples() == expected_event_tuples(expected_events)
        assert len(ingestion_lines()) == 17
        assert sum(1 for item in logged_event_tuples() if item[1] == "shared-100") == 3
        assert sum(1 for item in logged_event_tuples() if item[1] == "shared-300") == 2
        assert sum(1 for item in logged_event_tuples() if item[1] == "shared-860") == 3

        actual = read_json(ROLLUP_OUT)
        assert actual["acct-440"]["total"] == 0
        assert actual["acct-440"]["transactionCount"] == 1
        assert any(item[1] == "a-200" and item[3] == "-15.25" for item in logged_event_tuples())
        assert any(item[1] == "d-430" and item[3] == "-2.75" for item in logged_event_tuples())
        assert any(item[1] == "g-500a" and item[3] == "0.00" for item in logged_event_tuples())

        log_text = LOG_PATH.read_text(encoding="utf-8")
        for marker in (
            "stage=parsing",
            "stage=validation",
            "stage=schema-mapping",
            "stage=routing",
            "stage=ingestion",
            "stage=aggregation",
            "stage=summary-reporting",
            "stage=diagnostics",
            "stage=verification",
        ):
            assert marker in log_text


def test_partner_request_counts_and_partner_totals_match_partner_eod():
    # Spec: each real endpoint is hit and per-partner logged totals reconcile with each partner report.
    expected_partner_totals = partner_totals_from_eod(PARTNER_EOD_DIR)

    with mock_servers():
        run_rollup(diagnostics=True)

        for partner in PARTNERS:
            state = load_request_state(partner)
            assert state["requests"]["events"] >= 1
            assert any(entry["path"] == "/events" for entry in state["requestLog"])

        inspect_result = run(["node", "tools/inspect-rollup.mjs"], cwd=ROOT)
        assert inspect_result.returncode == 0

        summary = read_json(SUMMARY_OUT)
        inspection = read_json(INSPECTION_OUT)
        logged_totals = compute_log_partner_totals()

        assert inspection["partners"] == summary["partners"] == logged_totals
        for partner in PARTNERS:
            assert abs(logged_totals[partner]["total"] - expected_partner_totals[partner]["total"]) <= 0.01
            assert logged_totals[partner]["transactionCount"] == expected_partner_totals[partner]["transactionCount"]


def test_reversed_partner_order_produces_same_output():
    # Spec: a fresh-process reversed ordering still produces the same canonical daily rollup.
    expected_rollup = rollup_from_partner_eod(PARTNER_EOD_DIR)

    with mock_servers():
        result = run_rollup(partner_order="delta,beta,gamma,alpha")
        assert result.returncode == 0
        assert_rollup_matches_expected(expected_rollup)


def test_two_consecutive_runs_in_same_process_produce_the_same_correct_output():
    # Spec: same-process replays cannot leak a stale compiled resolver between partner orders.
    expected_rollup = rollup_from_partner_eod(PARTNER_EOD_DIR)

    with mock_servers():
        result, payload = run_same_process(
            [
                {"partnerOrder": ["beta", "delta", "gamma", "alpha"]},
                {"partnerOrder": ["delta", "beta", "gamma", "alpha"]},
            ]
        )
        assert result.returncode == 0
        assert payload is not None
        assert payload[0] == expected_rollup
        assert payload[1] == expected_rollup


def test_repeat_runs_without_restart_are_deterministic():
    # Spec: repeating the same clean run without restarting services remains deterministic.
    with mock_servers():
        run_rollup()
        first = canonical_json_bytes(ROLLUP_OUT)
        clean_outputs()
        run_rollup()
        second = canonical_json_bytes(ROLLUP_OUT)
        assert first == second


def test_partner_isolated_runs_match_each_partner_report():
    # Spec: each partner reconciles correctly on its own, so mixed-run failure cannot be masked by compensation.
    base_registry = read_json(REGISTRY)

    with mock_servers():
        for partner in PARTNERS:
            isolated_registry = {
                "businessDate": base_registry["businessDate"],
                "partners": [
                    {**entry, "enabled": entry["id"] == partner}
                    for entry in base_registry["partners"]
                ],
            }
            registry_path = write_temp_registry(isolated_registry)
            try:
                clean_outputs()
                result = run_rollup(registry_path=registry_path)
                assert result.returncode == 0
                assert_rollup_matches_expected(read_json(PARTNER_EOD_DIR / f"{partner}.json")["accounts"])
            finally:
                registry_path.unlink(missing_ok=True)


def test_held_out_boundary_fixture_generalizes():
    # Spec: the fix must generalize to a hidden fixture variant with different account mixes and path combinations.
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        current_root, registry_path, expected_root, expected_events = build_held_out_fixture(temp_root)
        expected_rollup = rollup_from_partner_eod(expected_root)

        with mock_servers(current_root):
            result = run_rollup(registry_path=registry_path, diagnostics=True)
            assert result.returncode == 0
            assert_rollup_matches_expected(expected_rollup)
            assert logged_event_tuples() == expected_event_tuples(expected_events)


def test_registry_mutation_changes_output_when_zone_or_cutoff_changes():
    # Spec: the rollup must actually use the registry settlement metadata instead of hardcoded or stale resolver state.
    mutated_registry = read_json(REGISTRY)
    for partner in mutated_registry["partners"]:
        if partner["id"] == "delta":
            partner["settlement"]["cutoffLocal"] = "00:00"
            break

    registry_path = write_temp_registry(mutated_registry)
    try:
        expected_events = authoritative_events(CURRENT_FIXTURES, registry_path)
        expected_rollup = rollup_from_events(expected_events)

        with mock_servers():
            result = run_rollup(registry_path=registry_path)
            assert result.returncode == 0
            assert_rollup_matches_expected(expected_rollup)
            assert logged_event_tuples() == expected_event_tuples(expected_events)
            assert read_json(ROLLUP_OUT) != rollup_from_partner_eod(PARTNER_EOD_DIR)
    finally:
        registry_path.unlink(missing_ok=True)


def test_validation_errors_still_raise_for_malformed_inputs():
    # Spec: malformed verifier-injected events must still fail through the existing validation path.
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        current_dir = temp_root / "current" / "partner-events"
        shutil.copytree(CURRENT_FIXTURES, current_dir)

        gamma_payload = read_json(current_dir / "gamma.json")
        gamma_payload["events"][0]["payload"]["accountRef"] = ""
        write_json(current_dir / "gamma.json", gamma_payload)

        with mock_servers(temp_root / "current"):
            result = run_rollup(check=False)
            assert result.returncode != 0
            assert "validation_failed" in LOG_PATH.read_text(encoding="utf-8")


def test_integrity_constraints_and_runtime_flags_remain_unchanged():
    # Spec: the agent cannot pass by editing fixtures, expected partner reports, helper surfaces, or runtime flags.
    for relative_path, expected_hash in ROOT_HASHES.items():
        assert sha256(ROOT / relative_path) == expected_hash
    for absolute_path, expected_hash in SCRIPT_HASHES.items():
        assert sha256(Path(absolute_path)) == expected_hash

    package_json = read_json(PACKAGE_JSON)
    assert package_json["engines"] == {"node": "20.x"}
    assert "--max-old-space-size" not in PACKAGE_JSON.read_text(encoding="utf-8")
    assert "NODE_OPTIONS" not in Path("/usr/local/bin/run-rollup-job").read_text(encoding="utf-8")

def test_same_process_registry_config_change_rebuilds_compiled_context():
    # Spec: resolver cache must be keyed by effective resolver inputs, not only partner id/profile.
    # This catches shallow fixes like `resolverCacheKey = partner.id`.
    mutated_registry = read_json(REGISTRY)
    for partner in mutated_registry["partners"]:
        if partner["id"] == "delta":
            partner["settlement"]["cutoffLocal"] = "00:00"
            break

    registry_path = write_temp_registry(mutated_registry)
    try:
        expected_first = rollup_from_partner_eod(PARTNER_EOD_DIR)
        expected_second = rollup_from_events(authoritative_events(CURRENT_FIXTURES, registry_path))

        assert expected_second != expected_first

        with mock_servers():
            result, payload = run_same_process(
                [
                    {},
                    {"registryPath": str(registry_path)},
                ]
            )

            assert result.returncode == 0, result.stdout + result.stderr
            assert payload is not None
            assert payload[0] == expected_first
            assert payload[1] == expected_second
    finally:
        registry_path.unlink(missing_ok=True)


def test_same_process_event_id_path_change_rebuilds_compiled_context():
    # Spec: resolver cache must include event-id reader inputs, not only partner id/profile/settlement.
    # This catches fixes that key the cache too shallowly while still passing visible totals.
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        current_dir = temp_root / "current" / "partner-events"
        shutil.copytree(CURRENT_FIXTURES, current_dir)

        delta_payload = read_json(current_dir / "delta.json")

        for event in delta_payload["events"]:
            event.setdefault("mirror", {})
            event["mirror"]["eventId"] = event["eventId"]

        delta_payload["events"][0]["mirror"]["accountRef"] = "acct-860"
        delta_payload["events"][0]["mirror"]["eventId"] = "delta-mirror-dupe"
        delta_payload["events"][3]["mirror"]["accountRef"] = "acct-860"
        delta_payload["events"][3]["mirror"]["eventId"] = "delta-mirror-dupe"

        write_json(current_dir / "delta.json", delta_payload)

        registry_payload = read_json(REGISTRY)
        for partner in registry_payload["partners"]:
            if partner["id"] == "delta":
                partner["eventIdPath"] = "mirror.eventId"
                break

        registry_path = write_temp_registry(registry_payload)

        try:
            default_fixture_expected = rollup_from_events(
                authoritative_events(current_dir, REGISTRY)
            )
            mutated_expected = rollup_from_events_with_dedupe(
                authoritative_events(current_dir, registry_path)
            )

            assert mutated_expected != default_fixture_expected

            with mock_servers(temp_root / "current"):
                result, payload = run_same_process(
                    [
                        {},
                        {"registryPath": str(registry_path)},
                    ]
                )

                assert result.returncode == 0, result.stdout + result.stderr
                assert payload is not None
                assert payload[0] == default_fixture_expected
                assert payload[1] == mutated_expected
        finally:
            registry_path.unlink(missing_ok=True)
