"""
Fixtures partagées — tests E2E pipeline S1→S5 (données LISI réelles).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import requests

from systems.s1.client_context import ClientContext

REPO_ROOT = Path(__file__).resolve().parent.parent
LISI_YAML = REPO_ROOT / "configs/lisi_aerospace/client_config.yaml"
LISI_CSV = REPO_ROOT / "data/lisi_capteurs.csv"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"


def ollama_available() -> bool:
    """True si Ollama répond sur localhost:11434."""
    try:
        resp = requests.get(OLLAMA_TAGS_URL, timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


OLLAMA_REQUIRED = pytest.mark.skipif(
    not ollama_available(),
    reason="Ollama non disponible sur http://localhost:11434",
)


@pytest.fixture(scope="session")
def lisi_yaml_path() -> str:
    if not LISI_YAML.is_file():
        pytest.fail(f"Config LISI introuvable : {LISI_YAML}")
    return str(LISI_YAML)


@pytest.fixture(scope="session")
def lisi_csv_path() -> Path:
    if not LISI_CSV.is_file():
        pytest.fail(f"Dataset LISI introuvable : {LISI_CSV}")
    return LISI_CSV


@pytest.fixture(scope="session")
def lisi_context(lisi_yaml_path: str) -> ClientContext:
    return ClientContext.load(lisi_yaml_path)


@pytest.fixture(scope="session")
def operateur_forbidden_words(lisi_context: ClientContext) -> list[str]:
    cfg = lisi_context.profils.get("operateur", {})
    words = cfg.get("forbidden_words", [])
    return [str(w).lower() for w in words]


def assert_no_forbidden_words(text: str, forbidden: list[str]) -> None:
    lowered = text.lower()
    for word in forbidden:
        assert not re.search(
            rf"\b{re.escape(word)}\b", lowered, re.IGNORECASE
        ), f"Terme interdit profil operateur présent : {word}"
