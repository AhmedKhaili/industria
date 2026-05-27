"""
Client Ollama 14b avec file FIFO (1 appel à la fois).
"""

from __future__ import annotations

import threading
import time

import requests

from data.config import MONITORING_CONFIG, OLLAMA_CONFIG

OLLAMA_URL = "http://localhost:11434/api/generate"
LLM_TIMEOUT_S = int(MONITORING_CONFIG.get("ollama_timeout_s", 30))
LLM_MAX_RETRIES = 3

_fifo_lock = threading.Lock()
_step_stats = {"calls": 0, "failures": 0, "duration_s": 0.0}


def reset_step_stats() -> None:
    _step_stats["calls"] = 0
    _step_stats["failures"] = 0
    _step_stats["duration_s"] = 0.0


def pop_step_stats() -> dict:
    stats = {
        "llm_calls": _step_stats["calls"],
        "llm_failures": _step_stats["failures"],
        "llm_duration_s": round(_step_stats["duration_s"], 2),
    }
    reset_step_stats()
    return stats


def chat(prompt: str, *, temperature: float = 0.2, num_predict: int = 400) -> str | None:
    """Appel LLM synchronisé ; None si échec après 3 tentatives."""
    payload = {
        "model": OLLAMA_CONFIG["model_14b"],
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    t0 = time.perf_counter()
    with _fifo_lock:
        _step_stats["calls"] += 1
        for _ in range(LLM_MAX_RETRIES):
            try:
                resp = requests.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT_S)
                resp.raise_for_status()
                text = (resp.json().get("response") or "").strip()
                if text:
                    _step_stats["duration_s"] += time.perf_counter() - t0
                    return text
            except Exception:
                continue
    _step_stats["failures"] += 1
    _step_stats["duration_s"] += time.perf_counter() - t0
    return None
