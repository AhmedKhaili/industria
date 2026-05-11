"""
Agent LLM IndustrIA : traduit les résultats analytiques en français pour techniciens.
Aucun calcul — uniquement reformulation via Ollama (JSON structuré en entrée).
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from ollama import Client

OLLAMA_HOST = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5-coder:14b"
OLLAMA_TIMEOUT_S = 45.0
NUM_CTX = 8000
TEMPERATURE = 0.3

MAX_SAMPLE_ITEMS = 5
FLOAT_DECIMALS = 3
TARGET_PROMPT_TOKENS = 5000
AGGRESSIVE_TRUNCATE_JSON_AT = 3000
TOKEN_CHAR_RATIO = 4

MAX_EXPLANATION_CHARS = 800

SYSTEM_PROMPT = """Tu es IndustrIA, un assistant d'analyse industrielle.
Tu expliques des résultats statistiques à des techniciens de maintenance en français simple et précis.

Règles :
- Jamais de jargon statistique brut (pas de 'z-score = 4.2')
- Toujours traduire en impact concret (ex. : 'le four 3 a dépassé sa limite normale 12 fois')
- Si anomalie détectée : dire QUAND, SUR QUOI, et quelle action recommander
- Si pas d'anomalie : rassurer clairement
- Format : 3-5 phrases maximum, ton professionnel
- Terminer par UNE recommandation concrète d'action"""


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // TOKEN_CHAR_RATIO)


def _round_floats(obj: Any) -> Any:
    if isinstance(obj, float):
        return round(obj, FLOAT_DECIMALS)
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(x) for x in obj]
    return obj


def _strip_empty(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            sv = _strip_empty(v)
            if sv is None:
                continue
            if sv == "":
                continue
            if sv == []:
                continue
            if sv == {}:
                continue
            out[k] = sv
        return out
    if isinstance(obj, list):
        out = [_strip_empty(x) for x in obj]
        out = [x for x in out if x is not None and x != "" and x != [] and x != {}]
        return out
    return obj


def _cap_sql_sample(payload: dict[str, Any]) -> None:
    sd = payload.get("sql_data")
    if not isinstance(sd, dict):
        return
    sample = sd.get("sample")
    if isinstance(sample, list) and len(sample) > MAX_SAMPLE_ITEMS:
        sd["sample"] = sample[:MAX_SAMPLE_ITEMS]
        sd["sample_truncated"] = True


def _truncate_result_lists_for_tokens(obj: Any, aggressive: bool) -> Any:
    """Réduit les listes longues dans results pour limiter la taille du prompt."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(v, list) and len(v) > 0:
                if aggressive:
                    out[k] = f"<liste omise, {len(v)} éléments>"
                else:
                    out[k] = v[: min(3, len(v))]
            elif isinstance(v, dict):
                out[k] = _truncate_result_lists_for_tokens(v, aggressive)
            else:
                out[k] = v
        return out
    if isinstance(obj, list):
        if aggressive:
            return f"<liste omise, {len(obj)} éléments>"
        return [_truncate_result_lists_for_tokens(x, aggressive) for x in obj[:5]]
    return obj


def _compress_analysis_results(analysis_results: dict[str, Any]) -> dict[str, Any]:
    """ÉTAPE A+B — Structure + compression pour Ollama."""
    data = deepcopy(analysis_results)
    data = _round_floats(data)
    _cap_sql_sample(data)

    results = data.get("results")
    if isinstance(results, dict):
        trimmed: dict[str, Any] = {}
        for agent_name, agent_res in results.items():
            if isinstance(agent_res, dict):
                trimmed[agent_name] = _truncate_result_lists_for_tokens(agent_res, aggressive=False)
            else:
                trimmed[agent_name] = agent_res
        data["results"] = trimmed

    data = _strip_empty(data)

    payload_str = json.dumps(data, ensure_ascii=False, default=str)
    est = _estimate_tokens(payload_str)
    if est > AGGRESSIVE_TRUNCATE_JSON_AT:
        data2 = deepcopy(data)
        res = data2.get("results")
        if isinstance(res, dict):
            for k, v in list(res.items()):
                if isinstance(v, dict):
                    res[k] = _truncate_result_lists_for_tokens(v, aggressive=True)
        if isinstance(data2.get("sql_data"), dict):
            sd = data2["sql_data"]
            if "sample" in sd:
                sd["sample"] = []
        data2 = _strip_empty(_round_floats(data2))
        data = data2

    return data


def _strip_markdown_light(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\*+([^*]+)\*+", r"\1", t)
    t = t.replace("`", "")
    return t.strip()


def _truncate_at_last_sentence(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    last_period = cut.rfind(".")
    last_excl = cut.rfind("!")
    last_q = cut.rfind("?")
    end = max(last_period, last_excl, last_q)
    if end > max_len // 4:
        return cut[: end + 1].strip()
    return cut.rstrip() + "…"


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _split_explanation_and_recommendation(text: str) -> tuple[str, str]:
    """Dernière phrase = recommandation ; le reste = explication (évite la duplication)."""
    sentences = _split_sentences(text)
    if not sentences:
        return (
            "",
            "Consulter les données brutes et le responsable de ligne.",
        )
    if len(sentences) == 1:
        return sentences[0], sentences[0]
    return " ".join(sentences[:-1]), sentences[-1]


def _infer_anomaly_detected(analysis_results: dict[str, Any]) -> bool:
    results = analysis_results.get("results") or {}
    if not isinstance(results, dict):
        return False
    for v in results.values():
        if not isinstance(v, dict):
            continue
        ac = v.get("anomalies_count")
        if isinstance(ac, (int, float)) and ac > 0:
            return True
        if v.get("anomaly_detected") is True:
            return True
        if v.get("anomalies"):
            if isinstance(v["anomalies"], list) and len(v["anomalies"]) > 0:
                return True
    return False


def _fallback_from_results(
    analysis_results: dict[str, Any],
    *,
    error: str | None,
) -> dict[str, Any]:
    n = 0
    colonne = "les variables suivies"
    results = analysis_results.get("results") or {}
    if isinstance(results, dict):
        for v in results.values():
            if isinstance(v, dict):
                ac = v.get("anomalies_count")
                if isinstance(ac, (int, float)):
                    n = max(n, int(ac))
                alist = v.get("anomalies")
                if isinstance(alist, list) and len(alist) > n:
                    n = len(alist)
                col = v.get("colonne") or v.get("column")
                if isinstance(col, str) and col:
                    colonne = col
    anomaly = _infer_anomaly_detected(analysis_results)
    if anomaly:
        expl = f"Analyse effectuée. {n} anomalies détectées sur {colonne}."
    else:
        expl = (
            "Analyse effectuée. Aucune anomalie marquante détectée dans les indicateurs agrégés."
        )
    return {
        "explanation": expl,
        "agents_used": list(analysis_results.get("agents_used") or []),
        "anomaly_detected": anomaly,
        "recommendation": "Consulter les données brutes.",
        "error": error,
    }


class LLMAgent:
    """Reformule les sorties des agents analytiques pour un technicien."""

    def __init__(
        self,
        *,
        host: str = OLLAMA_HOST,
        model: str = OLLAMA_MODEL,
        timeout: float = OLLAMA_TIMEOUT_S,
    ) -> None:
        self._client = Client(host=host, timeout=timeout)
        self._model = model

    def explain(self, analysis_results: dict[str, Any]) -> dict[str, Any]:
        agents_used = list(analysis_results.get("agents_used") or [])
        question = (analysis_results.get("question") or "").strip()
        anomaly_flag = _infer_anomaly_detected(analysis_results)

        if not question:
            return {
                "explanation": "Aucune question initiale fournie.",
                "agents_used": agents_used,
                "anomaly_detected": anomaly_flag,
                "recommendation": "Vérifier le contexte d'analyse.",
                "error": "question_manquante",
            }

        compressed = _compress_analysis_results(analysis_results)
        payload_json = json.dumps(compressed, ensure_ascii=False, default=str)
        user_msg = (
            f"Question initiale : {question}\n\n"
            f"Résultats des analyses : {payload_json}\n\n"
            "Génère l'explication pour le technicien."
        )
        if _estimate_tokens(SYSTEM_PROMPT + user_msg) > TARGET_PROMPT_TOKENS:
            minimal = {
                "question": question,
                "agents_used": agents_used,
                "results_summary": {
                    k: (
                        {sk: sv for sk, sv in v.items() if sk != "anomalies" and not isinstance(sv, list)}
                        if isinstance(v, dict)
                        else v
                    )
                    for k, v in (compressed.get("results") or {}).items()
                },
            }
            payload_json = json.dumps(minimal, ensure_ascii=False, default=str)
            user_msg = (
                f"Question initiale : {question}\n\n"
                f"Résultats des analyses (résumé) : {payload_json}\n\n"
                "Génère l'explication pour le technicien."
            )

        try:
            resp = self._client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                options={
                    "num_ctx": NUM_CTX,
                    "temperature": TEMPERATURE,
                },
            )
        except Exception:
            return _fallback_from_results(analysis_results, error="LLM indisponible")

        raw = (resp.message.content if resp.message else "") or ""
        raw = _strip_markdown_light(raw)
        full = _truncate_at_last_sentence(raw, MAX_EXPLANATION_CHARS)
        explanation, recommendation = _split_explanation_and_recommendation(full)

        return {
            "explanation": explanation,
            "agents_used": agents_used,
            "anomaly_detected": anomaly_flag,
            "recommendation": recommendation,
            "error": None,
        }


if __name__ == "__main__":
    demo = {
        "question": "Y a-t-il des anomalies dans le four 3 ?",
        "agents_used": ["zscore_agent", "isolation_forest_agent"],
        "sql_data": {
            "row_count": 526,
            "sample": [{"timestamp": "2026-05-10T12:00:00Z", "four_3": 339.123456}],
        },
        "results": {
            "zscore_agent": {
                "anomalies_count": 12,
                "anomalies": [{"t": 1}, {"t": 2}],
                "max_zscore": 4.2,
                "colonne": "four_3",
            },
            "isolation_forest_agent": {
                "anomalies_count": 9,
                "contamination": 0.05,
            },
        },
        "context": {
            "tables": ["formage_data"],
            "time_filter": "depuis lundi",
            "nominaux": {"four_3": 340.0},
        },
    }
    agent = LLMAgent()
    out = agent.explain(demo)
    print(json.dumps(out, ensure_ascii=False, indent=2))
