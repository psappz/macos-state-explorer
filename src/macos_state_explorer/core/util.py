from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
from pathlib import Path
from time import time
from typing import Any


def host() -> str:
    return socket.gethostname()


def run_cmd(cmd: list[str], timeout: int = 120) -> dict[str, Any]:
    started = time()

    try:
        p = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
        )

        return {
            "cmd": cmd,
            "returncode": p.returncode,
            "stdout": p.stdout,
            "stderr": p.stderr,
            "duration": time() - started,
        }

    except Exception as e:
        return {
            "cmd": cmd,
            "error": repr(e),
            "duration": time() - started,
        }


def run_shell(command: str, timeout: int = 120) -> dict[str, Any]:
    return run_cmd(
        ["/bin/bash", "-lc", command],
        timeout=timeout,
    )


def host() -> str:
    return socket.gethostname()


def safe_convert(obj: Any) -> Any:
    """
    Recursively converts everything into JSON-safe objects.

    bytes -> hex string
    sqlite.Row -> dict
    tuple -> list
    set -> list
    """

    if isinstance(obj, bytes):
        return obj.hex()

    if isinstance(obj, sqlite3.Row):
        return {
            k: safe_convert(obj[k])
            for k in obj.keys()
        }

    if isinstance(obj, dict):
        return {
            str(k): safe_convert(v)
            for k, v in obj.items()
        }

    if isinstance(obj, (list, tuple)):
        return [
            safe_convert(x)
            for x in obj
        ]

    if isinstance(obj, set):
        return [
            safe_convert(x)
            for x in obj
        ]

    return obj


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="python")

    data = safe_convert(data)

    path.write_text(
        json.dumps(
            data,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    )


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sqlite_overview(
    path: str,
    terms: list[str] | None = None,
) -> dict[str, Any]:

    p = Path(path).expanduser()

    result = {
        "path": str(p),
        "exists": p.exists(),
        "tables": [],
        "hits": [],
        "errors": [],
    }

    if not p.exists():
        return result

    try:

        conn = sqlite3.connect(
            f"file:{p}?mode=ro",
            uri=True,
            timeout=3,
        )

        conn.row_factory = sqlite3.Row

        cur = conn.cursor()

        cur.execute(
            "SELECT name,type,sql FROM sqlite_master ORDER BY type,name"
        )

        result["schema"] = safe_convert(cur.fetchall())

        for row in result["schema"]:

            if row["type"] != "table":
                continue

            table = row["name"]

            table_info = {
                "name": table,
                "columns": [],
                "count": None,
            }

            try:

                cur.execute(
                    f"PRAGMA table_info({quote_ident(table)})"
                )

                table_info["columns"] = safe_convert(cur.fetchall())

                cur.execute(
                    f"SELECT COUNT(*) AS c FROM {quote_ident(table)}"
                )

                table_info["count"] = cur.fetchone()["c"]

            except Exception as e:
                result["errors"].append(
                    f"{table}: {e!r}"
                )

            result["tables"].append(table_info)

            if terms:

                try:

                    cur.execute(
                        f"SELECT * FROM {quote_ident(table)} LIMIT 500"
                    )

                    rows = safe_convert(cur.fetchall())

                    for idx, r in enumerate(rows):

                        blob = json.dumps(
                            r,
                            ensure_ascii=False,
                            default=str,
                        ).lower()

                        matches = [
                            t
                            for t in terms
                            if t.lower() in blob
                        ]

                        if matches:
                            result["hits"].append(
                                {
                                    "table": table,
                                    "row_index": idx,
                                    "terms": matches,
                                    "row": r,
                                }
                            )

                except Exception as e:
                    result["errors"].append(
                        f"search {table}: {e!r}"
                    )

        conn.close()

    except Exception as e:
        result["errors"].append(repr(e))

    return safe_convert(result)
