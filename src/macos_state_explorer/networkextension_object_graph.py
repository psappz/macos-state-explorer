from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import json
import plistlib
import re
from pathlib import Path
from typing import Any, Iterable

from macos_state_explorer.networkextension_state import default_networkextension_roots

GRAPH_TOKEN_RE = re.compile(
    r"com\.google\.Chrome\.code_sign_clone|com\.google\.Chrome(?:\.[A-Za-z0-9_.-]+)?|/(?:Applications|Users|Volumes)[^\"'\n\r]*Google Chrome[^\"'\n\r]*|LaunchServices|SecurityPrivacyExtension|Chromium|Chrome",
    re.IGNORECASE,
)
SENSITIVE_PATH_RE = re.compile(r"/Users/[^/\s\"']+")
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
TEAM_ID_RE = re.compile(r"\b[A-Z0-9]{10}\b")


@dataclass(frozen=True)
class ObjectGraphReference:
    artifact: str
    artifact_path: str
    object_index: int
    object_reference: str
    value_type: str
    matched_token: str
    reference_category: str
    key_path: str | None
    parent_chain: tuple[str, ...]
    nearest_dictionary_keys: tuple[str, ...]
    neighboring_object_indices: tuple[int, ...]
    binding_classification: str
    safety_classification: str
    explanation: str

    def sort_key(self) -> tuple[str, int, str, str]:
        return (self.artifact_path, self.object_index, self.key_path or "", self.matched_token)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "artifact_path": self.artifact_path,
            "object_index": self.object_index,
            "object_reference": self.object_reference,
            "value_type": self.value_type,
            "matched_token": self.matched_token,
            "reference_category": self.reference_category,
            "key_path": self.key_path,
            "parent_chain": list(self.parent_chain),
            "nearest_dictionary_keys": list(self.nearest_dictionary_keys),
            "neighboring_object_indices": list(self.neighboring_object_indices),
            "binding_classification": self.binding_classification,
            "safety_classification": self.safety_classification,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class DecodedObjectGraphArtifact:
    artifact: str
    artifact_path: str
    decoded: bool
    object_count: int
    malformed: bool = False
    error: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "artifact_path": self.artifact_path,
            "decoded": self.decoded,
            "object_count": self.object_count,
            "malformed": self.malformed,
            "error": self.error,
        }


@dataclass(frozen=True)
class NetworkExtensionObjectGraph:
    object_graph_id: str
    references: tuple[ObjectGraphReference, ...]
    decoded_artifacts: tuple[DecodedObjectGraphArtifact, ...]
    roots: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        binding_counts = _counts(item.binding_classification for item in self.references)
        safety_counts = _counts(item.safety_classification for item in self.references)
        parent_summaries = sorted({" > ".join(item.parent_chain) for item in self.references if item.parent_chain})
        return {
            "decoded_artifacts": sum(artifact.decoded for artifact in self.decoded_artifacts),
            "malformed_artifacts": sum(artifact.malformed for artifact in self.decoded_artifacts),
            "total_references": len(self.references),
            "referenced_objects": len({(item.artifact_path, item.object_index) for item in self.references}),
            "referenced_object_indices": sorted({f"{item.artifact}:{item.object_reference}" for item in self.references}),
            "policy_record_candidates": binding_counts.get("policy_record_candidate", 0),
            "client_identity_candidates": binding_counts.get("client_identity_candidate", 0),
            "cache_or_blob_references": binding_counts.get("cache_or_blob_reference", 0),
            "raw_archive_references": binding_counts.get("raw_archive_reference", 0),
            "unknown_object_contexts": binding_counts.get("unknown_object_context", 0),
            "binding_classifications": binding_counts,
            "safety_classifications": safety_counts,
            "parent_chain_summaries": parent_summaries,
            "read_only": True,
            "mutation_performed": False,
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension object-graph",
            "object_graph_id": self.object_graph_id,
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "summary": self.summary(),
            "references": [item.to_json_dict() for item in self.references],
            "decoded_artifacts": [item.to_json_dict() for item in self.decoded_artifacts],
            "roots": list(self.roots),
        }


def build_networkextension_object_graph(roots: Iterable[Path] | None = None) -> NetworkExtensionObjectGraph:
    root_paths = [Path(root).expanduser() for root in (roots if roots is not None else default_networkextension_roots())]
    references: list[ObjectGraphReference] = []
    artifacts: list[DecodedObjectGraphArtifact] = []
    for root in root_paths:
        for path in _candidate_files(root):
            artifact, refs = _decode_artifact(path, root)
            artifacts.append(artifact)
            references.extend(refs)
    ordered_refs = tuple(sorted(references, key=lambda item: item.sort_key()))
    ordered_artifacts = tuple(sorted(artifacts, key=lambda item: item.artifact_path))
    digest = hashlib.sha256(
        json.dumps(
            {
                "artifacts": [item.to_json_dict() for item in ordered_artifacts],
                "references": [item.to_json_dict() for item in ordered_refs],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    return NetworkExtensionObjectGraph(
        object_graph_id=f"networkextension-object-graph-{digest}",
        references=ordered_refs,
        decoded_artifacts=ordered_artifacts,
        roots=tuple(str(root) for root in root_paths),
    )


def networkextension_object_graph_summary(graph: NetworkExtensionObjectGraph) -> dict[str, Any]:
    return graph.summary()


def render_networkextension_object_graph(graph: NetworkExtensionObjectGraph) -> str:
    summary = graph.summary()
    lines = [
        "NetworkExtension object graph",
        "- Read-only: true",
        "- Mutation performed: false",
        f"- Decoded artifacts: {summary['decoded_artifacts']}",
        f"- Malformed artifacts: {summary['malformed_artifacts']}",
        f"- Referenced objects: {summary['referenced_objects']}",
        f"- Policy record candidates: {summary['policy_record_candidates']}",
        f"- Client identity candidates: {summary['client_identity_candidates']}",
        f"- Cache/blob references: {summary['cache_or_blob_references']}",
        f"- Unknown object contexts: {summary['unknown_object_contexts']}",
        "",
        "References",
    ]
    if not graph.references:
        lines.append("- none")
    for item in graph.references:
        lines.append(
            f"- {item.artifact} :: {item.object_reference} :: {item.matched_token} "
            f"[{item.binding_classification}, {_human_safety_label(item.safety_classification)}]"
        )
        if item.key_path:
            lines.append(f"  - Key path: {item.key_path}")
        if item.parent_chain:
            lines.append(f"  - Parent chain: {' > '.join(item.parent_chain)}")
        if item.nearest_dictionary_keys:
            lines.append(f"  - Nearest dictionary keys: {', '.join(item.nearest_dictionary_keys)}")
        if item.neighboring_object_indices:
            lines.append(f"  - Neighboring object indices: {', '.join(str(index) for index in item.neighboring_object_indices)}")
        lines.append(f"  - Explanation: {item.explanation}")
    return "\n".join(lines)


def render_networkextension_object_graph_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "NetworkExtension object graph",
            f"- Decoded artifacts: {summary.get('decoded_artifacts', 0)}",
            f"- Malformed artifacts: {summary.get('malformed_artifacts', 0)}",
            f"- Referenced objects: {summary.get('referenced_objects', 0)}",
            f"- Policy record candidates: {summary.get('policy_record_candidates', 0)}",
            f"- Client identity candidates: {summary.get('client_identity_candidates', 0)}",
            f"- Cache/blob references: {summary.get('cache_or_blob_references', 0)}",
            f"- Unknown object contexts: {summary.get('unknown_object_contexts', 0)}",
        ]
    )


def _decode_artifact(path: Path, root: Path) -> tuple[DecodedObjectGraphArtifact, list[ObjectGraphReference]]:
    display = _display_path(path, root)
    artifact_name = path.name
    try:
        value = plistlib.loads(path.read_bytes())
    except Exception as error:
        return DecodedObjectGraphArtifact(artifact=artifact_name, artifact_path=display, decoded=False, object_count=0, malformed=True, error=type(error).__name__), []
    objects = value.get("$objects") if isinstance(value, dict) else None
    if not isinstance(objects, list):
        return DecodedObjectGraphArtifact(artifact=artifact_name, artifact_path=display, decoded=False, object_count=0, malformed=True, error="missing_$objects"), []
    edges, parent_edges = _build_edges(objects)
    top_indices = _top_indices(value)
    refs: list[ObjectGraphReference] = []
    for index, node in enumerate(objects):
        refs.extend(_references_in_object(artifact_name, display, index, node, objects, parent_edges, top_indices))
    artifact = DecodedObjectGraphArtifact(artifact=artifact_name, artifact_path=display, decoded=True, object_count=len(objects))
    return artifact, refs


def _references_in_object(
    artifact: str,
    artifact_path: str,
    index: int,
    node: Any,
    objects: list[Any],
    parent_edges: dict[int, list[tuple[int, str | None]]],
    top_indices: set[int],
) -> list[ObjectGraphReference]:
    refs: list[ObjectGraphReference] = []
    for local_path, value in _walk_object_values(node):
        if isinstance(value, (dict, list, plistlib.UID)):
            continue
        text = str(value)
        for match in GRAPH_TOKEN_RE.finditer(text):
            token = match.group(0).strip()
            category = _reference_category(token)
            if category == "unknown_raw_reference":
                continue
            parent_chain_indices = _parent_chain(index, parent_edges, top_indices)
            nearest_keys = _nearest_dictionary_keys(index, objects, parent_edges)
            neighbor_indices = _neighboring_indices(index, objects, parent_edges)
            key_path = _key_path(index, local_path, parent_edges)
            binding = _binding_classification(index, local_path, text, token, objects, parent_edges, parent_chain_indices, nearest_keys)
            safety = _safety_classification(binding)
            refs.append(
                ObjectGraphReference(
                    artifact=artifact,
                    artifact_path=artifact_path,
                    object_index=index,
                    object_reference=f"$objects[{index}]",
                    value_type=type(value).__name__,
                    matched_token=token,
                    reference_category=category,
                    key_path=key_path,
                    parent_chain=tuple(f"$objects[{item}]" for item in parent_chain_indices),
                    nearest_dictionary_keys=tuple(nearest_keys),
                    neighboring_object_indices=tuple(neighbor_indices),
                    binding_classification=binding,
                    safety_classification=safety,
                    explanation=_explanation(binding, safety),
                )
            )
    return refs


def _build_edges(objects: list[Any]) -> tuple[dict[int, list[tuple[int, str | None]]], dict[int, list[tuple[int, str | None]]]]:
    edges: dict[int, list[tuple[int, str | None]]] = defaultdict(list)
    parents: dict[int, list[tuple[int, str | None]]] = defaultdict(list)
    for index, node in enumerate(objects):
        for child, label in _uid_children(node):
            if 0 <= child < len(objects):
                edges[index].append((child, label))
                parents[child].append((index, label))
    return edges, parents


def _uid_children(value: Any, prefix: str | None = None) -> list[tuple[int, str | None]]:
    if isinstance(value, plistlib.UID):
        return [(value.data, prefix)]
    if isinstance(value, dict):
        result: list[tuple[int, str | None]] = []
        for key in sorted(value):
            child_prefix = str(key) if prefix is None else f"{prefix}.{key}"
            result.extend(_uid_children(value[key], child_prefix))
        return result
    if isinstance(value, list):
        result = []
        for idx, item in enumerate(value):
            child_prefix = f"[{idx}]" if prefix is None else f"{prefix}[{idx}]"
            result.extend(_uid_children(item, child_prefix))
        return result
    return []


def _walk_object_values(value: Any, prefix: str | None = None) -> list[tuple[str | None, Any]]:
    if isinstance(value, plistlib.UID):
        return [(prefix, value)]
    if isinstance(value, dict):
        result: list[tuple[str | None, Any]] = []
        for key in sorted(value):
            child_path = str(key) if prefix is None else f"{prefix}.{key}"
            result.extend(_walk_object_values(value[key], child_path))
        return result
    if isinstance(value, list):
        result = []
        for idx, item in enumerate(value):
            child_path = f"[{idx}]" if prefix is None else f"{prefix}[{idx}]"
            result.extend(_walk_object_values(item, child_path))
        return result
    return [(prefix, value)]


def _top_indices(value: dict[str, Any]) -> set[int]:
    top = value.get("$top")
    return {index for index, _label in _uid_children(top)} if isinstance(top, dict) else set()


def _parent_chain(index: int, parent_edges: dict[int, list[tuple[int, str | None]]], top_indices: set[int]) -> list[int]:
    if index in top_indices:
        return []
    queue = deque([(index, [])])
    visited = {index}
    while queue:
        current, path = queue.popleft()
        for parent, _label in sorted(parent_edges.get(current, []), key=lambda item: (item[0], item[1] or "")):
            next_path = [parent, *path]
            if parent in top_indices or not parent_edges.get(parent):
                return next_path
            if parent not in visited:
                visited.add(parent)
                queue.append((parent, next_path))
    return []


def _nearest_dictionary_keys(index: int, objects: list[Any], parent_edges: dict[int, list[tuple[int, str | None]]]) -> list[str]:
    for parent, _label in sorted(parent_edges.get(index, []), key=lambda item: (item[0], item[1] or "")):
        node = objects[parent]
        if isinstance(node, dict):
            return sorted(str(key) for key in node)
    node = objects[index]
    if isinstance(node, dict):
        return sorted(str(key) for key in node)
    return []


def _neighboring_indices(index: int, objects: list[Any], parent_edges: dict[int, list[tuple[int, str | None]]]) -> list[int]:
    neighbors: set[int] = set()
    for parent, _label in parent_edges.get(index, []):
        for child, _child_label in _uid_children(objects[parent]):
            if child != index:
                neighbors.add(child)
    return sorted(neighbors)


def _key_path(index: int, local_path: str | None, parent_edges: dict[int, list[tuple[int, str | None]]]) -> str | None:
    base = f"$objects[{index}]"
    if local_path:
        return f"{base}.{local_path}"
    parents = sorted(parent_edges.get(index, []), key=lambda item: (item[0], item[1] or ""))
    if parents and parents[0][1]:
        return f"$objects[{parents[0][0]}].{parents[0][1]}"
    return base


def _binding_classification(
    index: int,
    local_path: str | None,
    text: str,
    token: str,
    objects: list[Any],
    parent_edges: dict[int, list[tuple[int, str | None]]],
    parent_chain: list[int],
    nearest_keys: list[str],
) -> str:
    context = " ".join([local_path or "", text, " ".join(nearest_keys), " ".join(str(objects[parent]) for parent in parent_chain[-3:])]).lower()
    direct_context = " ".join([local_path or "", text, " ".join(nearest_keys)]).lower()
    if any(part in context for part in ["cache", "blob", "serialized", "history", "historical"]):
        return "cache_or_blob_reference"
    if any(part in direct_context for part in ["bundle", "codesign", "code_sign", "path"]):
        return "client_identity_candidate"
    if "policy" in context and "client" in context:
        return "policy_record_candidate"
    if parent_chain or parent_edges.get(index):
        return "raw_archive_reference"
    return "unknown_object_context"


def _safety_classification(binding: str) -> str:
    if binding in {"policy_record_candidate", "client_identity_candidate"}:
        return "potential_future_repair_candidate"
    if binding in {"cache_or_blob_reference", "raw_archive_reference"}:
        return "inspect_only"
    return "not_actionable"


def _human_safety_label(safety: str) -> str:
    if safety == "potential_future_repair_candidate":
        return "potential_future_candidate"
    return safety


def _explanation(binding: str, safety: str) -> str:
    if binding == "policy_record_candidate":
        return "object graph context resembles a policy record; read-only evidence only and not deletable."
    if binding == "client_identity_candidate":
        return "object graph context resembles a client identity record; read-only evidence only and not deletable."
    if binding == "cache_or_blob_reference":
        return "object graph context appears inside cache/blob or historical archive context; inspect only and not actionable."
    if binding == "raw_archive_reference":
        return "object graph context has parent/child links but no actionable policy or client record proof."
    return "object graph context is unknown; reference is not actionable."


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


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))
