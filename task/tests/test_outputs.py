import hashlib
import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest


ROOT = Path("/workspace/rollup")
REGISTRY = ROOT / "config" / "partner-registry.json"
ROLLUP_OUT = ROOT / "out" / "daily-rollup.json"
SUMMARY_OUT = ROOT / "out" / "daily-summary.json"
DIAGNOSTICS_OUT = ROOT / "out" / "diagnostics.json"
LOG_PATH = ROOT / "logs" / "rollup.log"
PACKAGE_JSON = ROOT / "package.json"

PARTNERS = ("p01", "p02", "p03", "p04", "p05")
DATES = ("2026-05-04", "2026-05-05", "2026-05-06", "2028-11-17")

ROOT_HASHES = {
    "README.md": "2e253a65cb5a49a08893ccd926095e7c5aa61c87281c146e03cc460d533c5798",
    "package.json": "a2399b7d4fde29b135d758df507ff11455d0b282515766fd99ed634b0679dec9",
    "package-lock.json": "016f992727175f41ce58c8f69ffa4125a59f64f326278b0a75c92b29fcfda02b",
    "config/partner-registry.json": "4664e583442040403a111b965c15d2b66976bfc7e0207e483b06b31158a9a0d8",
    "bin/partner-service": "e94bd33120b5f858c889d274d8560a7666b41e2b1239e42a9932b4e4b4b452e2",
}

SCRIPT_HASHES = {
    "/usr/local/bin/reset-rollup-runtime": "3239e6f81041817e48a99a8c789c63d8818d6a65d84cb54eed6a7e024c94250a",
    "/usr/local/bin/start-partner-services": "d0ab642191a7364b262a2ce359dd7c2635bd2fa29392ab95aa20af77481a9b30",
    "/usr/local/bin/stop-partner-services": "f27db74b160ae8f04d9a8a42399c6875a184b9a28c185de4c373e8b690156bf7",
    "/usr/local/bin/run-rollup": "8ca0e63159f2fd6f9773e567ee3d8506861617d1da00a29d17ed1e8164d55479",
}

ALLOWED_REGISTRY_KEYS = {
    "partnerId",
    "enabled",
    "baseUrl",
    "eventsPath",
    "reportPath",
    "currency",
    "accountField",
    "amountField",
    "timestampField",
    "referenceField",
    "settlementCutoff",
}

BANNED_PUBLIC_TERMS = (
    "identity",
    "posting",
    "sequence",
    "dedupe",
    "de_dupe",
    "occurrence",
    "ledger",
    "clearing",
    "wire",
    "unique key",
    "event key",
    "retry detection",
    "duplicate detection",
    "duplicate",
    "retry",
    "idempotency",
    "idempotent",
    "canonical",
    "fingerprint",
    "collapse",
    "suppress",
    "same transaction",
    "transport metadata",
    "replay",
)

FORBIDDEN_ROUTES = (
    "/debug",
    "/seed",
    "/schema",
    "/dump",
    "/raw",
    "/explain",
    "/fixtures",
    "/expected",
    "/admin",
    "/internal",
    "/list",
    "/config",
)


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


def fetch_json(url: str):
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def clean_outputs():
    shutil.rmtree(ROOT / "out", ignore_errors=True)
    shutil.rmtree(ROOT / "logs", ignore_errors=True)
    (ROOT / "out").mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)


@contextmanager
def partner_services():
    run(["/usr/local/bin/reset-rollup-runtime"])
    run(["/usr/local/bin/start-partner-services"])
    try:
        yield
    finally:
        run(["/usr/local/bin/stop-partner-services"])


def registry_partners():
    return read_json(REGISTRY)["partners"]


def by_partner():
    return {partner["partnerId"]: partner for partner in registry_partners()}


def run_rollup(date: str, *, check=True):
    clean_outputs()
    return run(
        ["/usr/local/bin/run-rollup", "--business-date", date, "--diagnostics"],
        check=check,
    )


def metrics_for(partner):
    return fetch_json(f"{partner['baseUrl']}/metrics")[partner["partnerId"]]


def report_for(partner, date: str):
    url = f"{partner['baseUrl']}{partner['reportPath']}?businessDate={date}"
    return fetch_json(url)


def merge_reports(date: str):
    merged = {}
    partner_totals = {}
    for partner in registry_partners():
        payload = report_for(partner, date)
        partner_total = 0.0
        partner_count = 0
        for row in payload["accounts"]:
            account = row["account"]
            amount = round(float(row["total"]), 2)
            count = int(row["count"])
            entry = merged.setdefault(
                account,
                {"total": 0.0, "count": 0, "currency": payload["currency"]},
            )
            entry["total"] = round(entry["total"] + amount, 2)
            entry["count"] += count
            partner_total = round(partner_total + amount, 2)
            partner_count += count
        partner_totals[partner["partnerId"]] = {
            "total": round(partner_total, 2),
            "count": partner_count,
        }
    return {account: merged[account] for account in sorted(merged)}, partner_totals


def assert_rollup_matches(expected_rollup):
    actual = read_json(ROLLUP_OUT)
    assert set(actual) == set(expected_rollup)
    for account, expected in expected_rollup.items():
        got = actual[account]
        assert set(got) == {"total", "count", "currency"}
        assert isinstance(got["total"], (int, float))
        assert not isinstance(got["total"], bool)
        assert abs(got["total"] - expected["total"]) <= 0.01
        assert got["count"] == expected["count"]
        assert got["currency"] == expected["currency"]


def totals_from_rollup(expected_rollup):
    return {
        "accountCount": len(expected_rollup),
        "count": sum(entry["count"] for entry in expected_rollup.values()),
        "total": round(sum(entry["total"] for entry in expected_rollup.values()), 2),
    }


def assert_summary_matches(summary, date, expected_rollup, expected_partner_totals):
    expected = totals_from_rollup(expected_rollup)
    assert summary["businessDate"] == date
    assert summary["accountCount"] == expected["accountCount"]
    assert summary["count"] == expected["count"]
    assert abs(summary["total"] - expected["total"]) <= 0.01
    assert summary["partners"] == expected_partner_totals


def assert_diagnostics_consistent(diagnostics, date, expected_partner_totals):
    assert diagnostics["businessDate"] == date
    assert diagnostics["acceptedEvents"] == sum(item["count"] for item in expected_partner_totals.values())
    assert diagnostics["skippedEvents"] == sum(diagnostics["perPartnerSkipped"].values())
    assert diagnostics["perPartnerAccepted"] == {
        partner: value["count"]
        for partner, value in expected_partner_totals.items()
    }
    for partner in PARTNERS:
        assert diagnostics["fetchedCounts"][partner] >= diagnostics["retainedCounts"][partner]
        assert diagnostics["retainedCounts"][partner] == (
            diagnostics["perPartnerAccepted"].get(partner, 0)
            + diagnostics["perPartnerSkipped"].get(partner, 0)
        )


def assert_no_report_calls_before_grader(date: str):
    for partner in registry_partners():
        metrics = metrics_for(partner)
        assert metrics["events"].get(date, 0) >= 1
        assert metrics["reports"].get(date, 0) == 0


def protected_public_files():
    roots = [
        ROOT / "README.md",
        ROOT / "package.json",
        REGISTRY,
        Path("/usr/local/bin/reset-rollup-runtime"),
        Path("/usr/local/bin/start-partner-services"),
        Path("/usr/local/bin/stop-partner-services"),
        Path("/usr/local/bin/run-rollup"),
    ]
    files = []
    for root in roots:
        if root.is_dir():
            files.extend(path for path in root.rglob("*") if path.is_file())
        else:
            files.append(root)
    return files


def public_text_for_audit():
    items = []
    for path in protected_public_files():
        items.append((str(path), path.read_text(encoding="utf-8", errors="ignore")))
    for path in [ROOT / "fixtures", ROOT / "mock", ROOT / "tools"]:
        if path.exists():
            items.append((str(path), str(path)))
    return items


@pytest.fixture(scope="session", autouse=True)
def npm_ci():
    result = run(["npm", "ci"], cwd=ROOT)
    assert result.returncode == 0


def test_public_bundle_has_no_readable_answer_sources_or_obvious_leaks():
    assert not (ROOT / "fixtures").exists()
    assert not (ROOT / "mock").exists()
    assert not (ROOT / "tools").exists()

    for partner in registry_partners():
        assert set(partner) == ALLOWED_REGISTRY_KEYS
        assert partner["partnerId"] in PARTNERS

    for label, text in public_text_for_audit():
        lowered = text.lower()
        for term in BANNED_PUBLIC_TERMS:
            assert term not in lowered, f"{term!r} leaked in {label}"

    for path in ROOT.rglob("*"):
        lowered = str(path.relative_to(ROOT)).lower()
        for term in ("fixture", "mock", "expected"):
            assert term not in lowered


def test_partner_service_routes_are_sealed():
    binary_info = run(["file", str(ROOT / "bin" / "partner-service")])
    assert "ELF" in binary_info.stdout
    assert "stripped" in binary_info.stdout

    with partner_services():
        for partner in registry_partners():
            assert fetch_json(f"{partner['baseUrl']}/health") == {"ok": True}
            for route in FORBIDDEN_ROUTES:
                try:
                    fetch_json(f"{partner['baseUrl']}{route}")
                except HTTPError as error:
                    assert error.code == 404
                else:
                    raise AssertionError(f"route unexpectedly exists: {route}")


def test_rollup_reconciles_to_runtime_eod_reports_for_hidden_dates():
    for date in DATES:
        with partner_services():
            result = run_rollup(date)
            assert result.returncode == 0, result.stdout + result.stderr
            assert_no_report_calls_before_grader(date)
            expected_rollup, expected_partner_totals = merge_reports(date)
            assert_rollup_matches(expected_rollup)

            summary = read_json(SUMMARY_OUT)
            diagnostics = read_json(DIAGNOSTICS_OUT)
            assert_summary_matches(summary, date, expected_rollup, expected_partner_totals)
            assert_diagnostics_consistent(diagnostics, date, expected_partner_totals)


def test_logs_remain_present_and_neutral():
    date = DATES[1]
    with partner_services():
        run_rollup(date)
        assert_no_report_calls_before_grader(date)

        lines = [
            json.loads(line)
            for line in LOG_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        names = {line.get("event") for line in lines}
        assert "acceptedEvent" in names
        assert "skippedEvent" in names

        allowed = {"ts", "event", "partnerId", "businessDate", "account", "amount", "timestamp", "reference"}
        for line in lines:
            if line.get("event") in {"acceptedEvent", "skippedEvent"}:
                assert set(line) == allowed


def test_source_does_not_fetch_eod_reports_during_production_run():
    production_paths = [
        path for path in (ROOT / "src").glob("*.mjs")
        if path.name != "registry.mjs"
    ]
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in production_paths)
    assert "reportPath" not in source_text
    assert "/reports/eod" not in source_text


def test_same_reference_detail_handling_generalizes_beyond_sampled_dates():
    script = """
import { applyEvents } from "./src/aggregation.mjs";

const calls = [];
const logger = {
  accepted(event) {
    calls.push(["accepted", event.reference, event.amount, event.source?.detail?.mode, event.source?.detail?.slot]);
  },
  skipped(event) {
    calls.push(["skipped", event.reference, event.amount, event.source?.detail?.mode, event.source?.detail?.slot]);
  }
};

function event(slot, amount) {
  return {
    partnerId: "p01",
    account: "A-general",
    amount,
    currency: "USD",
    timestamp: "2029-02-03T12:00:00Z",
    reference: "R-general",
    businessDate: "2029-02-03",
    source: {
      detail: {
        mode: "A",
        slot
      }
    }
  };
}

const result = applyEvents([
  event("1", 10),
  event("2", 5),
  event("2", 5)
], logger);

const account = result.rollup["A-general"];
if (!account || account.total !== 15 || account.count !== 2) {
  console.error(JSON.stringify({ result, calls }, null, 2));
  process.exit(1);
}
if (result.diagnostics.acceptedEvents !== 2 || result.diagnostics.skippedEvents !== 1) {
  console.error(JSON.stringify({ diagnostics: result.diagnostics, calls }, null, 2));
  process.exit(2);
}
"""
    result = run(["node", "--input-type=module", "-e", script], cwd=ROOT, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_validation_still_rejects_malformed_required_fields():
    script = """
import { validateNormalizedEvent } from "./src/validation.mjs";
try {
  validateNormalizedEvent({
    partnerId: "p01",
    account: "A-1000",
    amount: 12.3,
    currency: "USD",
    timestamp: "2026-05-06T12:00:00Z",
    reference: "",
    businessDate: "2026-05-06"
  });
  process.exit(1);
} catch (error) {
  if (!String(error.message).includes("validation_failed")) {
    process.exit(2);
  }
}
"""
    result = run(["node", "--input-type=module", "-e", script], cwd=ROOT, check=False)
    assert result.returncode == 0


def test_integrity_constraints_and_runtime_flags_remain_unchanged():
    for relative_path, expected_hash in ROOT_HASHES.items():
        assert sha256(ROOT / relative_path) == expected_hash
    for absolute_path, expected_hash in SCRIPT_HASHES.items():
        assert sha256(Path(absolute_path)) == expected_hash

    package_json = read_json(PACKAGE_JSON)
    assert package_json["engines"] == {"node": "20.x"}
    assert "--max-old-space-size" not in PACKAGE_JSON.read_text(encoding="utf-8")
    assert "NODE_OPTIONS" not in Path("/usr/local/bin/run-rollup").read_text(encoding="utf-8")


def test_required_evidence_artifact_exists():
    evidence = ROOT / "diagnosis" / "evidence.json"
    assert evidence.exists()
    payload = read_json(evidence)
    assert set(payload) >= {
        "sampledBusinessDates",
        "sampledPartners",
        "reportComparisons",
        "rawEventLogComparisons",
        "rejectedHypotheses",
        "productionReportEndpointCalls",
    }
    assert len(payload["sampledBusinessDates"]) >= 3
    assert len(payload["sampledPartners"]) >= 2
    assert len(payload["reportComparisons"]) >= 3
    assert len(payload["rawEventLogComparisons"]) >= 1
    assert len(payload["rejectedHypotheses"]) >= 2
    assert payload.get("productionReportEndpointCalls") == 0
