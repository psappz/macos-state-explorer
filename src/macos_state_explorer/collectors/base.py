from __future__ import annotations

from time import time
from typing import Any
from macos_state_explorer.core.model import Observation


class Collector:
    name = "base"

    def collect_payload(self) -> dict[str, Any]:
        raise NotImplementedError

    def collect(self) -> Observation:
        started = time()
        try:
            payload = self.collect_payload()
            errors = []
        except Exception as e:
            payload = {}
            errors = [repr(e)]
        return Observation(collector=self.name, started_at=started, ended_at=time(), payload=payload, errors=errors)
