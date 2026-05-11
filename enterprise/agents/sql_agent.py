"""
Agent Text-to-SQL sécurisé pour IndustrIA (TimescaleDB + Ollama local).
"""

from __future__ import annotations

import re
from typing import Any

import psycopg2
import sqlglot
from ollama import Client
from psycopg2.extras import RealDictCursor
from sqlglot import exp

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "industria123",
}

OLLAMA_HOST = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5-coder:14b"
OLLAMA_TIMEOUT_S = 30.0

HYPERTABLES = ("ebauche_data", "filage_data", "formage_data")

SYSTEM_PROMPT = (
    "Tu es un expert SQL TimescaleDB. Tu génères UNIQUEMENT "
    "du SQL en lecture seule. Utilise time_bucket() pour les "
    "agrégations temporelles. Réponds UNIQUEMENT avec la requête "
    "SQL, sans markdown, sans explication."
)

SYSTEM_PROMPT_RETRY = (
    "Tu génères UNE SEULE requête SELECT PostgreSQL valide, en lecture seule, "
    "sans markdown ni texte autour. Tables : ebauche_data, filage_data, formage_data. "
    "Colonne temps : timestamp (TIMESTAMPTZ)."
)

FORBIDDEN_SQL_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "GRANT",
    "REVOKE",
    "TRUNCATE",
)

_DANGEROUS_EXP_TYPES: tuple[type, ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Grant,
    exp.Revoke,
    exp.TruncateTable,
    exp.Command,
)
if hasattr(exp, "Merge"):
    _DANGEROUS_EXP_TYPES = _DANGEROUS_EXP_TYPES + (getattr(exp, "Merge"),)


class SQLSecurityError(Exception):
    """Requête SQL rejetée par la validation de sécurité."""


def strip_markdown_sql(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _contains_forbidden_keyword_prose(sql_upper: str) -> str | None:
    """Détecte les mots-clés DDL/DML en tant que tokens SQL (évite les faux positifs partiels)."""
    pattern = r"\b(" + "|".join(re.escape(k) for k in FORBIDDEN_SQL_KEYWORDS) + r")\b"
    m = re.search(pattern, sql_upper)
    return m.group(1) if m else None


def validate_readonly_sql(sql_text: str) -> exp.Expression:
    """
    Parse avec sqlglot, vérifie une seule instruction et l'absence d'opérations d'écriture.
    """
    cleaned = strip_markdown_sql(sql_text)
    if not cleaned:
        raise SQLSecurityError("Requête SQL vide après nettoyage.")

    kw = _contains_forbidden_keyword_prose(cleaned.upper())
    if kw:
        raise SQLSecurityError(f"Mot-clé interdit détecté : {kw}")

    try:
        statements = sqlglot.parse(cleaned, dialect="postgres")
    except sqlglot.errors.ParseError as e:
        raise SQLSecurityError(f"SQL non analysable : {e}") from e

    if not statements:
        raise SQLSecurityError("Aucune instruction SQL reconnue.")
    if len(statements) > 1:
        raise SQLSecurityError("Plusieurs instructions SQL ne sont pas autorisées.")

    parsed = statements[0]
    for node in parsed.walk():
        if isinstance(node, _DANGEROUS_EXP_TYPES):
            raise SQLSecurityError(f"Opération interdite dans l'arbre SQL : {type(node).__name__}")

    if not isinstance(parsed, (exp.Select, exp.Union)):
        raise SQLSecurityError("Seules les requêtes SELECT (éventuellement UNION) sont autorisées.")

    return parsed


def ensure_limit(sql_text: str, max_rows: int = 100) -> str:
    """Ajoute LIMIT si absent (sinon laisse la requête inchangée)."""
    parsed = validate_readonly_sql(sql_text)
    if parsed.args.get("limit") is None:
        limited = parsed.limit(max_rows)
        return limited.sql(dialect="postgres")
    return parsed.sql(dialect="postgres")


def fetch_schema_text(conn) -> str:
    """ÉTAPE A — Schéma dynamique via information_schema."""
    q = """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name IN %s
        ORDER BY table_name, ordinal_position;
    """
    lines: list[str] = []
    with conn.cursor() as cur:
        cur.execute(q, (HYPERTABLES,))
        rows = cur.fetchall()
    current: str | None = None
    for table_name, column_name, data_type in rows:
        if table_name != current:
            current = table_name
            lines.append(f"\nTable {table_name}:")
        lines.append(f"  - {column_name}: {data_type}")
    return "\n".join(lines).strip() or "(aucune colonne trouvée)"


def _ollama_client() -> Client:
    return Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT_S)


def generate_sql(schema_text: str, question: str, *, retry: bool) -> str:
    """ÉTAPE B — Génération via Ollama."""
    client = _ollama_client()
    system = SYSTEM_PROMPT_RETRY if retry else SYSTEM_PROMPT
    user_content = f"Schéma des tables :\n{schema_text}\n\nQuestion :\n{question}"
    resp = client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        options={
            "num_ctx": 8000,
            "temperature": 0.1,
        },
    )
    content = resp.message.content if resp.message else ""
    return (content or "").strip()


def execute_readonly(
    conn,
    sql_text: str,
) -> list[dict[str, Any]]:
    """ÉTAPE D — transaction lecture seule, timeout 5s, résultats en dicts."""
    final_sql = ensure_limit(sql_text, 100)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL statement_timeout = '5000ms'")
        try:
            cur.execute(final_sql)
            rows = cur.fetchall()
        finally:
            cur.execute("ROLLBACK")

    return [dict(r) for r in rows]


class SQLAgent:
    """Agent question (FR) → données TimescaleDB via Ollama + validation sqlglot."""

    def __init__(self) -> None:
        self._schema_cache: str | None = None

    def _get_schema(self, conn) -> str:
        if self._schema_cache is None:
            self._schema_cache = fetch_schema_text(conn)
        return self._schema_cache

    def ask(self, question: str) -> dict[str, Any]:
        """
        Exécute le pipeline A→E et retourne :
        { "sql": str|None, "data": [...], "row_count": int, "error": str|None }
        """
        result: dict[str, Any] = {
            "sql": None,
            "data": [],
            "row_count": 0,
            "error": None,
        }
        if not question or not question.strip():
            result["error"] = "Question vide."
            return result

        conn = None
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            schema = self._get_schema(conn)

            sql_out: str | None = None
            last_validation_error: str | None = None

            for attempt, use_retry_prompt in enumerate((False, True)):
                raw = generate_sql(schema, question, retry=use_retry_prompt)
                candidate = strip_markdown_sql(raw)
                try:
                    sql_out = ensure_limit(candidate, 100)
                    last_validation_error = None
                    break
                except SQLSecurityError as e:
                    last_validation_error = str(e)
                    if attempt == 1:
                        result["error"] = (
                            f"SQL invalide ou non sécurisé après nouvelle tentative : {last_validation_error}"
                        )
                        result["sql"] = candidate or None
                        return result
                except Exception as e:
                    last_validation_error = str(e)
                    if attempt == 1:
                        result["error"] = f"Erreur de validation SQL : {last_validation_error}"
                        result["sql"] = candidate or None
                        return result

            if sql_out is None:
                result["error"] = last_validation_error or "Échec de génération SQL."
                return result

            result["sql"] = sql_out
            data = execute_readonly(conn, sql_out)
            result["data"] = data
            result["row_count"] = len(data)
            return result

        except psycopg2.Error as e:
            result["error"] = f"Erreur PostgreSQL : {e}"
            return result
        except Exception as e:
            result["error"] = f"Erreur inattendue : {e}"
            return result
        finally:
            if conn is not None:
                conn.close()


if __name__ == "__main__":
    agent = SQLAgent()
    tests = [
        "Combien de mesures d'ébauche ont été enregistrées ?",
        "Quelles sont les 5 dernières mesures de filage ?",
        "Y a-t-il des anomalies dans les données de formage ?",
    ]
    for q in tests:
        print(f"\n--- Question : {q}")
        out = agent.ask(q)
        print(f"sql      : {out.get('sql')}")
        print(f"row_count: {out.get('row_count')}")
        print(f"error    : {out.get('error')}")
        if out.get("data"):
            print(f"data[0]  : {out['data'][0]}")
