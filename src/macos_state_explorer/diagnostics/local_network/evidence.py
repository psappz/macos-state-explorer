from __future__ import annotations

from typing import Any

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.framework import DiagnosticEvidence
from macos_state_explorer.launchservices.analysis import analyze_launchservices, summarize_root_causes
from macos_state_explorer.launchservices.generations import analyze_generations, summarize_chromium_generations_for_local_network

LocalNetworkEvidence = DiagnosticEvidence


def collect_local_network_evidence(
    snapshot: Snapshot,
    trace_analysis: dict[str, Any] | None = None,
) -> list[LocalNetworkEvidence]:
    payloads = {observation.collector: observation.payload for observation in snapshot.observations}
    tcc = payloads.get("tcc", {})
    launchservices = payloads.get("launchservices", {})
    trace_analysis = trace_analysis or {}

    direct_ln = _stdout(tcc.get("direct_localnetwork_query"))
    tcc_hits = _tcc_term_hits(tcc, ["ktccservicelocalnetwork", "localnetwork"])
    has_localnetwork_rows = bool(direct_ln.strip() or tcc_hits)

    all_entries = launchservices.get("entries", []) or []
    stale_entries = launchservices.get("stale_entries", []) or _stale_entries_from_records(all_entries)
    stale_count = len(stale_entries)
    launchservices_analysis = analyze_launchservices(stale_entries)
    root_cause_summary = summarize_root_causes(launchservices_analysis)
    generation_analysis = analyze_generations(all_entries or stale_entries)
    generation_detail = summarize_chromium_generations_for_local_network(generation_analysis)
    stale_blob = str(stale_entries).lower()
    stale_chrome_entries = [entry for entry in stale_entries if _mentions_chrome_or_google(entry)]
    trash_chrome_entries = [entry for entry in stale_chrome_entries if _is_trash_path(entry)]
    non_trash_chrome_entries = [entry for entry in stale_chrome_entries if not _is_trash_path(entry)]
    candidate_files = _stdout(launchservices.get("candidate_files"))
    trace_blob = str(trace_analysis).lower()
    signal_counts = trace_analysis.get("signal_counts", {}) if isinstance(trace_analysis, dict) else {}
    securityprivacy_count = _signal_count(signal_counts, "securityprivacyextension", trace_blob)
    csstore_count = _signal_count(signal_counts, "launchservices_csstore", trace_blob)
    code_sign_count = _signal_count(signal_counts, "chrome_code_sign_clone", trace_blob)
    runningboard_count = _signal_count(signal_counts, "runningboard", trace_blob)
    code_sign_present = "com.google.chrome.code_sign_clone" in stale_blob or code_sign_count > 0

    evidence = [
        LocalNetworkEvidence(
            id="LN-E001",
            title="No kTCCServiceLocalNetwork rows found",
            detail=(
                "The direct Local Network query and scanned TCC/REG hits are empty."
                if not has_localnetwork_rows
                else "TCC/REG data includes Local Network terms; inspect before assuming LaunchServices is primary."
            ),
            source="tcc",
            present=not has_localnetwork_rows,
            provenance=["tcc"],
        ),
        LocalNetworkEvidence(
            id="LN-E002",
            title="LaunchServices has stale/orphaned Chrome or Google registrations",
            detail=(
                f"Chromium-family LaunchServices generations were reported.\n{generation_detail}\n{root_cause_summary}"
                if stale_count
                else "No stale LaunchServices registrations were reported."
            ),
            source="launchservices",
            present=stale_count > 0,
            provenance=["launchservices"],
        ),
        LocalNetworkEvidence(
            id="LN-E003",
            title="LaunchServices store files are in the evidence set",
            detail="LaunchServices candidate files include registry/cache paths used by System Settings." if candidate_files else "No LaunchServices candidate file list was captured in this snapshot.",
            source="launchservices",
            present=bool(candidate_files),
            provenance=["filesystem", "launchservices"],
        ),
        LocalNetworkEvidence(
            id="LN-E004",
            title="SecurityPrivacyExtension appears in Local Network trace",
            detail="Trace analysis references SecurityPrivacyExtension.appex." if securityprivacy_count else "No SecurityPrivacyExtension trace evidence was provided to this solver run.",
            source="trace",
            present=securityprivacy_count > 0,
            confidence=_confidence(0.78, securityprivacy_count),
            provenance=["trace"],
        ),
        LocalNetworkEvidence(
            id="LN-E005",
            title="LaunchServices .csstore files appear heavily in Local Network trace",
            detail=(
                "Trace analysis references LaunchServices .csstore access."
                if csstore_count
                else "No .csstore trace evidence was provided to this solver run."
            ),
            source="trace",
            present=csstore_count > 0,
            confidence=_confidence(0.82, csstore_count),
            provenance=["filesystem", "launchservices", "trace"],
        ),
        LocalNetworkEvidence(
            id="LN-E006",
            title="com.google.Chrome.code_sign_clone appears in evidence",
            detail="Chrome code_sign_clone identity appears in LaunchServices or trace evidence." if code_sign_present else "No code_sign_clone identity appears in this snapshot.",
            source="launchservices/trace",
            present=code_sign_present,
            confidence=_confidence(0.9 if "com.google.chrome.code_sign_clone" in stale_blob else 0.86, code_sign_count),
            provenance=_provenance(
                chrome=True,
                launchservices="com.google.chrome.code_sign_clone" in stale_blob,
                trace=code_sign_count > 0,
            ),
        ),
        LocalNetworkEvidence(
            id="LN-E007",
            title="Chrome or Google stale registration points to Trash",
            detail=(
                f"{len(trash_chrome_entries)} stale Chrome/Google LaunchServices entries point inside Trash."
                if trash_chrome_entries
                else "No stale Chrome/Google LaunchServices entry points inside Trash."
            ),
            source="launchservices",
            present=bool(trash_chrome_entries),
            confidence=0.95 if trash_chrome_entries else 0.7,
            provenance=["filesystem", "launchservices", "chrome"],
        ),
        LocalNetworkEvidence(
            id="LN-E008",
            title="Chrome or Google stale registration is not Trash-specific",
            detail=(
                f"{len(non_trash_chrome_entries)} stale Chrome/Google LaunchServices entries are outside Trash."
                if non_trash_chrome_entries
                else "No non-Trash Chrome/Google stale LaunchServices entry was found."
            ),
            source="launchservices",
            present=bool(non_trash_chrome_entries),
            confidence=0.85 if non_trash_chrome_entries else 0.65,
            provenance=["filesystem", "launchservices", "chrome"],
        ),
        LocalNetworkEvidence(
            id="LN-E009",
            title="RunningBoard activity appears in Local Network trace",
            detail="Trace analysis references RunningBoard app lifecycle activity." if runningboard_count else "No RunningBoard trace evidence was provided to this solver run.",
            source="trace",
            present=runningboard_count > 0,
            confidence=_confidence(0.72, runningboard_count),
            provenance=["runningboard", "trace"],
        ),
    ]
    return evidence


def _stdout(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("stdout", ""))
    return str(value or "")


def _mentions_chrome_or_google(value: Any) -> bool:
    text = str(value).lower()
    return "chrome" in text or "google" in text


def _is_trash_path(value: Any) -> bool:
    text = str(value).lower().replace("\\", "/")
    return "/.trash/" in text or "/trash/" in text


def _stale_entries_from_records(entries: list[Any]) -> list[Any]:
    stale_terms = {"orphaned", "stale", "missing_volume", "duplicate_bundle"}
    stale_entries: list[Any] = []
    for entry in entries:
        if isinstance(entry, dict):
            classification = str(entry.get("classification", "")).lower()
            path_exists = entry.get("path_exists")
            node_not_found = entry.get("node_not_found")
            if classification in stale_terms or path_exists is False or node_not_found is True:
                stale_entries.append(entry)
        else:
            text = str(entry).lower()
            if any(term in text for term in stale_terms):
                stale_entries.append(entry)
    return stale_entries


def _tcc_term_hits(tcc_payload: dict[str, Any], needles: list[str]) -> list[str]:
    hits: list[str] = []
    for section_name in ("user_tcc", "system_tcc", "regdb"):
        section = tcc_payload.get(section_name, {})
        for hit in section.get("hits", []) if isinstance(section, dict) else []:
            blob = str(hit).lower()
            hits.extend(needle for needle in needles if needle in blob)
    direct_chrome = _stdout(tcc_payload.get("direct_chrome_query"))
    if direct_chrome:
        blob = direct_chrome.lower()
        hits.extend(needle for needle in needles if needle in blob)
    return hits


def _signal_count(signal_counts: Any, signal: str, trace_blob: str) -> int:
    if isinstance(signal_counts, dict) and signal_counts.get(signal):
        return int(signal_counts[signal])
    return 1 if signal in trace_blob else 0


def _confidence(base: float, count: int) -> float:
    if count <= 0:
        return max(0.55, base - 0.18)
    return min(0.99, base + (count * 0.04))


def _provenance(*, chrome: bool = False, filesystem: bool = False, launchservices: bool = False, tcc: bool = False, trace: bool = False) -> list[str]:
    values = []
    for enabled, value in [
        (chrome, "chrome"),
        (filesystem, "filesystem"),
        (launchservices, "launchservices"),
        (tcc, "tcc"),
        (trace, "trace"),
    ]:
        if enabled:
            values.append(value)
    return values
