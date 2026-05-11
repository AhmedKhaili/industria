"""
Initialisation TimescaleDB pour IndustrIA — tables et hypertables des processus simulés.
Relançable sans erreur (IF NOT EXISTS / if_not_exists).
"""

from __future__ import annotations

import sys

import psycopg2
from psycopg2 import sql

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "industria123",
}

TABLES_DDL = {
    "ebauche_data": """
        CREATE TABLE IF NOT EXISTS ebauche_data (
            timestamp TIMESTAMPTZ NOT NULL,
            piece_id TEXT,
            vitesse_coupe DOUBLE PRECISION,
            debit_coupe DOUBLE PRECISION,
            poids DOUBLE PRECISION,
            lubrifiant DOUBLE PRECISION,
            anomalie BOOLEAN,
            score_anomalie DOUBLE PRECISION
        );
    """,
    "filage_data": """
        CREATE TABLE IF NOT EXISTS filage_data (
            timestamp TIMESTAMPTZ NOT NULL,
            piece_id TEXT,
            modele TEXT,
            inducteur_1 DOUBLE PRECISION,
            inducteur_2 DOUBLE PRECISION,
            lvdt_moyenne DOUBLE PRECISION,
            pyrometre DOUBLE PRECISION,
            frette DOUBLE PRECISION,
            anomalie BOOLEAN,
            score_anomalie DOUBLE PRECISION
        );
    """,
    "formage_data": """
        CREATE TABLE IF NOT EXISTS formage_data (
            timestamp TIMESTAMPTZ NOT NULL,
            piece_id TEXT,
            modele TEXT,
            verin_1 DOUBLE PRECISION,
            verin_2 DOUBLE PRECISION,
            fouloir DOUBLE PRECISION,
            four_1 DOUBLE PRECISION,
            four_2 DOUBLE PRECISION,
            four_3 DOUBLE PRECISION,
            four_4 DOUBLE PRECISION,
            matrice DOUBLE PRECISION,
            lvdt_formage DOUBLE PRECISION,
            anomalie BOOLEAN,
            score_anomalie DOUBLE PRECISION
        );
    """,
}


def create_hypertable_sql(table_name: str) -> sql.Composed:
    return sql.SQL(
        "SELECT create_hypertable({table}, {time_col}, "
        "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);"
    ).format(
        table=sql.Literal(table_name),
        time_col=sql.Literal("timestamp"),
    )


def create_index_sql(table_name: str) -> sql.Composed:
    index_name = f"idx_{table_name}_timestamp_piece_id"
    return sql.SQL(
        "CREATE INDEX IF NOT EXISTS {idx} ON {tbl} (timestamp DESC, piece_id);"
    ).format(
        idx=sql.Identifier(index_name),
        tbl=sql.Identifier(table_name),
    )


def setup() -> None:
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True
        with conn.cursor() as cur:
            for table_name in TABLES_DDL:
                try:
                    cur.execute(TABLES_DDL[table_name])
                    print(f"✅ Table {table_name} créée")
                except psycopg2.Error as e:
                    print(f"❌ Échec création table {table_name}: {e}", file=sys.stderr)
                    raise

                try:
                    cur.execute(create_hypertable_sql(table_name))
                    print(f"✅ Hypertable {table_name} configurée")
                except psycopg2.Error as e:
                    print(
                        f"❌ Échec hypertable {table_name}: {e}",
                        file=sys.stderr,
                    )
                    raise

                try:
                    cur.execute(create_index_sql(table_name))
                    print(f"✅ Index (timestamp DESC, piece_id) sur {table_name}")
                except psycopg2.Error as e:
                    print(
                        f"❌ Échec index sur {table_name}: {e}",
                        file=sys.stderr,
                    )
                    raise

        print("🚀 IndustrIA DB prête !")
    except psycopg2.OperationalError as e:
        print(
            f"❌ Connexion TimescaleDB impossible ({DB_CONFIG['host']}:{DB_CONFIG['port']}): {e}",
            file=sys.stderr,
        )
        sys.exit(1)
    except psycopg2.Error as e:
        print(f"❌ Erreur PostgreSQL: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    setup()
