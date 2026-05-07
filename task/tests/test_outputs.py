import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
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

PARTNERS = ("alpha", "beta", "gamma", "delta", "epsilon")

ROOT_HASHES = {
    "config/partner-registry.json": "7ec93378659056a96e68ba4ff437db756e274654d809df3a357537008343cbcc",
    "fixtures/current/partner-events/alpha.json": "4d505ebb4972b5eeac64f3d15b588ef2c501ef26a189d8cba1c167f1e12c1a82",
    "fixtures/current/partner-events/beta.json": "c364cb98bb4bb5b7b203cf708cadff91a4c07f176d7b87768b27ddd5646c5b0c",
    "fixtures/current/partner-events/gamma.json": "af00079b137849084f48ca339a714bb05e913bac4f724115672289a5a8f7dd53",
    "fixtures/current/partner-events/delta.json": "53b84d954dbaddad43108852233cf09b7e86399a859c285be4b7b5a360c889de",
    "fixtures/current/partner-events/epsilon.json": "eec06828471cfbb3b4802ea584be147031ad1637406f31ad6c4146f9dba24b45",
    "fixtures/expected/partner-eod/alpha.json": "37f868957acbb35dc04ced4de5daa7d13511d7c90f2047a4f0ee21b99c8b917c",
    "fixtures/expected/partner-eod/beta.json": "623509602fcb04f030b9beebb38d4e9af9f37659d3885a1e5241d1dc318d5730",
    "fixtures/expected/partner-eod/gamma.json": "d2750fd1ac6b74da38fd40a1d829e23f2276b2153f85437768cfbecc2d7a1ded",
    "fixtures/expected/partner-eod/delta.json": "35480971f213c63f3647ee2a72230d154da5de349927278d8d674fa1fce46691",
    "fixtures/expected/partner-eod/epsilon.json": "3f295ecf9321738f7eeb60711ca6229d3d3b1dd918a8c1906746a8e4c4572cba",
    "package.json": "afbb2a1134511aca799685c28dcba19b702180fb0996d2b265fdb9ca0e427889",
    "tools/inspect-rollup.mjs": "37a7dd4302ab93f4540d0a22f239dc403c5f74251565ea028bcf91431e9aea79",
    "tools/print-raw-payloads.mjs": "28501cdcaefc1ba7dfbe25ea8467b5958d02f20430064003e45aa560ebed0e91",
}

SCRIPT_HASHES = {
    "/usr/local/bin/reset-rollup-runtime": "404432a3e56a3fcd45c6deb17fff1c3457795a387f93665ade7a821cd851ff27",
    "/usr/local/bin/start-rollup-mocks": "519506039cae9a0990adf3ff3331d9a794d4324011ab898df40cae54a632c64f",
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


def read_path(source, path_expression: str | None):
    if not path_expression:
        return None
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

    if partner_id == "gamma":
        amount = float(raw["entry"]["amountText"])
        if raw["entry"]["code"] == "refund":
            return round(-abs(amount), 2)
        if raw["entry"]["code"] == "zero":
            return 0.0
        return round(abs(amount), 2)

    amount = float(raw["posting"]["amountText"])
    if raw["posting"]["type"] in {"refund", "reversal"}:
        return round(-abs(amount), 2)
    if raw["posting"]["type"] == "zero":
        return 0.0
    return round(amount, 2)


def identity_key(event):
    parts = [event["partnerId"], event["eventId"]]
    if event["eventIdentity"] == "ledger-posting":
        parts.append(event["postingSequence"])
    return tuple(parts)


def deduped_events(events):
    seen = set()
    retained = []
    for event in events:
        key = identity_key(event)
        if key in seen:
            continue
        seen.add(key)
        retained.append(event)
    return retained


def authoritative_events(fixtures_root: Path, registry_path: Path):
    registry = read_json(registry_path)
    accepted = []

    for partner in sorted(
        (entry for entry in registry["partners"] if entry["enabled"]),
        key=lambda entry: entry["sortOrder"],
    ):
        payload = read_json(fixtures_root / f"{partner['id']}.json")
        event_identity = partner.get("eventIdentity", "stable-event")
        for raw in payload["events"]:
            event_ts = read_path(raw, partner["sourceTsPath"])
            canonical = {
                "partnerId": partner["id"],
                "eventIdentity": event_identity,
                "eventId": read_path(raw, partner.get("eventIdPath", "eventId")),
                "postingSequence": read_path(raw, partner.get("postingSequencePath")),
                "accountId": read_path(raw, partner["accountPath"]),
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

    return deduped_events(accepted)


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


def duplicate_lines():
    return [
        parse_log_fields(line)
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines()
        if "action=duplicate_skipped" in line
    ]


def logged_event_tuples():
    return sorted(
        (
            line["partner"],
            line["eventId"],
            line.get("postingSequence", ""),
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
            event.get("postingSequence") or "",
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


def write_expected_eod(expected_root: Path, events):
    by_partner = {partner: [] for partner in PARTNERS}
    for event in events:
        by_partner[event["partnerId"]].append(event)
    for partner, partner_events in by_partner.items():
        write_json(
            expected_root / f"{partner}.json",
            {"partner": partner, "accounts": rollup_from_events(partner_events)},
        )


def build_held_out_fixture(temp_root: Path):
    current_root = temp_root / "current"
    fixtures_root = current_root / "partner-events"
    expected_root = temp_root / "expected" / "partner-eod"
    registry_path = temp_root / "config" / "partner-registry.json"
    shutil.copytree(CURRENT_FIXTURES, fixtures_root)
    expected_root.mkdir(parents=True, exist_ok=True)
    registry = read_json(REGISTRY)
    write_json(registry_path, registry)

    epsilon_payload = read_json(fixtures_root / "epsilon.json")
    epsilon_payload["events"] = [
        {
            "ledger": {"id": "eps-hidden-10"},
            "account": {"id": "acct-h900"},
            "posting": {
                "sequence": "A",
                "postedAt": "2026-05-06T14:00:00Z",
                "type": "sale",
                "amountText": "20.00",
            },
            "currency": "USD",
        },
        {
            "ledger": {"id": "eps-hidden-10"},
            "account": {"id": "acct-h900"},
            "posting": {
                "sequence": "B",
                "postedAt": "2026-05-06T14:05:00Z",
                "type": "correction",
                "amountText": "-2.00",
            },
            "currency": "USD",
        },
        {
            "ledger": {"id": "eps-hidden-10"},
            "account": {"id": "acct-h900"},
            "posting": {
                "sequence": "B",
                "postedAt": "2026-05-06T14:05:05Z",
                "type": "correction",
                "amountText": "-2.00",
            },
            "currency": "USD",
        },
        {
            "ledger": {"id": "eps-hidden-20"},
            "account": {"id": "acct-h901"},
            "posting": {
                "sequence": "A",
                "postedAt": "2026-05-06T16:00:00Z",
                "type": "sale",
                "amountText": "11.00",
            },
            "currency": "USD",
        },
        {
            "ledger": {"id": "eps-hidden-20"},
            "account": {"id": "acct-h901"},
            "posting": {
                "sequence": "B",
                "postedAt": "2026-05-06T18:00:00Z",
                "type": "reversal",
                "amountText": "11.00",
            },
            "currency": "USD",
        },
        {
            "ledger": {"id": "eps-hidden-cut"},
            "account": {"id": "acct-h902"},
            "posting": {
                "sequence": "A",
                "postedAt": "2026-05-06T22:30:00Z",
                "type": "sale",
                "amountText": "4.00",
            },
            "currency": "USD",
        },
    ]
    write_json(fixtures_root / "epsilon.json", epsilon_payload)

    expected_events = authoritative_events(fixtures_root, registry_path)
    write_expected_eod(expected_root, expected_events)
    return current_root, registry_path, expected_root, expected_events


@pytest.fixture(scope="session", autouse=True)
def npm_ci():
    result = run(["npm", "ci"], cwd=ROOT)
    assert result.returncode == 0


def test_build_and_helper_scripts_work():
    help_result = run(["node", "src/index.mjs", "--help"], cwd=ROOT)
    assert "daily-account-rollup" in help_result.stdout

    with mock_servers():
        result = run_rollup()
        assert result.returncode == 0
        assert ROLLUP_OUT.exists()


def test_mixed_run_matches_visible_partner_reports_and_logs():
    expected_events = authoritative_events(CURRENT_FIXTURES, REGISTRY)
    expected_rollup = rollup_from_partner_eod(PARTNER_EOD_DIR)

    with mock_servers():
        result = run_rollup(diagnostics=True)
        assert result.returncode == 0
        assert_rollup_matches_expected(expected_rollup)

        diagnostics = read_json(DIAGNOSTICS_OUT)
        assert diagnostics["acceptedEvents"] == 27
        assert diagnostics["duplicateEvents"] == 5
        assert diagnostics["fetchedCounts"] == {
            "alpha": 7,
            "beta": 7,
            "gamma": 7,
            "delta": 7,
            "epsilon": 9,
        }
        assert diagnostics["retainedCounts"] == {
            "alpha": 6,
            "beta": 6,
            "gamma": 6,
            "delta": 6,
            "epsilon": 8,
        }
        assert diagnostics["perPartnerAccepted"] == {
            "alpha": 5,
            "beta": 5,
            "gamma": 5,
            "delta": 5,
            "epsilon": 7,
        }
        assert diagnostics["perPartnerDuplicates"] == {
            "alpha": 1,
            "beta": 1,
            "gamma": 1,
            "delta": 1,
            "epsilon": 1,
        }

        assert logged_event_tuples() == expected_event_tuples(expected_events)
        assert len(ingestion_lines()) == 27
        assert len(duplicate_lines()) == 5
        assert sum(1 for item in logged_event_tuples() if item[1] == "eps-ledger-100") == 2
        assert sum(1 for item in logged_event_tuples() if item[1] == "eps-ledger-200") == 2
        assert sum(1 for item in logged_event_tuples() if item[1] == "eps-ledger-500") == 2

        summary = read_json(SUMMARY_OUT)
        assert summary["transactionCount"] == 27
        assert abs(summary["grandTotal"] - 231.63) <= 0.01
        assert summary["partners"]["epsilon"] == {"total": 49.99, "transactionCount": 7}

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
    expected_rollup = rollup_from_partner_eod(PARTNER_EOD_DIR)

    with mock_servers():
        result = run_rollup(partner_order="epsilon,delta,beta,gamma,alpha")
        assert result.returncode == 0
        assert_rollup_matches_expected(expected_rollup)


def test_repeat_runs_without_restart_are_deterministic():
    with mock_servers():
        run_rollup()
        first = canonical_json_bytes(ROLLUP_OUT)
        clean_outputs()
        run_rollup()
        second = canonical_json_bytes(ROLLUP_OUT)
        assert first == second


def test_partner_isolated_runs_match_each_partner_report():
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


def test_held_out_ledger_posting_fixture_generalizes():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        current_root, registry_path, expected_root, expected_events = build_held_out_fixture(temp_root)
        expected_rollup = rollup_from_partner_eod(expected_root)

        with mock_servers(current_root):
            result = run_rollup(registry_path=registry_path, diagnostics=True)
            assert result.returncode == 0
            assert_rollup_matches_expected(expected_rollup)
            assert logged_event_tuples() == expected_event_tuples(expected_events)


def test_stable_event_partner_ignores_posting_sequence_metadata():
    registry_payload = read_json(REGISTRY)
    for partner in registry_payload["partners"]:
        if partner["id"] == "beta":
            partner["postingSequencePath"] = "posting.sequence"
            assert partner["eventIdentity"] == "stable-event"
            break

    registry_path = write_temp_registry(registry_payload)
    try:
        expected_events = authoritative_events(CURRENT_FIXTURES, registry_path)
        expected_rollup = rollup_from_events(expected_events)

        with mock_servers():
            result = run_rollup(registry_path=registry_path, diagnostics=True)
            assert result.returncode == 0
            assert_rollup_matches_expected(expected_rollup)
            assert read_json(DIAGNOSTICS_OUT)["perPartnerDuplicates"]["beta"] == 1
    finally:
        registry_path.unlink(missing_ok=True)


def test_registry_identity_mutation_changes_epsilon_dedupe_semantics():
    mutated_registry = read_json(REGISTRY)
    for partner in mutated_registry["partners"]:
        if partner["id"] == "epsilon":
            partner["eventIdentity"] = "stable-event"
            break

    registry_path = write_temp_registry(mutated_registry)
    try:
        expected_events = authoritative_events(CURRENT_FIXTURES, registry_path)
        expected_rollup = rollup_from_events(expected_events)
        assert expected_rollup != rollup_from_partner_eod(PARTNER_EOD_DIR)

        with mock_servers():
            result = run_rollup(registry_path=registry_path, diagnostics=True)
            assert result.returncode == 0
            assert_rollup_matches_expected(expected_rollup)
            assert read_json(DIAGNOSTICS_OUT)["perPartnerAccepted"]["epsilon"] == 3
    finally:
        registry_path.unlink(missing_ok=True)


def test_validation_errors_still_raise_for_malformed_inputs():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        current_dir = temp_root / "current" / "partner-events"
        shutil.copytree(CURRENT_FIXTURES, current_dir)

        epsilon_payload = read_json(current_dir / "epsilon.json")
        epsilon_payload["events"][0]["posting"]["sequence"] = ""
        write_json(current_dir / "epsilon.json", epsilon_payload)

        with mock_servers(temp_root / "current"):
            result = run_rollup(check=False)
            assert result.returncode != 0
            assert "validation_failed" in LOG_PATH.read_text(encoding="utf-8")


def test_integrity_constraints_and_runtime_flags_remain_unchanged():
    for relative_path, expected_hash in ROOT_HASHES.items():
        assert sha256(ROOT / relative_path) == expected_hash
    for absolute_path, expected_hash in SCRIPT_HASHES.items():
        assert sha256(Path(absolute_path)) == expected_hash

    package_json = read_json(PACKAGE_JSON)
    assert package_json["engines"] == {"node": "20.x"}
    assert "--max-old-space-size" not in PACKAGE_JSON.read_text(encoding="utf-8")
    assert "NODE_OPTIONS" not in Path("/usr/local/bin/run-rollup-job").read_text(encoding="utf-8")
