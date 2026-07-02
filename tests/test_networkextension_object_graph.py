from __future__ import annotations

import json
import plistlib
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def snapshot_with_launchservices() -> Snapshot:
    return Snapshot(
        host="object-graph-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "entries": [
                        {
                            "raw_block": "Google Chrome com.google.Chrome",
                            "bundle_id": "com.google.Chrome",
                            "identifier": "com.google.Chrome",
                            "canonical_id": "com.google.Chrome",
                            "name": "Google Chrome",
                            "display_name": "Google Chrome",
                            "version": "149.0.1",
                            "display_version": "149.0.1",
                            "path": "/Applications/Google Chrome.app",
                            "path_clean": "/Applications/Google Chrome.app",
                            "path_exists": False,
                            "executable": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                            "team_id": "EQHXZ8M8AV",
                            "classification": "STALE",
                            "fields": {"application_uuid": "11111111-1111-1111-1111-111111111111"},
                        }
                    ]
                },
            ),
        ],
    )


def write_object_graph_fixture(root: Path) -> Path:
    prefs = root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    archive = {
        "$archiver": "NSKeyedArchiver",
        "$version": 100000,
        "$top": {"root": plistlib.UID(1)},
        "$objects": [
            "$null",
            {"LocalNetworkPolicies": plistlib.UID(2), "HistoricalCache": plistlib.UID(7)},
            [plistlib.UID(3), plistlib.UID(9)],
            {"PolicyRecord": plistlib.UID(4), "DisplayName": "Google Chrome"},
            {"Client": plistlib.UID(5), "PolicyDecision": "allow", "SiblingMarker": "policy-neighbor"},
            {"bundleID": "com.google.Chrome", "CodeSign": plistlib.UID(6), "Path": plistlib.UID(8)},
            "com.google.Chrome.code_sign_clone",
            {"SerializedBlob": "legacy archive blob mentions com.google.Chrome.code_sign_clone and Chromium only"},
            "/Applications/Google Chrome.app.bundle/Contents/MacOS/Google Chrome",
            {"ClientIdentity": {"BundleIdentifier": "com.google.Chrome", "Path With Spaces": "/Applications/Google Chrome.app"}},
        ],
    }
    with (prefs / "com.apple.networkextension.plist").open("wb") as handle:
        plistlib.dump(archive, handle, fmt=plistlib.FMT_BINARY, sort_keys=True)
    (prefs / "com.apple.networkextension.partial.plist").write_bytes(b"not a plist \x00 com.google.Chrome.code_sign_clone")
    return root


def test_networkextension_object_graph_json_decodes_uid_relationships_and_context(tmp_path):
    root = write_object_graph_fixture(tmp_path / "ne")

    first = CliRunner().invoke(app, ["networkextension", "object-graph", "--root", str(root), "--json"])
    second = CliRunner().invoke(app, ["networkextension", "object-graph", "--root", str(root), "--json"])

    assert first.exit_code == 0
    assert json.loads(first.stdout) == json.loads(second.stdout)
    payload = json.loads(first.stdout)
    assert list(payload)[:8] == [
        "command",
        "object_graph_id",
        "timestamp",
        "read_only",
        "mutation_performed",
        "summary",
        "references",
        "decoded_artifacts",
    ]
    assert payload["command"] == "networkextension object-graph"
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
    assert payload["summary"]["decoded_artifacts"] == 1
    assert payload["summary"]["referenced_objects"] >= 4
    assert payload["summary"]["malformed_artifacts"] == 1

    refs = payload["references"]
    clone = next(item for item in refs if item["matched_token"] == "com.google.Chrome.code_sign_clone" and item["object_index"] == 6)
    assert clone["artifact"] == "com.apple.networkextension.plist"
    assert clone["object_reference"] == "$objects[6]"
    assert clone["value_type"] == "str"
    assert clone["parent_chain"] == ["$objects[1]", "$objects[2]", "$objects[3]", "$objects[4]", "$objects[5]"]
    assert "$objects[5].CodeSign" in clone["key_path"]
    assert clone["nearest_dictionary_keys"] == ["CodeSign", "Path", "bundleID"]
    assert 8 in clone["neighboring_object_indices"]
    assert clone["binding_classification"] == "client_identity_candidate"
    assert clone["safety_classification"] == "potential_future_repair_candidate"
    assert "object graph context" in clone["explanation"]

    cache = next(item for item in refs if item["binding_classification"] == "cache_or_blob_reference")
    assert cache["safety_classification"] in {"inspect_only", "not_actionable"}
    assert "deletable" not in cache["explanation"].lower()

    path_ref = next(item for item in refs if ".app.bundle/Contents/MacOS/Google Chrome" in item["matched_token"])
    assert path_ref["reference_category"] == "chrome_path"
    assert "Path With Spaces" in json.dumps(refs)


def test_networkextension_object_graph_human_output_is_read_only(tmp_path):
    root = write_object_graph_fixture(tmp_path / "ne")

    result = CliRunner().invoke(app, ["networkextension", "object-graph", "--root", str(root)])

    assert result.exit_code == 0
    assert "NetworkExtension object graph" in result.stdout
    assert "Read-only: true" in result.stdout
    assert "Mutation performed: false" in result.stdout
    assert "client_identity_candidate" in result.stdout
    assert "cache_or_blob_reference" in result.stdout
    forbidden = ["defaults write", "defaults delete", "lsregister", "killall", "rm ", "repair", "reset"]
    lowered = result.stdout.lower()
    for token in forbidden:
        assert token not in lowered


def test_local_network_report_and_bundle_include_object_graph(monkeypatch, tmp_path):
    root = write_object_graph_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [root])
    report = build_local_network_report(snapshot_with_launchservices())

    payload = report.to_json_dict()
    assert payload["networkextension_object_graph_summary"]["decoded_artifacts"] == 1
    assert "NetworkExtension object graph" in report.render_text()

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-object-graph.json").exists()
    assert (bundle / "networkextension-object-graph.txt").exists()
    artifact = json.loads((bundle / "networkextension-object-graph.json").read_text())
    assert artifact["summary"]["client_identity_candidates"] >= 1


def test_bundle_diff_includes_networkextension_object_graph_diff(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "evidence": [],
                "networkextension_object_graph_summary": {
                    "decoded_artifacts": 1,
                    "referenced_object_indices": ["com.apple.networkextension.plist:$objects[6]"],
                    "binding_classifications": {"cache_or_blob_reference": 1},
                    "safety_classifications": {"inspect_only": 1},
                    "parent_chain_summaries": ["$objects[1] > $objects[7]"],
                },
            },
            sort_keys=True,
        )
    )
    (after / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "evidence": [],
                "networkextension_object_graph_summary": {
                    "decoded_artifacts": 2,
                    "referenced_object_indices": ["com.apple.networkextension.plist:$objects[6]", "com.apple.networkextension.plist:$objects[9]"],
                    "binding_classifications": {"client_identity_candidate": 1},
                    "safety_classifications": {"potential_future_repair_candidate": 1},
                    "parent_chain_summaries": ["$objects[1] > $objects[2] > $objects[3] > $objects[4] > $objects[5]"],
                },
            },
            sort_keys=True,
        )
    )

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["networkextension_object_graph_diff"] == {
        "added_decoded_artifacts": 1,
        "removed_decoded_artifacts": 0,
        "added_referenced_object_indices": ["com.apple.networkextension.plist:$objects[9]"],
        "removed_referenced_object_indices": [],
        "changed_binding_classifications": ["cache_or_blob_reference", "client_identity_candidate"],
        "changed_safety_classifications": ["inspect_only", "potential_future_repair_candidate"],
        "changed_parent_chain_summaries": [
            "$objects[1] > $objects[2] > $objects[3] > $objects[4] > $objects[5]",
            "$objects[1] > $objects[7]",
        ],
    }

    text = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Object Graph Diff" in text
    assert "Added referenced object indices: com.apple.networkextension.plist:$objects[9]" in text
