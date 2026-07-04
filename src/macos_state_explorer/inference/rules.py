from __future__ import annotations
from macos_state_explorer.core.model import Hypothesis, Snapshot


def infer(snapshot: Snapshot) -> list[Hypothesis]:
    payloads = {o.collector: o.payload for o in snapshot.observations}
    hyps: list[Hypothesis] = []
    tcc_blob = str(payloads.get("tcc", {})).lower()
    has_localnetwork = "ktccservicelocalnetwork" in tcc_blob or "localnetwork" in tcc_blob

    ls = payloads.get("launchservices", {})
    stale = ls.get("stale_entries", [])

    if not has_localnetwork:
        hyps.append(Hypothesis(
            title="TCC.access is unlikely to be the direct Local Network GUI source",
            confidence=0.90,
            evidence=["No kTCCServiceLocalNetwork/LocalNetwork rows found in scanned TCC/REG data."],
            next_actions=["Trace System Settings while opening the Local Network page."],
        ))

    if stale:
        hyps.append(Hypothesis(
            title="LaunchServices contains stale or orphaned app registrations",
            confidence=0.90,
            evidence=[f"{len(stale)} stale/orphaned/missing-volume LaunchServices entries found."],
            next_actions=["Compare stale entries with System Settings GUI."],
        ))

    if stale and not has_localnetwork:
        hyps.append(Hypothesis(
            title="Local Network GUI may be backed by app registry metadata or a privacy cache layer",
            confidence=0.80,
            evidence=["LaunchServices has stale app records.", "TCC lacks LocalNetwork rows."],
            next_actions=["Run `mse trace local-network ~/Desktop/mse-trace`."],
        ))

    return hyps
