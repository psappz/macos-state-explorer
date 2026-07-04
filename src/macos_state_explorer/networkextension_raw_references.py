from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import plistlib
import re
from pathlib import Path
from typing import Any, Iterable

from macos_state_explorer.networkextension_state import default_networkextension_roots

CHROME_TOKEN_RE = re.compile(
    r"com\.google\.Chrome\.code_sign_clone|com\.google\.Chrome(?:\.[A-Za-z0-9_.-]+)?|/[^\s\"']*Google Chrome[^\s\"']*|LaunchServices|SecurityPrivacyExtension|Chromium|Chrome",
    re.IGNORECASE,
)
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
TEAM_ID_RE = re.compile(r"\b[A-Z0-9]{10}\b")
SENSITIVE_PATH_RE = re.compile(r"/Users/[^/\s\"']+")


@dataclass(frozen=True)
class NetworkExtensionRawReference:
    artifact_path: str
    artifact_label: str
    plist_key_path: str | None
    value_type: str
    matched_token: str
    surrounding_context: str
    reference_category: str
    binding_status: str
    safety_classification: str
    actionability_reason: str

    def sort_key(self) -> tuple[str, str, str, str]:
        return (self.artifact_path, self.plist_key_path or "", self.reference_category, self.matched_token)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "artifact_label": self.artifact_label,
            "plist_key_path": self.plist_key_path,
            "value_type": self.value_type,
            "matched_token": self.matched_token,
            "surrounding_context": self.surrounding_context,
            "reference_category": self.reference_category,
            "binding_status": self.binding_status,
            "safety_classification": self.safety_classification,
            "actionability_reason": self.actionability_reason,
        }


@dataclass(frozen=True)
class NetworkExtensionRawReferences:
    raw_reference_id: str
    references: tuple[NetworkExtensionRawReference, ...]
    roots: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        artifacts = sorted({item.artifact_path for item in self.references})
        return {
            "total_raw_references": len(self.references),
            "artifacts_with_chrome_references": len(artifacts),
            "candidate_local_network_store_references": sum(item.safety_classification == "candidate_local_network_store" for item in self.references),
            "broad_cache_or_blob_references": sum(item.safety_classification == "broad_cache_or_blob" for item in self.references),
            "structurally_bound_references": sum(item.binding_status == "structurally_bound_identity" for item in self.references),
            "non_actionable_references": sum(item.safety_classification == "not_actionable" for item in self.references),
            "inspect_only_references": sum(item.safety_classification == "inspect_only" for item in self.references),
            "raw_text_reference_only": sum(item.binding_status == "raw_text_reference_only" for item in self.references),
            "ambiguous_preference_reference": sum(item.binding_status == "ambiguous_preference_reference" for item in self.references),
            "read_only": True,
            "mutation_performed": False,
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension raw-references",
            "raw_reference_id": self.raw_reference_id,
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "summary": self.summary(),
            "references": [item.to_json_dict() for item in self.references],
            "roots": list(self.roots),
        }


def build_networkextension_raw_references(roots: Iterable[Path] | None = None) -> NetworkExtensionRawReferences:
    root_paths = [Path(root).expanduser() for root in (roots if roots is not None else default_networkextension_roots())]
    refs: list[NetworkExtensionRawReference] = []
    for root in root_paths:
        for path in _candidate_files(root):
            refs.extend(_references_from_file(path, root))
    references = tuple(sorted(refs, key=lambda item: item.sort_key()))
    digest = hashlib.sha256("|".join(json.dumps(item.to_json_dict(), sort_keys=True) for item in references).encode()).hexdigest()[:16]
    return NetworkExtensionRawReferences(
        raw_reference_id=f"networkextension-raw-references-{digest}",
        references=references,
        roots=tuple(str(root) for root in root_paths),
    )


def networkextension_raw_references_summary(raw_references: NetworkExtensionRawReferences) -> dict[str, Any]:
    return raw_references.summary()


def render_networkextension_raw_references(raw_references: NetworkExtensionRawReferences) -> str:
    summary = raw_references.summary()
    lines = [
        "NetworkExtension raw references",
        "- Read-only: true",
        "- Mutation performed: false",
        f"- Total raw references: {summary['total_raw_references']}",
        f"- Artifacts with Chrome references: {summary['artifacts_with_chrome_references']}",
        f"- Candidate Local Network store references: {summary['candidate_local_network_store_references']}",
        f"- Broad cache/blob references: {summary['broad_cache_or_blob_references']}",
        f"- Structurally bound references: {summary['structurally_bound_references']}",
        f"- Non-actionable references: {summary['non_actionable_references']}",
        "",
        "References",
    ]
    if not raw_references.references:
        lines.append("- none")
    for item in raw_references.references:
        key_path = item.plist_key_path or "<raw text>"
        lines.append(f"- {item.artifact_path} :: {key_path} :: {item.matched_token} [{item.reference_category}, {item.binding_status}, {item.safety_classification}]")
        lines.append(f"  - Reason: {item.actionability_reason}")
    return "\n".join(lines)


def render_networkextension_raw_references_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "NetworkExtension raw references",
            f"- Total raw references: {summary.get('total_raw_references', 0)}",
            f"- Artifacts with Chrome references: {summary.get('artifacts_with_chrome_references', 0)}",
            f"- Candidate Local Network store references: {summary.get('candidate_local_network_store_references', 0)}",
            f"- Broad cache/blob references: {summary.get('broad_cache_or_blob_references', 0)}",
            f"- Structurally bound references: {summary.get('structurally_bound_references', 0)}",
            f"- Non-actionable references: {summary.get('non_actionable_references', 0)}",
        ]
    )


def _references_from_file(path: Path, root: Path) -> list[NetworkExtensionRawReference]:
    try:
        value = _decode_value(path)
    except Exception:
        return []
    display = _display_path(path, root)
    label = _artifact_label(path)
    refs: list[NetworkExtensionRawReference] = []
    for key_path, node in _walk_values(value):
        if isinstance(node, (dict, list)):
            continue
        text = str(node)
        for match in CHROME_TOKEN_RE.finditer(text):
            token = match.group(0)
            category = _reference_category(token)
            if category == "unknown_raw_reference":
                continue
            refs.append(
                NetworkExtensionRawReference(
                    artifact_path=display,
                    artifact_label=label,
                    plist_key_path=key_path,
                    value_type=type(node).__name__,
                    matched_token=token,
                    surrounding_context=_redacted_context(text, match.start(), match.end()),
                    reference_category=category,
                    binding_status=_binding_status(key_path, node, value, token),
                    safety_classification=_safety_classification(path, key_path, text, category),
                    actionability_reason=_actionability_reason(path, key_path, text, category),
                )
            )
    return refs


def _decode_value(path: Path) -> Any:
    data = path.read_bytes()
    if path.suffix == ".plist":
        try:
            return plistlib.loads(data)
        except Exception:
            pass
    text = data.decode("utf-8", errors="ignore")
    try:
        return json.loads(text)
    except Exception:
        return text


def _walk_values(value: Any, prefix: str | None = None) -> list[tuple[str | None, Any]]:
    if isinstance(value, dict):
        result: list[tuple[str | None, Any]] = []
        for key in sorted(value):
            child_path = str(key) if prefix is None else f"{prefix}.{key}"
            result.extend(_walk_values(value[key], child_path))
        return result
    if isinstance(value, list):
        result = []
        for index, item in enumerate(value):
            child_path = f"{prefix}[{index}]" if prefix is not None else f"[{index}]"
            result.extend(_walk_values(item, child_path))
        return result
    return [(prefix, value)]


def _binding_status(key_path: str | None, node: Any, root_value: Any, token: str) -> str:
    if key_path is None:
        return "raw_text_reference_only"
    lower_key = key_path.lower()
    if any(part in lower_key for part in ["raw", "blob", "cache", "serialized"]):
        return "raw_text_reference_only"
    parent = _parent_object(root_value, key_path)
    if isinstance(parent, dict):
        bundle_values = [str(value) for value in parent.values() if isinstance(value, str) and value.startswith("com.")]
        if len(set(bundle_values)) > 1:
            return "ambiguous_preference_reference"
        if token.startswith("com.google.Chrome") and len(set(bundle_values)) == 1:
            return "structurally_bound_identity"
    if token.startswith("com.google.Chrome") and any(part in lower_key for part in ["bundle", "identifier", "bundleid"]):
        return "structurally_bound_identity"
    return "raw_text_reference_only"


def _parent_object(root_value: Any, key_path: str | None) -> Any:
    if not key_path or not isinstance(root_value, (dict, list)):
        return None
    parts = re.split(r"\.(?![^\[]*\])", key_path)
    if len(parts) <= 1:
        return root_value if isinstance(root_value, dict) else None
    current: Any = root_value
    for part in parts[:-1]:
        list_match = re.fullmatch(r"(.+)\[(\d+)\]", part)
        if list_match:
            key, index = list_match.group(1), int(list_match.group(2))
            if not isinstance(current, dict) or key not in current or not isinstance(current[key], list) or index >= len(current[key]):
                return None
            current = current[key][index]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _reference_category(token: str) -> str:
    lower = token.lower()
    if lower == "com.google.chrome.code_sign_clone":
        return "chrome_code_sign_clone"
    if lower.startswith("com.google.chrome"):
        return "chrome_bundle_id"
    if "google chrome" in lower and "/" in token:
        return "chrome_path"
    if lower == "launchservices":
        return "launchservices_reference"
    if lower == "securityprivacyextension":
        return "securityprivacyextension_reference"
    if lower in {"chromium", "chrome"}:
        return "generic_chromium_text"
    return "unknown_raw_reference"


def _safety_classification(path: Path, key_path: str | None, text: str, category: str) -> str:
    lower = " ".join([path.name, key_path or "", text]).lower()
    if category in {"generic_chromium_text", "launchservices_reference", "securityprivacyextension_reference"}:
        return "inspect_only"
    if any(token in lower for token in [".trash", "/volumes/", "mounted"]):
        return "not_actionable"
    if "localnetwork" in lower or "local network" in lower:
        return "candidate_local_network_store"
    if any(token in lower for token in ["raw", "blob", "cache", "serialized"]):
        return "broad_cache_or_blob"
    return "not_actionable"


def _actionability_reason(path: Path, key_path: str | None, text: str, category: str) -> str:
    safety = _safety_classification(path, key_path, text, category)
    if safety == "candidate_local_network_store":
        return "Observed in a specific Local Network preference key; inspect only because this command is read-only."
    if safety == "broad_cache_or_blob":
        return "Broad cache/blob reference does not create identity binding and is not actionable without manual inspection."
    if safety == "inspect_only":
        return "Reference is useful for inspection only and does not create identity binding."
    return "Reference is not actionable from current evidence and does not create identity binding."


def _redacted_context(text: str, start: int, end: int) -> str:
    left = max(0, start - 80)
    right = min(len(text), end + 80)
    context = text[left:right]
    context = UUID_RE.sub("[REDACTED_UUID]", context)
    context = TEAM_ID_RE.sub("[REDACTED_TEAM_ID]", context)
    context = SENSITIVE_PATH_RE.sub("/Users/[REDACTED]", context)
    return " ".join(context.split())[:240]


def _candidate_files(root: Path) -> list[Path]:
    root = root.expanduser()
    if root.is_file():
        return [root]
    if root.is_dir():
        return sorted(path for path in root.rglob("*") if path.is_file() and _is_candidate(path))
    return []


def _is_candidate(path: Path) -> bool:
    lower = str(path).lower()
    return any(token in lower for token in ["networkextension", "localnetwork", "local-network", "securityprivacyextension", "systemsettings"])


def _artifact_label(path: Path) -> str:
    lower = path.name.lower()
    if "localnetwork" in lower or "local-network" in lower:
        return "Local Network preference store"
    if "securityprivacyextension" in lower:
        return "SecurityPrivacyExtension reference"
    if "networkextension" in lower:
        return "NetworkExtension preference file"
    return "Related preference artifact"


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
