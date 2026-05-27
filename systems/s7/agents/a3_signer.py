"""
A3 — Signature SHA-256 + sidecar JSON (Python pur).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from systems.s7.document import ReportDocument


def canonical_payload(
    question_originale: str,
    intent: dict,
    s3_output: dict,
    s5_output: dict,
    s6_output: dict,
    timestamp: str,
) -> str:
    specialist_results = list(s3_output.get("specialist_results") or [])
    recommandations = list(s6_output.get("recommandations") or [])
    parts = [
        question_originale,
        json.dumps(intent, sort_keys=True, ensure_ascii=False, default=str),
        json.dumps(specialist_results, sort_keys=True, ensure_ascii=False, default=str),
        json.dumps(recommandations, sort_keys=True, ensure_ascii=False, default=str),
        str(s5_output.get("synthese", "") or ""),
        str(s6_output.get("synthese_action", "") or ""),
        str(s5_output.get("fidelite_score", 0.0)),
        timestamp,
    ]
    return "".join(parts)


def compute_sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run(
    document: "ReportDocument",
    question_originale: str,
    intent: dict,
    s3_output: dict,
    s5_output: dict,
    s6_output: dict,
    *,
    timestamp: str,
    reports_dir: str | Path,
    slug: str,
) -> dict:
    try:
        payload = canonical_payload(
            question_originale, intent, s3_output, s5_output, s6_output, timestamp
        )
        sha = compute_sha256(payload)
        trace = document.find("traceability")
        if trace is not None:
            trace.data["sha256"] = sha
        document.meta["sha256"] = sha

        reports_dir = Path(reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        safe_ts = timestamp.replace(":", "").replace(".", "")
        sidecar_name = f"rapport_{slug}_{safe_ts}.meta.json"
        sidecar_path = reports_dir / sidecar_name
        sidecar = {
            "sha256": sha,
            "timestamp": timestamp,
            "metadata": dict(document.meta),
        }
        sidecar_path.write_text(
            json.dumps(sidecar, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return {"sha256": sha, "sidecar_path": str(sidecar_path), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"sha256": "", "sidecar_path": "", "error": str(exc)}
