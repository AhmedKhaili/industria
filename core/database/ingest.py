"""
Ingestion CSV simulateur IndustrIA vers TimescaleDB (hypertables).
Relançable : déduplication via ON CONFLICT (timestamp, piece_id).
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from psycopg2 import sql

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "industria123",
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BATCH_SIZE = 500

EBAUCHE_TABLE = "ebauche_data"
FILAGE_TABLE = "filage_data"
FORMAGE_TABLE = "formage_data"

EBAUCHE_COLUMNS = [
    "timestamp",
    "piece_id",
    "vitesse_coupe",
    "debit_coupe",
    "poids",
    "lubrifiant",
    "anomalie",
    "score_anomalie",
]

FILAGE_COLUMNS = [
    "timestamp",
    "piece_id",
    "modele",
    "inducteur_1",
    "inducteur_2",
    "lvdt_moyenne",
    "pyrometre",
    "frette",
    "anomalie",
    "score_anomalie",
]

FORMAGE_COLUMNS = [
    "timestamp",
    "piece_id",
    "modele",
    "verin_1",
    "verin_2",
    "fouloir",
    "four_1",
    "four_2",
    "four_3",
    "four_4",
    "matrice",
    "lvdt_formage",
    "anomalie",
    "score_anomalie",
]


def _regime_to_anomalie(series: pd.Series) -> pd.Series:
    def one(val: object) -> bool:
        if pd.isna(val):
            return False
        s = str(val).strip().lower()
        return s not in ("normal", "ok", "")

    return series.map(one)


def _ensure_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "timestamp" in out.columns and out["timestamp"].notna().any():
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    else:
        ts = datetime.now(timezone.utc)
        out["timestamp"] = ts
    return out


def _fill_defaults(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.reindex(columns=columns)
    if "anomalie" in columns:
        out["anomalie"] = out["anomalie"].fillna(False).astype(bool)
    if "score_anomalie" in columns:
        out["score_anomalie"] = pd.to_numeric(out["score_anomalie"], errors="coerce").fillna(
            0.0
        )
    return out


def _to_db_tuples(df: pd.DataFrame, columns: list[str]) -> list[tuple]:
    """Convertit le DataFrame en tuples pour psycopg2 (None à la place des NaN)."""
    out = df[columns].copy()
    for c in out.columns:
        if out[c].dtype == bool or str(out[c].dtype) == "boolean":
            out[c] = out[c].astype(object).where(out[c].notna(), None)
        else:
            out[c] = out[c].replace({np.nan: None})
    rows: list[tuple] = []
    for rec in out.itertuples(index=False, name=None):
        row = []
        for v in rec:
            if v is not None and isinstance(v, pd.Timestamp):
                row.append(v.to_pydatetime())
            else:
                row.append(v)
        rows.append(tuple(row))
    return rows


def _lvdt_reel_mean(df: pd.DataFrame, pattern: re.Pattern[str]) -> pd.Series:
    cols = [c for c in df.columns if pattern.match(c)]
    if not cols:
        return pd.Series(np.nan, index=df.index)
    return df[cols].apply(pd.to_numeric, errors="coerce").mean(axis=1)


def prepare_ebauche(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    df = pd.DataFrame()
    if "horodatage" in raw.columns:
        df["timestamp"] = raw["horodatage"]
    if "modele" in raw.columns:
        df["piece_id"] = raw["modele"].astype(str)
    if "vitesse_coupe_m_min" in raw.columns:
        df["vitesse_coupe"] = pd.to_numeric(raw["vitesse_coupe_m_min"], errors="coerce")
    if "debit_coupe_l_min" in raw.columns:
        df["debit_coupe"] = pd.to_numeric(raw["debit_coupe_l_min"], errors="coerce")
    if "poids_piece_process_g" in raw.columns:
        df["poids"] = pd.to_numeric(raw["poids_piece_process_g"], errors="coerce")
    if "epaisseur_lubrifiant_process_mm" in raw.columns:
        df["lubrifiant"] = pd.to_numeric(raw["epaisseur_lubrifiant_process_mm"], errors="coerce")
    if "regime_anomalie" in raw.columns:
        df["anomalie"] = _regime_to_anomalie(raw["regime_anomalie"])
    df = _ensure_timestamp(df)
    df = _fill_defaults(df, EBAUCHE_COLUMNS)
    return df


def prepare_filage(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    df = pd.DataFrame()
    if "horodatage" in raw.columns:
        df["timestamp"] = raw["horodatage"]
    if "numero_pastille" in raw.columns:
        df["piece_id"] = raw["numero_pastille"].apply(lambda x: str(x) if pd.notna(x) else None)
    if "machine" in raw.columns:
        df["modele"] = raw["machine"].astype(str)
    if "inducteur_puissance_1_reel_kW" in raw.columns:
        df["inducteur_1"] = pd.to_numeric(raw["inducteur_puissance_1_reel_kW"], errors="coerce")
    if "inducteur_puissance_2_reel_kW" in raw.columns:
        df["inducteur_2"] = pd.to_numeric(raw["inducteur_puissance_2_reel_kW"], errors="coerce")
    lvdt_pat = re.compile(r"^lvdt_\d{2}_reel_mm$")
    df["lvdt_moyenne"] = _lvdt_reel_mean(raw, lvdt_pat)
    if "pyrometre_inducteur_1_C" in raw.columns and "pyrometre_inducteur_2_C" in raw.columns:
        a = pd.to_numeric(raw["pyrometre_inducteur_1_C"], errors="coerce")
        b = pd.to_numeric(raw["pyrometre_inducteur_2_C"], errors="coerce")
        df["pyrometre"] = (a + b) / 2.0
    elif "pyrometre_inducteur_1_C" in raw.columns:
        df["pyrometre"] = pd.to_numeric(raw["pyrometre_inducteur_1_C"], errors="coerce")
    if "frette_int_reel_C" in raw.columns and "frette_ext_reel_C" in raw.columns:
        a = pd.to_numeric(raw["frette_int_reel_C"], errors="coerce")
        b = pd.to_numeric(raw["frette_ext_reel_C"], errors="coerce")
        df["frette"] = (a + b) / 2.0
    elif "frette_int_reel_C" in raw.columns:
        df["frette"] = pd.to_numeric(raw["frette_int_reel_C"], errors="coerce")
    if "regime_anomalie" in raw.columns:
        df["anomalie"] = _regime_to_anomalie(raw["regime_anomalie"])
    df = _ensure_timestamp(df)
    df = _fill_defaults(df, FILAGE_COLUMNS)
    return df


def _formage_modele(machine: object) -> str | None:
    if pd.isna(machine):
        return None
    m = re.search(r"M156[56]", str(machine))
    return m.group(0) if m else None


def prepare_formage(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    df = pd.DataFrame()
    if "horodatage" in raw.columns:
        df["timestamp"] = raw["horodatage"]
    if "numero_programme" in raw.columns:
        df["piece_id"] = raw["numero_programme"].astype(str)
    if "machine" in raw.columns:
        df["modele"] = raw["machine"].map(_formage_modele)
    if "pression_verin_1_reel_bars" in raw.columns:
        df["verin_1"] = pd.to_numeric(raw["pression_verin_1_reel_bars"], errors="coerce")
    if "pression_verin_2_reel_bars" in raw.columns:
        df["verin_2"] = pd.to_numeric(raw["pression_verin_2_reel_bars"], errors="coerce")
    if "pression_fouloir_reel_bars" in raw.columns:
        df["fouloir"] = pd.to_numeric(raw["pression_fouloir_reel_bars"], errors="coerce")
    if "four_gauche_1_reel_C" in raw.columns:
        df["four_1"] = pd.to_numeric(raw["four_gauche_1_reel_C"], errors="coerce")
    if "four_gauche_2_reel_C" in raw.columns:
        df["four_2"] = pd.to_numeric(raw["four_gauche_2_reel_C"], errors="coerce")
    if "four_droit_1_reel_C" in raw.columns:
        df["four_3"] = pd.to_numeric(raw["four_droit_1_reel_C"], errors="coerce")
    if "four_droit_2_reel_C" in raw.columns:
        df["four_4"] = pd.to_numeric(raw["four_droit_2_reel_C"], errors="coerce")
    df["matrice"] = np.nan
    lvdt_pat = re.compile(r".*_lvdt_reel_mm$")
    df["lvdt_formage"] = _lvdt_reel_mean(raw, lvdt_pat)
    if "regime_anomalie" in raw.columns:
        df["anomalie"] = _regime_to_anomalie(raw["regime_anomalie"])
    df = _ensure_timestamp(df)
    df = _fill_defaults(df, FORMAGE_COLUMNS)
    return df


def ensure_dedup_indexes(cur) -> None:
    stmts = [
        (
            "ebauche_data",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ebauche_data_ts_piece "
            "ON ebauche_data (timestamp, piece_id);",
        ),
        (
            "filage_data",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_filage_data_ts_piece "
            "ON filage_data (timestamp, piece_id);",
        ),
        (
            "formage_data",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_formage_data_ts_piece "
            "ON formage_data (timestamp, piece_id);",
        ),
    ]
    for _, ddl in stmts:
        cur.execute(ddl)


def build_insert_statement(table: str, columns: list[str]) -> sql.Composed:
    cols = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    placeholders = sql.SQL(", ").join([sql.Placeholder() for _ in columns])
    return (
        sql.SQL("INSERT INTO {} ({}) VALUES ({}) ").format(
            sql.Identifier(table),
            cols,
            placeholders,
        )
        + sql.SQL("ON CONFLICT (timestamp, piece_id) DO NOTHING")
    )


def count_rows(cur, table: str) -> int:
    cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
    return int(cur.fetchone()[0])


def insert_with_batches(
    cur,
    conn,
    table: str,
    columns: list[str],
    rows: list[tuple],
    label: str,
) -> tuple[int, int]:
    """
    Insère par lots avec executemany ; en cas d'échec d'un lot, insertion ligne par ligne.
    Utilise des SAVEPOINT pour ne pas invalider toute la transaction PostgreSQL.
    Retourne (nombre de lignes réellement insérées, nombre de lignes en erreur ignorées).
    """
    if not rows:
        return 0, 0

    before = count_rows(cur, table)
    stmt = build_insert_statement(table, columns)
    query = stmt.as_string(conn)
    errors = 0
    total = len(rows)

    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        chunk = rows[start:end]
        sp_batch = f"ingest_batch_{start}"
        print(f"📥 Insertion {label} : {end} lignes...")
        try:
            cur.execute(f"SAVEPOINT {sp_batch}")
            cur.executemany(query, chunk)
            cur.execute(f"RELEASE SAVEPOINT {sp_batch}")
        except psycopg2.Error as e:
            cur.execute(f"ROLLBACK TO SAVEPOINT {sp_batch}")
            print(
                f"⚠️  Lot {label} [{start}:{end}] : échec executemany ({e}), reprise ligne par ligne.",
                file=sys.stderr,
            )
            for i, row in enumerate(chunk):
                sp_row = f"ingest_row_{start}_{i}"
                try:
                    cur.execute(f"SAVEPOINT {sp_row}")
                    cur.execute(query, row)
                    cur.execute(f"RELEASE SAVEPOINT {sp_row}")
                except psycopg2.Error as row_err:
                    cur.execute(f"ROLLBACK TO SAVEPOINT {sp_row}")
                    errors += 1
                    print(
                        f"Ligne ignorée ({label}): {row_err} | row≈{row[:4]}...",
                        file=sys.stderr,
                    )

    conn.commit()
    after = count_rows(cur, table)
    inserted = after - before
    print(f"✅ {label} : {inserted} lignes insérées")
    return inserted, errors


def ingest() -> None:
    jobs = [
        (
            DATA_DIR / "ebauche.csv",
            EBAUCHE_TABLE,
            EBAUCHE_COLUMNS,
            prepare_ebauche,
            "ebauche_data",
        ),
        (
            DATA_DIR / "filage.csv",
            FILAGE_TABLE,
            FILAGE_COLUMNS,
            prepare_filage,
            "filage_data",
        ),
        (
            DATA_DIR / "formage.csv",
            FORMAGE_TABLE,
            FORMAGE_COLUMNS,
            prepare_formage,
            "formage_data",
        ),
    ]

    totals: dict[str, int] = {}
    error_counts: dict[str, int] = {}

    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        with conn.cursor() as cur:
            ensure_dedup_indexes(cur)
            conn.commit()

            for path, table, columns, prepare_fn, label in jobs:
                if not path.is_file():
                    print(f"❌ Fichier manquant : {path}", file=sys.stderr)
                    sys.exit(1)
                df = prepare_fn(path)
                rows = _to_db_tuples(df, columns)
                inserted, errs = insert_with_batches(cur, conn, table, columns, rows, label)
                totals[label] = inserted
                error_counts[label] = errs

        print("")
        print("—— Récapitulatif ——")
        for label in ("ebauche_data", "filage_data", "formage_data"):
            n = totals.get(label, 0)
            e = error_counts.get(label, 0)
            extra = f" ({e} lignes ignorées pour erreur)" if e else ""
            print(f"  • {label} : {n} lignes insérées{extra}")
    except psycopg2.OperationalError as e:
        print(f"❌ Connexion impossible : {e}", file=sys.stderr)
        sys.exit(1)
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        print(f"❌ Erreur PostgreSQL : {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    ingest()
