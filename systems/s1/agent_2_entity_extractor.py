"""
Extraction d'entités par fuzzy + embeddings + fusion RRF — Python pur.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import numpy as np
from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

MODEL_EMBED = "all-MiniLM-L6-v2"
RRF_K = 60
SCORE_CERTAIN = 0.85
SCORE_AMBIGUOUS_LOW = 0.70
FACTEUR_LEXICAL_CERTAIN = 0.75


class Agent2EntityExtractor:
    def __init__(self) -> None:
        self._embedder: SentenceTransformer | None = None
        self._embedder_failed = False
        self._embed_cache: dict[str, np.ndarray] = {}

    def _get_embedder(self) -> SentenceTransformer | None:
        if self._embedder_failed:
            return None
        if self._embedder is None:
            try:
                self._embedder = SentenceTransformer(MODEL_EMBED)
            except Exception:
                self._embedder_failed = True
                return None
        return self._embedder

    def run(self, question_normalisee: str, context: "ClientContext") -> dict:
        try:
            pieces = self._match_pieces(question_normalisee, context)
            operations = self._match_operations(question_normalisee, context)
            facteurs = self._match_facteurs(question_normalisee, context)
            variables = self._match_variables(question_normalisee, context)
            intentions = self._match_intentions(question_normalisee, context)

            return {
                "pieces_candidates": pieces,
                "operations_candidates": operations,
                "facteurs_candidates": facteurs,
                "variables_candidates": variables,
                "intentions_candidates": intentions,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "pieces_candidates": [],
                "operations_candidates": [],
                "facteurs_candidates": [],
                "variables_candidates": [],
                "intentions_candidates": [],
                "error": str(exc),
            }

    def _embed(self, text: str) -> np.ndarray | None:
        embedder = self._get_embedder()
        if embedder is None:
            return None
        if text not in self._embed_cache:
            self._embed_cache[text] = embedder.encode(
                text, normalize_embeddings=True
            )
        return self._embed_cache[text]

    def _rrf(self, rank_lexical: int, rank_semantic: int, k: int = RRF_K) -> float:
        return 1.0 / (k + rank_lexical + 1) + 1.0 / (k + rank_semantic + 1)

    def _fuse_rankings(
        self,
        lexical: list[dict],
        semantic: list[dict],
        key_field: str = "value",
    ) -> list[dict]:
        lex_rank = {c[key_field]: i for i, c in enumerate(lexical)}
        sem_rank = {c[key_field]: i for i, c in enumerate(semantic)}
        all_keys = set(lex_rank) | set(sem_rank)
        fused: list[dict] = []
        for key in all_keys:
            rl = lex_rank.get(key, len(lexical) + 10)
            rs = sem_rank.get(key, len(semantic) + 10)
            score = self._rrf(rl, rs)
            meta = next(
                (c for c in lexical if c.get(key_field) == key),
                next((c for c in semantic if c.get(key_field) == key), {}),
            )
            fused.append({**meta, key_field: key, "score": score})
        if not fused and lexical:
            fused = [{**c, "score": c.get("score", 0)} for c in lexical]
        if not fused:
            return []
        max_s = max(c["score"] for c in fused)
        for c in fused:
            c["score"] = round(c["score"] / max_s, 4) if max_s > 0 else 0.0
        fused.sort(key=lambda x: x["score"], reverse=True)
        return fused

    def _score_lexical(self, terme: str, candidats: list[str]) -> list[dict]:
        scored = []
        for c in candidats:
            s1 = fuzz.token_sort_ratio(terme, c) / 100.0
            s2 = fuzz.token_set_ratio(terme, c) / 100.0
            s3 = fuzz.partial_ratio(terme, c) / 100.0
            score = max(s1, s2, s3)
            if score >= 0.45:
                scored.append({"value": c, "score": round(score, 4)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def _score_semantique(
        self, terme: str, candidats: list[tuple[str, str]]
    ) -> list[dict]:
        if not candidats:
            return []
        q_emb = self._embed(terme)
        if q_emb is None:
            return []
        scored = []
        for value, desc in candidats:
            d_emb = self._embed(desc)
            if d_emb is None:
                continue
            sim = float(np.dot(q_emb, d_emb))
            if sim >= 0.25:
                scored.append({"value": value, "score": round(sim, 4)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def _match_technical_codes(
        self, question: str, codes: list[str]
    ) -> list[dict]:
        """Codes techniques (pièces, opérations) : présence exacte uniquement, pas d'embeddings."""
        q = question.lower()
        matched = [
            {"value": code, "score": 1.0}
            for code in codes
            if code.lower() in q
        ]
        return matched

    def _match_pieces(self, question: str, context: "ClientContext") -> list[dict]:
        return self._match_technical_codes(question, list(context.modeles_actifs))

    def _match_operations(self, question: str, context: "ClientContext") -> list[dict]:
        return self._match_technical_codes(
            question, list(context.operations_actives)
        )

    @staticmethod
    def _label_lexical_score(question: str, label: str) -> float:
        t = label.lower()
        q = question.lower()
        if len(t) >= 6 and t in q:
            return 1.0
        if len(t) >= 4 and re.search(
            rf"(?<![a-z0-9_]){re.escape(t)}(?![a-z0-9_])", q
        ):
            return 1.0
        words = re.findall(r"[a-z0-9_]+", q)
        best = 0.0
        for w in words:
            fuzzy = max(
                fuzz.ratio(t, w) / 100.0,
                fuzz.token_sort_ratio(t, w) / 100.0,
            )
            if fuzzy >= FACTEUR_LEXICAL_CERTAIN and abs(len(t) - len(w)) > 1:
                continue
            best = max(best, fuzzy)
        if " " in t:
            best = max(best, fuzz.token_sort_ratio(t, q) / 100.0)
        return best

    def _match_facteurs(self, question: str, context: "ClientContext") -> list[dict]:
        candidats_meta: list[dict] = []
        sem_pairs: list[tuple[str, str]] = []

        for scope, key, cfg in context.iter_facteurs():
            syns = list(cfg.get("synonymes", [])) + [key]
            desc = cfg.get("description", key)
            fuse_key = f"{scope}:{key}"
            for s in syns:
                candidats_meta.append(
                    {"key": key, "operation": scope, "label": s, "fuse_key": fuse_key}
                )
            sem_pairs.append((fuse_key, f"{key} {desc}"))

        raw_lex = []
        for meta in candidats_meta:
            s = self._label_lexical_score(question, meta["label"])
            if s >= FACTEUR_LEXICAL_CERTAIN:
                raw_lex.append({**meta, "value": meta["label"], "score": s})

        by_fuse_lex: dict[str, dict] = {}
        for r in raw_lex:
            fk = r["fuse_key"]
            if fk not in by_fuse_lex or r["score"] > by_fuse_lex[fk]["score"]:
                by_fuse_lex[fk] = {
                    "key": r["key"],
                    "operation": r["operation"],
                    "value": r["value"],
                    "score": round(r["score"], 4),
                    "fuse_key": fk,
                }
        lex = sorted(by_fuse_lex.values(), key=lambda x: x["score"], reverse=True)

        sem_raw = self._score_semantique(question, sem_pairs)
        sem = []
        for s in sem_raw:
            fuse_key = s["value"]
            scope, key = fuse_key.split(":", 1)
            sem.append(
                {
                    "key": key,
                    "operation": scope,
                    "fuse_key": fuse_key,
                    "value": key,
                    "score": s["score"],
                }
            )

        fused = self._fuse_rankings(lex, sem, key_field="fuse_key")
        for c in fused:
            c.pop("fuse_key", None)
        return fused

    def _match_variables(self, question: str, context: "ClientContext") -> list[dict]:
        lex: list[dict] = []
        sem_pairs: list[tuple[str, str]] = []
        for op, key, cfg in context.iter_variables():
            syns = list(cfg.get("synonymes", [])) + [key]
            desc = cfg.get("description", key)
            fuse_key = f"{op}:{key}"
            best = 0.0
            for s in syns:
                best = max(best, self._label_lexical_score(question, s))
            if best >= FACTEUR_LEXICAL_CERTAIN:
                lex.append(
                    {
                        "key": key,
                        "operation": op,
                        "value": key,
                        "score": round(best, 4),
                        "fuse_key": fuse_key,
                    }
                )
            sem_pairs.append((fuse_key, f"{key} {desc}"))
        lex.sort(key=lambda x: x["score"], reverse=True)
        sem_raw = self._score_semantique(question, sem_pairs)
        sem = []
        for s in sem_raw:
            fuse_key = s["value"]
            op, key = fuse_key.split(":", 1)
            sem.append(
                {
                    "key": key,
                    "operation": op,
                    "fuse_key": fuse_key,
                    "value": key,
                    "score": s["score"],
                }
            )
        fused = self._fuse_rankings(lex, sem, key_field="fuse_key")
        for c in fused:
            c.pop("fuse_key", None)
        return fused

    def _match_intentions(self, question: str, context: "ClientContext") -> list[dict]:
        lex: list[dict] = []
        sem_pairs: list[tuple[str, str]] = []
        for key, cfg in context.entites_intentions.items():
            syns = list(cfg.get("synonymes", [])) + [key]
            desc = cfg.get("description", key)
            best = 0.0
            for s in syns:
                best = max(
                    best,
                    fuzz.token_set_ratio(question, s) / 100.0,
                    fuzz.partial_ratio(question, s) / 100.0,
                )
            if best >= 0.45:
                lex.append({"key": key, "value": key, "score": round(best, 4)})
            sem_pairs.append((key, f"{key} {desc}"))
        lex.sort(key=lambda x: x["score"], reverse=True)
        sem_raw = self._score_semantique(question, sem_pairs)
        sem = [{"key": s["value"], "value": s["value"], "score": s["score"]} for s in sem_raw]
        return self._fuse_rankings(lex, sem, key_field="key")


# Seuils exportés pour le pipeline
THRESHOLD_CERTAIN = SCORE_CERTAIN
THRESHOLD_AMBIGUOUS = SCORE_AMBIGUOUS_LOW
