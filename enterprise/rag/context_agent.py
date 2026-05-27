"""
Agent RAG documentaire IndustrIA — ChromaDB local, embeddings locaux.
Recherche par similarité cosinus (SentenceTransformer). Zéro LLM pour la recherche.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import chromadb
from chromadb.utils import embedding_functions
from pypdf import PdfReader

from data.config import OLLAMA_CONFIG
from enterprise.report.formatters import format_value, sanitize_for_pdf

logger = logging.getLogger(__name__)

MANUALS_DIR = os.path.join(str(_ROOT), "data", "manuals")
CHROMA_PERSIST_DIR = os.path.join(str(_ROOT), "data", "chroma_db")
COLLECTION_NAME = "industria_manuals"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
MAX_EXCERPT_CHARS = 500
_MIN_PAGE_TEXT_LEN = 20

# OLLAMA_CONFIG : réservé aux agents LLM de reformulation (agent_6b_reco), pas pour search().
_OLLAMA_MODELS = OLLAMA_CONFIG  # noqa: F841 — import exigé par l'architecture Sprint 5


class ContextAgent:
    """Indexe les manuels PDF et retrouve les pages les plus pertinentes (cosinus pur)."""

    def __init__(self) -> None:
        self._client: chromadb.PersistentClient | None = None
        self._embedding_fn = None
        self._collection = None
        self._init_error: str | None = None

        try:
            os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
            os.makedirs(MANUALS_DIR, exist_ok=True)

            if not os.path.isdir(MANUALS_DIR):
                logger.warning("Dossier manuels absent : %s", MANUALS_DIR)

            self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=EMBEDDING_MODEL,
            )
            self._client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
            self._collection = self._get_or_create_collection()
        except Exception as exc:
            logger.exception("ContextAgent init failed")
            self._init_error = str(exc)

    def _get_or_create_collection(self):
        if self._client is None:
            raise RuntimeError(self._init_error or "Client ChromaDB non initialisé")
        return self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def _reset_collection(self) -> None:
        """Supprime et recrée la collection (ChromaDB corrompu ou réindexation forcée)."""
        if self._client is None:
            return
        try:
            self._client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        self._collection = self._get_or_create_collection()

    @staticmethod
    def _safe_chunk_id(filename: str, page: int) -> str:
        base = os.path.splitext(filename)[0]
        safe = re.sub(r"[^\w\-]", "_", base)
        return f"{safe}_page_{page}"

    @staticmethod
    def _format_excerpt(text: str) -> str:
        cleaned = sanitize_for_pdf(format_value(text))
        if len(cleaned) > MAX_EXCERPT_CHARS:
            return cleaned[: MAX_EXCERPT_CHARS - 3] + "..."
        return cleaned

    @staticmethod
    def _format_citation(source: str, page: int) -> str:
        src = format_value(source)
        pg = format_value(page)
        return f"{src} — page {pg}"

    def index_manuals(self, force_reindex: bool = False) -> dict:
        """
        Indexe tous les PDFs de ``data/manuals/`` (1 chunk = 1 page).

        Returns:
            dict: ``indexed``, ``skipped``, ``files``, ``error``.
        """
        result = {
            "indexed": 0,
            "skipped": 0,
            "files": [],
            "error": None,
        }
        try:
            if self._init_error:
                result["error"] = self._init_error
                return result

            if force_reindex:
                self._reset_collection()
            elif self._collection is not None:
                try:
                    if self._collection.count() > 0:
                        result["files"] = self._list_pdf_files()
                        logger.info(
                            "Collection %s déjà indexée (%s chunks), skip",
                            COLLECTION_NAME,
                            self._collection.count(),
                        )
                        return result
                except Exception as exc:
                    logger.warning("Collection corrompue, réindexation : %s", exc)
                    self._reset_collection()

            pdf_files = self._list_pdf_files()
            result["files"] = pdf_files

            if not pdf_files:
                logger.warning("Aucun PDF dans %s", MANUALS_DIR)
                return result

            ids: list[str] = []
            documents: list[str] = []
            metadatas: list[dict[str, Any]] = []

            for pdf_name in pdf_files:
                pdf_path = os.path.join(MANUALS_DIR, pdf_name)
                pages = self._extract_pages(pdf_path)
                total_pages = len(pages)

                for page_info in pages:
                    if page_info.get("empty"):
                        result["skipped"] += 1
                        continue

                    page_num = int(page_info["page"])
                    text = str(page_info.get("text", ""))
                    chunk_id = self._safe_chunk_id(pdf_name, page_num)

                    ids.append(chunk_id)
                    documents.append(text)
                    metadatas.append({
                        "source": pdf_name,
                        "page": page_num,
                        "total_pages": total_pages,
                    })
                    result["indexed"] += 1

            if ids and self._collection is not None:
                batch_size = 100
                for i in range(0, len(ids), batch_size):
                    self._collection.upsert(
                        ids=ids[i : i + batch_size],
                        documents=documents[i : i + batch_size],
                        metadatas=metadatas[i : i + batch_size],
                    )

            return result
        except Exception as exc:
            logger.exception("index_manuals failed")
            result["error"] = str(exc)
            try:
                self._reset_collection()
            except Exception:
                pass
            return result

    def search(
        self,
        query: str,
        n_results: int = 3,
        min_relevance: float = 0.3,
    ) -> dict:
        """
        Recherche par similarité cosinus dans ChromaDB.

        Returns:
            dict: ``results``, ``query``, ``n_found``, ``error``.
        """
        out = {
            "results": [],
            "query": format_value(query),
            "n_found": 0,
            "error": None,
        }
        try:
            if self._init_error:
                out["error"] = self._init_error
                return out

            q = (query or "").strip()
            if not q:
                out["error"] = "Query vide"
                return out

            out["query"] = q

            if self._collection is None:
                out["error"] = "Collection ChromaDB non disponible"
                return out

            try:
                count = self._collection.count()
            except Exception as exc:
                logger.warning("Lecture collection échouée, réindexation : %s", exc)
                self._reset_collection()
                count = 0

            if count == 0:
                index_result = self.index_manuals(force_reindex=False)
                if index_result.get("error"):
                    out["error"] = format_value(index_result["error"])
                    return out
                try:
                    count = self._collection.count()
                except Exception as exc:
                    out["error"] = str(exc)
                    return out
                if count == 0:
                    return out

            n_query = max(1, int(n_results))
            try:
                raw = self._collection.query(
                    query_texts=[q],
                    n_results=min(n_query * 3, max(count, 1)),
                    include=["documents", "metadatas", "distances"],
                )
            except Exception as exc:
                logger.warning("Query ChromaDB échouée, réindexation auto : %s", exc)
                self.index_manuals(force_reindex=True)
                try:
                    raw = self._collection.query(
                        query_texts=[q],
                        n_results=min(n_query * 3, max(self._collection.count(), 1)),
                        include=["documents", "metadatas", "distances"],
                    )
                except Exception as exc2:
                    out["error"] = str(exc2)
                    return out

            results = self._parse_query_results(raw, min_relevance, n_query)
            out["results"] = results
            out["n_found"] = len(results)
            return out
        except Exception as exc:
            logger.exception("search failed")
            out["error"] = str(exc)
            return out

    def search_for_anomaly(
        self,
        target_column: str,
        priority: str,
        causes: list | None = None,
    ) -> dict:
        """
        Construit une requête depuis le contexte d'anomalie et appelle ``search()``.
        """
        try:
            labels: list[str] = []
            if causes:
                for item in causes[:3]:
                    if isinstance(item, dict) and item.get("label"):
                        labels.append(str(item["label"]))

            query = (
                f"anomalie {format_value(target_column)} {format_value(priority)} "
                f"{' '.join(labels)}"
            ).strip()

            return self.search(query, n_results=3, min_relevance=0.3)
        except Exception as exc:
            logger.exception("search_for_anomaly failed")
            return {
                "results": [],
                "query": format_value(target_column),
                "n_found": 0,
                "error": str(exc),
            }

    def get_collection_stats(self) -> dict:
        """Statistiques de la collection indexée."""
        stats = {
            "total_chunks": 0,
            "files_indexed": [],
            "collection_name": COLLECTION_NAME,
            "persist_dir": CHROMA_PERSIST_DIR,
        }
        try:
            if self._init_error or self._collection is None:
                return stats

            stats["total_chunks"] = int(self._collection.count())
            if stats["total_chunks"] > 0:
                peek = self._collection.get(
                    limit=min(stats["total_chunks"], 5000),
                    include=["metadatas"],
                )
                metas = peek.get("metadatas") or []
                sources = set()
                for meta in metas:
                    if isinstance(meta, dict) and meta.get("source"):
                        sources.add(str(meta["source"]))
                stats["files_indexed"] = sorted(sources)
            return stats
        except Exception as exc:
            logger.exception("get_collection_stats failed")
            stats["files_indexed"] = []
            return stats

    def _list_pdf_files(self) -> list[str]:
        if not os.path.isdir(MANUALS_DIR):
            return []
        return sorted(
            f
            for f in os.listdir(MANUALS_DIR)
            if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(MANUALS_DIR, f))
        )

    def _extract_pages(self, pdf_path: str) -> list[dict]:
        """
        Extrait le texte page par page via pypdf.

        Returns:
            list: ``{"page": int, "text": str, "empty": bool}`` (page base 1).
        """
        pages_out: list[dict] = []
        try:
            reader = PdfReader(pdf_path)
            for i, page in enumerate(reader.pages):
                page_num = i + 1
                try:
                    raw_text = page.extract_text() or ""
                except Exception:
                    raw_text = ""
                text = raw_text.strip()
                empty = text == "" or len(text) < _MIN_PAGE_TEXT_LEN
                pages_out.append({
                    "page": page_num,
                    "text": text,
                    "empty": empty,
                })
        except Exception as exc:
            logger.warning("Extraction PDF échouée %s : %s", pdf_path, exc)
        return pages_out

    def _parse_query_results(
        self,
        raw: dict,
        min_relevance: float,
        n_results: int,
    ) -> list[dict]:
        """Convertit la réponse ChromaDB en résultats triés par pertinence."""
        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]

        parsed: list[dict] = []
        for doc, meta, dist in zip(documents, metadatas, distances):
            try:
                distance = float(dist)
            except (TypeError, ValueError):
                distance = 1.0

            relevance = max(0.0, min(1.0, 1.0 - distance))
            if relevance < float(min_relevance):
                continue

            meta = meta if isinstance(meta, dict) else {}
            source = format_value(meta.get("source", "N/A"))
            page_raw = meta.get("page", "N/A")
            try:
                page = int(page_raw)
            except (TypeError, ValueError):
                page = page_raw

            parsed.append({
                "text": self._format_excerpt(doc or ""),
                "source": source,
                "page": page,
                "relevance": round(relevance, 4),
                "citation": self._format_citation(source, page),
            })

        parsed.sort(key=lambda r: r["relevance"], reverse=True)
        return parsed[:n_results]
