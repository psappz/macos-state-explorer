from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.launchservices.generations import GenerationClassification, analyze_generations
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from macos_state_explorer.launchservices.remediation_plan import (
    RemediationSafety,
    plan_launchservices_remediation,
    render_remediation_plan,
)


def record(
    path: str,
    *,
    bundle_id: str,
    name: str,
    version: str | None,
    path_exists: bool | None = False,
    volume: str | None = "/",
    volume_exists: bool | None = True,
    classification: LaunchServicesStatus = LaunchServicesStatus.STALE,
) -> LaunchServicesRecord:
    return LaunchServicesRecord(
        raw_block=f"path: {path}",
        bundle_id=bundle_id,
        name=name,
        display_name=name,
        version=version,
        display_version=version,
        path=path,
        path_clean=path,
        path_exists=path_exists,
        volume=volume,
        volume_exists=volume_exists,
        classification=classification,
    )


def planning_records() -> list[LaunchServicesRecord]:
    return [
        record(
            "/Applications/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.250",
            path_exists=True,
            classification=LaunchServicesStatus.ACTIVE,
        ),
        record(
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.7778.216/Helpers/Google Chrome Helper.app",
            bundle_id="com.google.Chrome.helper",
            name="Google Chrome Helper",
            version="148.0.7778.216",
        ),
        record(
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.7778.216/Helpers/Google Chrome Helper (Renderer).app",
            bundle_id="com.google.Chrome.helper.renderer",
            name="Google Chrome Helper (Renderer)",
            version="148.0.7778.216",
        ),
        record(
            "/Volumes/Google Chrome/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.201",
            volume="/Volumes/Google Chrome",
            volume_exists=True,
        ),
        record(
            "/Users/patrick/.Trash/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.201",
            path_exists=True,
        ),
        record(
            "/Applications/GoogleUpdater.app",
            bundle_id="com.google.GoogleUpdater",
            name="GoogleUpdater",
            version="2.0",
            path_exists=True,
            classification=LaunchServicesStatus.ACTIVE,
        ),
        record(
            "/Applications/GoogleUpdater.app/Contents/Helpers/GoogleUpdater Helper.app",
            bundle_id="com.google.GoogleUpdater.helper",
            name="GoogleUpdater Helper",
            version="1.0",
        ),
        record(
            "/Applications/Google Home.app",
            bundle_id="com.google.GoogleHome",
            name="Google Home",
            version="4.0",
            path_exists=True,
            classification=LaunchServicesStatus.ACTIVE,
        ),
        record(
            "/Users/patrick/Library/Developer/CoreSimulator/Devices/IOSPlaceholder/YouTube.app",
            bundle_id="com.google.ios.youtube",
            name="YouTube",
            version="19.0",
            path_exists=True,
            classification=LaunchServicesStatus.ACTIVE,
        ),
        record(
            "/Applications/Google Chrome Mystery.app",
            bundle_id="com.google.Chrome.mystery",
            name="Mystery",
            version="1.0",
            path_exists=None,
            classification=LaunchServicesStatus.UNKNOWN,
        ),
    ]


def snapshot(records: list[LaunchServicesRecord]) -> Snapshot:
    return Snapshot(
        host="plan-host",
        created_at=123.0,
        observations=[
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "entries": [item.model_dump(mode="python") for item in records],
                    "stale_entries": [item.model_dump(mode="python") for item in records if item.classification != LaunchServicesStatus.ACTIVE],
                    "candidate_files": {"stdout": "/System/Library/LaunchServices/com.apple.LaunchServices.csstore\n"},
                },
            )
        ],
    )


def volume_regression_records() -> list[LaunchServicesRecord]:
    return [
        record(
            "/Applications/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.250",
            path_exists=True,
            classification=LaunchServicesStatus.ACTIVE,
        ),
        record(
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.7778.216/Helpers/Google Chrome Helper.app",
            bundle_id="com.google.Chrome.helper",
            name="Google Chrome Helper",
            version="148.0.7778.216",
        ),
        record(
            "/Volumes/Google Chrome/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.201",
            volume="/Volumes/Google Chrome",
            volume_exists=False,
        ),
        record(
            "/Volumes/Google Chrome/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/149.0.7827.201/Helpers/Google Chrome Helper.app",
            bundle_id="com.google.Chrome.helper",
            name="Google Chrome Helper",
            version="149.0.7827.201",
            volume="/Volumes/Google Chrome",
            volume_exists=False,
        ),
    ]


def test_product_detection_excludes_google_apps_and_ios_placeholders_from_chrome():
    analysis = analyze_generations(planning_records())
    families_by_name = {(generation.product_family, registration.name) for generation in analysis.generations for registration in generation.registrations}

    assert ("Google Chrome", "Google Home") not in families_by_name
    assert ("Google Chrome", "YouTube") not in families_by_name
    assert all("googlehome" not in (generation.bundle_identifier or "").lower() for generation in analysis.generations)


def test_google_updater_is_separate_from_chrome_active_generation():
    analysis = analyze_generations(planning_records())
    chrome_active = [generation for generation in analysis.generations if generation.product_family == "Google Chrome" and generation.classification == GenerationClassification.ACTIVE]
    updater_generations = [generation for generation in analysis.generations if generation.product_family == "GoogleUpdater"]

    assert len(chrome_active) == 1
    assert chrome_active[0].generation_id == "google-chrome:149.0.7827.250:applications-google-chrome-app"
    assert updater_generations
    assert all(generation.product_family != "Google Chrome" for generation in updater_generations)


def test_remediation_plan_steps_cover_obsolete_mounted_trash_and_stale_updater_generations():
    plan = plan_launchservices_remediation(analyze_generations(planning_records()))
    by_action = {step.action: step for step in plan.steps}

    assert by_action["plan_unregister_obsolete_generation"].product_family == "Google Chrome"
    assert by_action["plan_unregister_obsolete_generation"].safety == RemediationSafety.PLAN_ONLY_SAFE
    assert by_action["plan_review_mounted_installer_generation"].safety == RemediationSafety.MANUAL_REVIEW_REQUIRED
    assert by_action["plan_review_trash_generation"].safety == RemediationSafety.MANUAL_REVIEW_REQUIRED
    assert by_action["plan_review_stale_updater_generation"].product_family == "GoogleUpdater"
    assert all(step.executable is False for step in plan.steps)
    assert all(step.requires_confirmation is True for step in plan.steps)


def test_remediation_plan_never_selects_active_unknown_or_healthy_unrelated_entries():
    plan = plan_launchservices_remediation(analyze_generations(planning_records()))
    planned_registration_paths = {registration["path"] for step in plan.steps for registration in step.to_json_dict()["target_registrations"]}
    skipped_by_id = {generation["generation_id"]: generation for generation in plan.to_json_dict()["skipped_generations"]}

    assert "/Applications/Google Chrome.app" not in planned_registration_paths
    assert all("Mystery" not in registration["name"] for step in plan.steps for registration in step.to_json_dict()["target_registrations"])
    assert all("Google Home" not in registration["name"] for step in plan.steps for registration in step.to_json_dict()["target_registrations"])
    assert all("YouTube" not in registration["name"] for step in plan.steps for registration in step.to_json_dict()["target_registrations"])
    assert skipped_by_id["google-chrome:149.0.7827.250:applications-google-chrome-app"]["safety"] == "BLOCKED_ACTIVE_GENERATION"
    assert any(item["safety"] == "BLOCKED_UNKNOWN" for item in skipped_by_id.values())


def test_volume_generations_require_manual_review_even_when_classifier_marks_obsolete():
    analysis = analyze_generations(volume_regression_records())
    volume_generation = next(generation for generation in analysis.generations if (generation.installation_root or "").startswith("/Volumes/"))
    plan = plan_launchservices_remediation(analysis)
    steps_by_generation = {step.generation_id: step for step in plan.steps}

    assert volume_generation.classification == GenerationClassification.STALE
    assert steps_by_generation[volume_generation.generation_id].safety == RemediationSafety.MANUAL_REVIEW_REQUIRED
    assert steps_by_generation[volume_generation.generation_id].action == "plan_review_mounted_installer_generation"
    assert "volume" in steps_by_generation[volume_generation.generation_id].reason.lower()
    assert "installer" in steps_by_generation[volume_generation.generation_id].reason.lower()


def test_normal_obsolete_helper_remains_plan_only_safe_and_active_is_blocked():
    plan = plan_launchservices_remediation(analyze_generations(volume_regression_records()))
    steps_by_generation = {step.generation_id: step for step in plan.steps}
    skipped_by_generation = {generation["generation_id"]: generation for generation in plan.to_json_dict()["skipped_generations"]}

    assert steps_by_generation["google-chrome:148.0.7778.216:applications-google-chrome-app"].safety == RemediationSafety.PLAN_ONLY_SAFE
    assert skipped_by_generation["google-chrome:149.0.7827.250:applications-google-chrome-app"]["safety"] == "BLOCKED_ACTIVE_GENERATION"


def test_local_network_plan_summary_counts_nonexistent_volume_generation_as_manual_review(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(volume_regression_records()))
    result = CliRunner().invoke(app, ["solve", "local-network", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload)[:6] == ["command", "diagnosis", "evidence", "matched_rules", "repair_candidates", "next_action"]
    summary = payload["remediation_plan_summary"]
    chrome_summary = next(item for item in summary["product_summaries"] if item["product_family"] == "Google Chrome")
    assert chrome_summary["mounted_installer_generation_count"] == 1
    assert summary["safety_summary"]["MANUAL_REVIEW_REQUIRED"] == 1


def test_remediation_plan_json_schema_is_deterministic():
    payload = plan_launchservices_remediation(analyze_generations(planning_records())).to_json_dict()

    assert list(payload) == [
        "command",
        "plan_id",
        "created_at",
        "product_family",
        "active_generation",
        "candidate_generations",
        "skipped_generations",
        "safety_summary",
        "steps",
        "verification_commands",
        "warnings",
    ]
    assert payload["command"] == "launchservices plan"
    assert list(payload["steps"][0]) == [
        "step_id",
        "action",
        "product_family",
        "generation_id",
        "target_registrations",
        "reason",
        "safety",
        "executable",
        "requires_confirmation",
        "rollback",
        "expected_effect",
    ]


def test_remediation_plan_human_output_is_stable():
    output = render_remediation_plan(plan_launchservices_remediation(analyze_generations(planning_records())))

    assert output.startswith("LaunchServices remediation plan")
    assert "Product family: Google Chrome" in output
    assert "Active generation: 149.0.7827.250" in output
    assert "planned candidate generations" in output
    assert "manual review" in output
    assert "Executable in future: no" in output
    assert "No active generation is selected for cleanup" in output


def test_launchservices_plan_cli_json_and_human(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(planning_records()))
    runner = CliRunner()

    json_result = runner.invoke(app, ["launchservices", "plan", "--json"])
    human_result = runner.invoke(app, ["launchservices", "plan"])

    assert json_result.exit_code == 0
    assert json.loads(json_result.stdout)["command"] == "launchservices plan"
    assert human_result.exit_code == 0
    assert "LaunchServices remediation plan" in human_result.stdout


def test_launchservices_execute_plan_dry_run_uses_generation_planner_human_output(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(planning_records()))
    result = CliRunner().invoke(app, ["launchservices", "execute-plan", "--dry-run"])

    assert result.exit_code == 0
    assert "LaunchServices output: execute-plan" not in result.stdout
    assert "Stale entries:" not in result.stdout
    assert "LaunchServices execute-plan dry run" in result.stdout
    assert "Plan ID:" in result.stdout
    assert "dry_run: yes" in result.stdout
    assert "Product family: Chromium-family" in result.stdout
    assert "Active generation:" in result.stdout
    assert "Candidate generations" in result.stdout
    assert "Skipped generations" in result.stdout
    assert "Expected effect:" in result.stdout
    assert "Safety:" in result.stdout
    assert "Executable in future:" in result.stdout
    assert "Verification commands" in result.stdout
    assert "Warnings" in result.stdout
    assert "No commands were executed." in result.stdout
    assert "manual-review-only; not executable in dry run" in result.stdout
    assert "execution is not implemented yet" in result.stdout


def test_launchservices_execute_plan_dry_run_json_is_deterministic_and_non_mutating(monkeypatch, tmp_path):
    calls: list[bool] = []

    def fake_snapshot(fast: bool = False):
        calls.append(fast)
        return snapshot(planning_records())

    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", fake_snapshot)
    audit_log = tmp_path / "dry-run-audit.jsonl"
    result = CliRunner().invoke(app, ["launchservices", "execute-plan", "--dry-run", "--json", "--audit-log", str(audit_log)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload) == [
        "command",
        "plan_id",
        "dry_run",
        "commands_executed",
        "product_family",
        "active_generation",
        "candidate_generations",
        "skipped_generations",
        "safety_summary",
        "steps",
        "verification_commands",
        "warnings",
        "message",
    ]
    assert payload["command"] == "launchservices execute-plan"
    assert payload["dry_run"] is True
    assert payload["commands_executed"] == []
    assert payload["message"] == "No commands were executed. Dry-run only; LaunchServices mutation is not implemented."
    assert calls == [True]
    assert not (tmp_path / "execute-plan").exists()


def test_launchservices_execute_plan_dry_run_step_executability(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(planning_records()))
    result = CliRunner().invoke(app, ["launchservices", "execute-plan", "--dry-run", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    manual_steps = [step for step in payload["steps"] if step["safety"] == "MANUAL_REVIEW_REQUIRED"]
    plan_only_steps = [step for step in payload["steps"] if step["safety"] == "PLAN_ONLY_SAFE"]
    assert manual_steps
    assert plan_only_steps
    assert all(step["executable"] is False for step in manual_steps)
    assert all("manual-review-only" in step["execution_status"] for step in manual_steps)
    assert all(step["executable"] is False for step in plan_only_steps)
    assert all("execution is not implemented yet" in step["execution_status"] for step in plan_only_steps)


def test_launchservices_execute_plan_dry_run_writes_jsonl_audit(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(planning_records()))
    audit_log = tmp_path / "audit" / "launchservices.jsonl"

    result = CliRunner().invoke(app, ["launchservices", "execute-plan", "--dry-run", "--audit-log", str(audit_log)])

    assert result.exit_code == 0
    events = [json.loads(line) for line in audit_log.read_text().splitlines()]
    assert len(events) == 1
    assert list(events[0]) == ["event", "command", "plan_id", "dry_run", "commands_executed", "step_count", "safety_summary", "message"]
    assert events[0]["event"] == "launchservices_execute_plan_dry_run"
    assert events[0]["command"] == "launchservices execute-plan"
    assert events[0]["dry_run"] is True
    assert events[0]["commands_executed"] == []


def test_local_network_solution_and_report_include_additive_plan_summary(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(planning_records()))
    runner = CliRunner()

    solve_result = runner.invoke(app, ["solve", "local-network", "--json"])
    report_result = runner.invoke(app, ["report", "local-network", "--json"])

    assert solve_result.exit_code == 0
    solve_payload = json.loads(solve_result.stdout)
    assert list(solve_payload)[:6] == ["command", "diagnosis", "evidence", "matched_rules", "repair_candidates", "next_action"]
    assert "remediation_plan_summary" in solve_payload
    assert "No active generation is selected for cleanup" in solve_payload["remediation_plan_summary"]["warnings"]

    assert report_result.exit_code == 0
    report_payload = json.loads(report_result.stdout)
    assert list(report_payload)[:9] == ["command", "system_context", "trace", "diagnosis", "evidence", "matched_rules", "repair_candidates", "verification", "next_actions"]
    assert "remediation_plan_summary" in report_payload
    assert report_payload["remediation_plan_summary"]["product_summaries"][0]["product_family"] == "Google Chrome"


def test_local_network_human_output_includes_selective_plan_summary(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(planning_records()))
    result = CliRunner().invoke(app, ["solve", "local-network"])

    assert result.exit_code == 0
    assert "Selective LaunchServices remediation plan" in result.stdout
    assert "Google Chrome: 1 obsolete generation can be planned" in result.stdout
    assert "Google Chrome: 1 mounted installer generation requires manual review" in result.stdout
    assert "Google Chrome: 1 Trash generation requires manual review" in result.stdout
    assert "No active generation is selected for cleanup" in result.stdout


def test_internal_generation_planning_note_exists_and_explains_plan_only_scope():
    note = __import__("pathlib").Path("docs/LAUNCHSERVICES_REMEDIATION_PLANNING.md").read_text()

    assert "generation-based" in note
    assert "plan-only" in note
    assert "real-world plan validation" in note
