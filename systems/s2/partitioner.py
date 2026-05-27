"""
Partitionnement CSV → Parquet par opération et pièce.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

MANIFEST_NAME = "_manifest.json"


def _project_root(yaml_path: str) -> Path:
    return Path(yaml_path).resolve().parents[2]


def csv_path(yaml_path: str, context: "ClientContext") -> Path:
    rel = context.raw["dataset"].get("fichier", "")
    return _project_root(yaml_path) / rel


def client_slug(context: "ClientContext") -> str:
    """Ex. « LISI Aerospace » → lisi_aerospace (depuis context.raw['client']['nom'])."""
    nom = (context.raw.get("client") or {}).get("nom") or "client"
    normalized = unicodedata.normalize("NFKD", str(nom))
    ascii_nom = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_nom.lower()).strip("_")
    return slug or "client"


def cache_dir(yaml_path: str, context: "ClientContext | None" = None) -> Path:
    if context is None:
        from systems.s1.client_context import ClientContext

        context = ClientContext.load(yaml_path)
    slug = client_slug(context)
    return _project_root(yaml_path) / "data" / "cache" / slug


def _manifest_path(cache: Path) -> Path:
    return cache / MANIFEST_NAME


def _needs_rebuild(csv: Path, cache: Path) -> bool:
    manifest = _manifest_path(cache)
    if not manifest.is_file():
        return True
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    return float(data.get("csv_mtime", 0)) < csv.stat().st_mtime


def _write_manifest(csv: Path, cache: Path, partition_count: int) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    _manifest_path(cache).write_text(
        json.dumps(
            {
                "csv_mtime": csv.stat().st_mtime,
                "csv_path": str(csv),
                "partition_count": partition_count,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def ensure_partitions(
    yaml_path: str,
    context: "ClientContext",
    *,
    force: bool = False,
) -> dict:
    """
    Crée ou met à jour data/cache/{client_slug}/{OPERATION}/{PIECE}.parquet si le CSV a changé.
    """
    try:
        csv = csv_path(yaml_path, context)
        if not csv.is_file():
            return {"error": f"CSV introuvable : {csv}", "partition_count": 0}

        cache = cache_dir(yaml_path, context)
        if not force and not _needs_rebuild(csv, cache):
            count = sum(1 for _ in cache.rglob("*.parquet"))
            return {"error": None, "partition_count": count, "rebuilt": False}

        col_piece = context.colonnes.get("piece", "Designation Reference")
        col_op = context.colonnes.get("operation", "Operation")
        sep = context.raw["dataset"].get("separateur", ";")
        encoding = context.raw["dataset"].get("encoding", "utf-8")

        if cache.exists() and force:
            for p in cache.rglob("*.parquet"):
                p.unlink()

        cache.mkdir(parents=True, exist_ok=True)
        buffers: dict[tuple[str, str], list[pd.DataFrame]] = {}
        partition_count = 0

        for chunk in pd.read_csv(
            csv,
            sep=sep,
            encoding=encoding,
            chunksize=250_000,
            low_memory=False,
        ):
            if col_piece not in chunk.columns or col_op not in chunk.columns:
                return {
                    "error": f"Colonnes partition manquantes : {col_piece}, {col_op}",
                    "partition_count": 0,
                }
            chunk = chunk[chunk[col_op].isin(context.operations_actives)]
            chunk = chunk[chunk[col_piece].notna()]
            for (op, piece), group in chunk.groupby([col_op, col_piece], dropna=True):
                key = (str(op), str(piece))
                buffers.setdefault(key, []).append(group)

        for (op, piece), parts in buffers.items():
            out_dir = cache / str(op)
            out_dir.mkdir(parents=True, exist_ok=True)
            df = pd.concat(parts, ignore_index=True)
            out_file = out_dir / f"{piece}.parquet"
            df.to_parquet(out_file, index=False)
            partition_count += 1

        _write_manifest(csv, cache, partition_count)
        return {"error": None, "partition_count": partition_count, "rebuilt": True}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "partition_count": 0}


def count_rows_vague_scope(yaml_path: str, context: "ClientContext") -> dict:
    """Compte les lignes utiles (opérations actives) sans charger tout en mémoire."""
    try:
        part = ensure_partitions(yaml_path, context)
        if part.get("error"):
            return {"error": part["error"], "row_count": 0}

        cache = cache_dir(yaml_path, context)
        total = 0
        for path in cache.rglob("*.parquet"):
            if path.name.startswith("_"):
                continue
            total += pq.read_metadata(path).num_rows
        return {"error": None, "row_count": total}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "row_count": 0}
