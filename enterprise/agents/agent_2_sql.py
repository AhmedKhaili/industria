import json
import logging
import time
import re
import psycopg2
import psycopg2.extras
import pandas as pd
import sqlglot
import ollama
from typing import Any
from tenacity import retry, stop_after_attempt, \
                     wait_exponential

logger = logging.getLogger(__name__)

_NUMERIC_SQL_TYPES = frozenset({
    "integer",
    "bigint",
    "smallint",
    "numeric",
    "real",
    "double precision",
    "decimal",
})
_MIN_ANALYSIS_ROWS = 5
_SKIP_METRIC_COLUMNS = frozenset({
    "timestamp",
    "piece_id",
    "id",
    "row_id",
    "anomalie",
    "score_anomalie",
})


class SQLAgent:
    """Generic SQL engine for IndustrIA using live schema, Ollama, and strict SQL validation."""

    def __init__(self) -> None:
        """Initialize DB connection settings and the in-memory schema cache."""
        self._schema_cache: dict[str, Any] | None = None
        self._db_config = {
            "host": "localhost",
            "port": 5432,
            "dbname": "postgres",
            "user": "postgres",
            "password": "industria123",
        }
        self._readonly_config = {
            "host": "localhost",
            "port": 5432,
            "dbname": "postgres",
            "user": "postgres_readonly",
            "password": "industria123",
            "options": "-c default_transaction_read_only=on",
        }

    def _is_timestamp_projection(self, expression) -> bool:
        """
        Check whether a SELECT projection is a raw `timestamp` column.

        Args:
            expression: sqlglot expression from the SELECT list.

        Returns:
            bool: True when the projection is a direct timestamp column.
        """
        base_expression = expression.this if hasattr(expression, "this") and expression.__class__.__name__ == "Alias" else expression
        if not isinstance(base_expression, sqlglot.exp.Column):
            return False
        return str(base_expression.name).lower() == "timestamp"

    def _remove_timestamp_from_aggregate_select(self, statement):
        """
        Remove raw timestamp from aggregate SELECT queries without GROUP BY.

        Args:
            statement: Parsed sqlglot statement.

        Returns:
            sqlglot expression: Possibly adjusted statement.
        """
        if not isinstance(statement, sqlglot.exp.Select):
            return statement

        statement_sql = statement.sql(dialect="postgres")
        has_aggregate = re.search(
            r"\b(?:AVG|SUM|COUNT|MIN|MAX)\s*\(",
            statement_sql,
            re.IGNORECASE,
        )
        has_group_by = statement.args.get("group") is not None
        if not has_aggregate or has_group_by:
            return statement

        projections = list(statement.expressions or [])
        if not projections:
            return statement

        filtered_projections = [
            expression
            for expression in projections
            if not self._is_timestamp_projection(expression)
        ]
        if len(filtered_projections) == len(projections) or not filtered_projections:
            return statement

        logger.warning(
            "Timestamp retire du SELECT agrege sans GROUP BY pour SQL invalide"
        )
        adjusted_statement = statement.copy()
        adjusted_statement.set("expressions", filtered_projections)
        return adjusted_statement

    def _load_schema_from_db(self) -> dict:
        """
        Load the live public schema from TimescaleDB and cache it.

        Returns:
            dict: {"table_name": {"columns": {"column_name": "data_type"}}}
        """
        if self._schema_cache:
            return self._schema_cache

        query = """
        SELECT
          table_name,
          column_name,
          data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name NOT LIKE 'pg_%'
        AND table_name NOT LIKE '_timescale%'
        ORDER BY table_name, ordinal_position
        """

        schema: dict[str, Any] = {}
        conn = None
        try:
            conn = psycopg2.connect(**self._db_config)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query)
                rows = cur.fetchall()

            for row in rows:
                table_name = row["table_name"]
                column_name = row["column_name"]
                data_type = row["data_type"]
                if table_name not in schema:
                    schema[table_name] = {"columns": {}}
                schema[table_name]["columns"][column_name] = data_type

            self._schema_cache = schema
            logger.info("SQL schema loaded from database: %s tables", len(schema))
            return schema
        except Exception as exc:
            logger.exception("Failed to load schema for SQL agent")
            raise exc
        finally:
            if conn is not None:
                conn.close()

    def _pick_metric_column(
        self,
        table: str,
        target_column: str,
        schema: dict,
    ) -> str | None:
        """
        Pick a numeric metric column for deterministic series fallback SQL.

        Args:
            table: Table name.
            target_column: Preferred metric from analyst state.
            schema: Reduced schema payload keyed by table name.

        Returns:
            str | None: Column name when found.
        """
        table_info = schema.get(table) or {}
        columns = table_info.get("columns", {})

        if (
            target_column
            and target_column in columns
            and str(columns[target_column]).lower() in _NUMERIC_SQL_TYPES
        ):
            return target_column

        for column_name, data_type in columns.items():
            if column_name in _SKIP_METRIC_COLUMNS:
                continue
            if str(data_type).lower() in _NUMERIC_SQL_TYPES:
                return column_name

        return None

    def _build_series_fallback_sql(
        self,
        tables: list[str],
        target_column: str,
        schema: dict,
        group_column: str | None = None,
    ) -> str:
        """
        Build a simple time-series query when LLM SQL returns too few rows.

        Args:
            tables: Candidate tables from analyst state.
            target_column: Preferred metric column.
            schema: Reduced schema payload keyed by table name.

        Returns:
            str: Read-only SELECT with ORDER BY timestamp and LIMIT.
        """
        table = tables[0] if tables else next(iter(schema.keys()), "")
        if group_column:
            for candidate_table in tables:
                candidate_columns = (schema.get(candidate_table) or {}).get(
                    "columns",
                    {},
                )
                if group_column in candidate_columns:
                    table = candidate_table
                    break
        table_sql = self._safe_identifier(table)
        metric = self._pick_metric_column(table, target_column, schema)
        table_columns = (schema.get(table) or {}).get("columns", {})

        select_parts = ["timestamp"]
        if (
            group_column
            and group_column in table_columns
            and group_column != "timestamp"
        ):
            select_parts.append(self._safe_identifier(group_column))
        if metric:
            select_parts.append(self._safe_identifier(metric))

        if len(select_parts) > 1:
            return (
                f"SELECT {', '.join(select_parts)} "
                f"FROM {table_sql} "
                "ORDER BY timestamp ASC LIMIT 500"
            )

        return (
            f"SELECT * FROM {table_sql} "
            "ORDER BY timestamp ASC LIMIT 500"
        )

    def _safe_identifier(self, name: str) -> str:
        """
        Return a safely quoted SQL identifier.

        Args:
            name: Table or column name.

        Returns:
            str: SQL identifier wrapped in double quotes.
        """
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"Unsafe SQL identifier: {name!r}")
        return f'"{name}"'

    def _build_prompt(
        self,
        question: str,
        tables: list,
        columns: list,
        filters: dict,
        schema: dict,
    ) -> dict:
        """
        Build the system and user prompt for SQL generation.

        Args:
            question: User question.
            tables: Relevant tables from state.
            columns: Relevant columns from state.
            filters: Filter dictionary from state.
            schema: Reduced schema for relevant tables only.

        Returns:
            dict: {"system": "...", "user": "..."}
        """
        schema_json = json.dumps(schema, ensure_ascii=False, indent=2)
        time_filter_hours = filters.get("time_filter_hours") if isinstance(filters, dict) else None
        group_filter_column = (
            filters.get("group_filter_column")
            if isinstance(filters, dict)
            else None
        )

        system_prompt = (
            "Tu es un expert SQL TimescaleDB.\n"
            "Tu génères UNIQUEMENT du SQL en lecture seule.\n"
            "Tu ne fais AUCUN calcul analytique.\n\n"
            "Règles SQL obligatoires :\n"
            "- Toujours inclure la colonne timestamp\n"
            "- Toujours ORDER BY timestamp ASC\n"
            "- Ne jamais générer INSERT/UPDATE/DELETE/\n"
            "  DROP/ALTER/CREATE/TRUNCATE\n"
            "- Pas de sous-requêtes complexes\n\n"
            "RÈGLES SQL OBLIGATOIRES :\n\n"
            "1. INTERDIT : UNION, UNION ALL\n"
            "   entre tables différentes\n\n"
            "2. Pour agrégation temporelle\n"
            "   utiliser EXACTEMENT :\n"
            "   time_bucket('1 hour', timestamp)\n"
            "   PAS TIME_BUCKET('hour', timestamp)\n\n"
            "3. Si AVG/SUM/MIN/MAX dans SELECT ->\n"
            "   GROUP BY obligatoire sur toutes\n"
            "   les colonnes non-agrégées\n\n"
            "EXEMPLE CORRECT :\n"
            "SELECT time_bucket('1 hour', timestamp)\n"
            "       AS bucket, AVG(poids)\n"
            "FROM ebauche_data\n"
            "GROUP BY bucket\n"
            "ORDER BY bucket ASC\n"
            "LIMIT 100\n\n"
            "Tables et colonnes disponibles :\n"
            f"{schema_json}\n\n"
            "Exemple générique :\n"
            "SELECT timestamp, nom_colonne\n"
            "FROM nom_table\n"
            "WHERE timestamp > NOW() - INTERVAL '72 hours'\n"
            "ORDER BY timestamp ASC\n"
            "LIMIT 100\n\n"
            "Réponds UNIQUEMENT avec le SQL brut.\n"
            "Pas de markdown. Pas d'explication.\n"
            "Pas de texte avant ou après le SQL."
        )

        user_prompt = (
            f"Question : {question}\n"
            f"Tables : {tables}\n"
            f"Colonnes : {columns}\n"
            f"Filtre temps : {time_filter_hours}h ou null\n"
            f"Colonne de groupe : {group_filter_column or 'null'}\n"
            "Si colonne de groupe renseignée,\n"
            "inclure cette colonne dans le SELECT.\n"
            "Génère le SQL."
        )
        return {"system": system_prompt, "user": user_prompt}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _call_ollama(self, prompt: dict) -> str | None:
        """
        Call Ollama and return cleaned raw SQL text.

        Args:
            prompt: Prompt dictionary with system and user text.

        Returns:
            str | None: Cleaned SQL string or None if empty.
        """
        try:
            response = ollama.chat(
                model="qwen2.5-coder:7b",
                messages=[
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": prompt["user"]},
                ],
                options={
                    "num_ctx": 4000,
                    "num_predict": 300,
                    "temperature": 0.0,
                },
            )
        except Exception as exc:
            logger.exception("Ollama SQL call failed")
            raise exc

        sql_brut = ""
        if isinstance(response, dict):
            message = response.get("message", {})
            if isinstance(message, dict):
                sql_brut = str(message.get("content", "") or "")
        else:
            message = getattr(response, "message", None)
            if message is not None:
                sql_brut = str(getattr(message, "content", "") or "")

        sql_brut = (
            sql_brut
            .replace("```sql", "")
            .replace("```SQL", "")
            .replace("```", "")
        )
        select_match = re.search(r"\bSELECT\b", sql_brut, re.IGNORECASE)
        if select_match is not None:
            sql_brut = sql_brut[select_match.start():]
        sql_brut = sql_brut.strip()
        logger.debug(f"SQL brut : {sql_brut}")
        if not sql_brut:
            return None
        return sql_brut

    def _validate_sql(self, sql: str) -> dict:
        """
        Validate SQL safety and inject LIMIT 100 if absent.

        Args:
            sql: Raw SQL string.

        Returns:
            dict: {"valid": bool, "sql_safe": str | None, "error": str | None}
        """
        if not isinstance(sql, str) or not sql.strip():
            return {"valid": False, "sql_safe": None, "error": "sql vide"}

        select_match = re.search(r"\bSELECT\b", sql, re.IGNORECASE)
        if select_match is None:
            return {"valid": False, "sql_safe": None, "error": "pas de SELECT"}

        sql_clean = sql[select_match.start():].strip()

        mots_interdits = [
            "INSERT", "UPDATE", "DELETE",
            "DROP", "ALTER", "CREATE",
            "TRUNCATE", "GRANT", "REVOKE",
        ]
        for mot in mots_interdits:
            if re.search(rf"\b{mot}\b", sql_clean, re.IGNORECASE):
                return {"valid": False, "sql_safe": None, "error": "mot interdit"}

        if re.search(r"\bFULL\s+OUTER\s+JOIN\b", sql_clean, re.IGNORECASE):
            return {
                "valid": False,
                "sql_safe": None,
                "error": "FULL OUTER JOIN interdit",
            }

        if re.search(r"\bUNION\s+ALL\b", sql_clean, re.IGNORECASE):
            return {
                "valid": False,
                "sql_safe": None,
                "error": "UNION ALL interdit",
            }

        if re.search(r"\bUNION\b", sql_clean, re.IGNORECASE):
            return {
                "valid": False,
                "sql_safe": None,
                "error": "UNION interdit",
            }

        try:
            statements = sqlglot.parse(sql_clean, dialect="postgres")
        except Exception as exc:
            return {"valid": False, "sql_safe": None, "error": f"parse error: {exc}"}

        if len(statements) != 1:
            return {"valid": False, "sql_safe": None, "error": "exactement 1 statement attendu"}

        statement = statements[0]
        statement_sql = statement.sql(dialect="postgres").strip()
        if not statement_sql.upper().startswith("SELECT"):
            return {"valid": False, "sql_safe": None, "error": "statement non SELECT"}

        sql_safe = statement_sql
        if not re.search(r"\bLIMIT\b", sql_safe, re.IGNORECASE):
            if sql_safe.endswith(";"):
                sql_safe = sql_safe[:-1].rstrip() + " LIMIT 100;"
            else:
                sql_safe = sql_safe.rstrip() + " LIMIT 100"

        return {"valid": True, "sql_safe": sql_safe, "error": None}

    def _execute_sql(self, sql: str) -> pd.DataFrame | None:
        """
        Execute SQL in read-only mode and return a pandas DataFrame.

        Args:
            sql: Validated SQL query.

        Returns:
            pd.DataFrame | None: Result set as DataFrame, empty DataFrame, or None on fatal error.
        """
        conn = None
        fallback_used = False
        try:
            try:
                conn = psycopg2.connect(**self._readonly_config)
                logger.info("Connected with dedicated read-only PostgreSQL user")
            except Exception:
                logger.warning(
                    "Utilisation user postgres — postgres_readonly non trouvé"
                )
                conn = psycopg2.connect(**self._db_config)
                fallback_used = True

            conn.autocommit = False
            with conn.cursor() as cursor:
                cursor.execute("BEGIN")
                if fallback_used:
                    cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SET LOCAL statement_timeout = '2000ms'")
                sql_to_execute = sql
                sql_to_execute = re.sub(
                    r"(?i)TIME_BUCKET\('(\w+)'",
                    lambda m: f"time_bucket('1 {m.group(1).lower()}'",
                    sql_to_execute,
                )
                has_aggregate = re.search(
                    r"\b(?:AVG|SUM|MIN|MAX|COUNT)\s*\(",
                    sql_to_execute,
                    re.IGNORECASE,
                )
                has_group_by = re.search(
                    r"\bGROUP\s+BY\b",
                    sql_to_execute,
                    re.IGNORECASE,
                )
                select_match = re.search(
                    r"\bSELECT\b(?P<select_clause>.*?)\bFROM\b",
                    sql_to_execute,
                    re.IGNORECASE | re.DOTALL,
                )
                select_clause = select_match.group("select_clause") if select_match else ""
                has_timestamp_in_select = re.search(
                    r"(?:^|,)\s*(?:[A-Za-z_][A-Za-z0-9_]*\.)?\"?timestamp\"?\s*(?:,|$)",
                    select_clause,
                    re.IGNORECASE,
                )
                logger.debug(
                    f"[SQL] sql_to_execute = {sql_to_execute}"
                )
                logger.debug(
                    f"[SQL] has_aggregate = {bool(has_aggregate)}"
                )
                logger.debug(
                    f"[SQL] has_group_by = {bool(has_group_by)}"
                )
                logger.debug(
                    f"[SQL] select_clause = '{select_clause}'"
                )
                logger.debug(
                    f"[SQL] has_timestamp = {bool(has_timestamp_in_select)}"
                )
                if has_aggregate and not has_group_by and has_timestamp_in_select:
                    # Cas 1 : timestamp en premier avec préfixe optionnel
                    sql_to_execute = re.sub(
                        r"(?i)SELECT\s+(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
                        r"\"?timestamp\"?\s*,\s*",
                        "SELECT ",
                        sql_to_execute,
                    )

                    # Cas 2 : timestamp en milieu avec préfixe optionnel
                    sql_to_execute = re.sub(
                        r"(?i),\s*(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
                        r"\"?timestamp\"?\s*(?=,|\s+FROM)",
                        "",
                        sql_to_execute,
                    )
                    logger.warning(
                        "Timestamp retire du SELECT agrege sans GROUP BY avant execution"
                    )

                cursor.execute(sql_to_execute)
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                conn.rollback()

            df = pd.DataFrame(rows, columns=columns)
            if df.empty:
                logger.warning("SQL execution returned an empty DataFrame")
            return df
        except Exception:
            logger.exception("SQL execution failed")
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    logger.debug("Rollback failed after SQL execution error")
            return None
        finally:
            if conn is not None:
                conn.close()

    def run(self, question: str, state: dict) -> dict:
        """
        Generate SQL from state, validate it, execute it, and update the shared state.

        Args:
            question: User question.
            state: Shared state from previous agents.

        Returns:
            dict: Structured SQL agent result.
        """
        start_time = time.time()
        attempts = 0
        sql_used = None
        df: pd.DataFrame | None = None
        state.setdefault("errors", [])

        try:
            tables = state.get("tables", [])
            columns = state.get("columns", [])
            filters = state.get("filters", {})
            _target_column = state.get("target_column", "")

            schema = self._load_schema_from_db()
            if not tables:
                tables = list(schema.keys())

            reduced_schema = {
                table_name: schema[table_name]
                for table_name in tables
                if table_name in schema
            }
            if not reduced_schema:
                reduced_schema = schema
                tables = list(schema.keys())

            attempt_errors: list[str] = []
            for attempt in range(3):
                attempts = attempt + 1
                prompt = self._build_prompt(
                    question,
                    tables,
                    columns,
                    filters,
                    reduced_schema,
                )
                try:
                    sql_brut = self._call_ollama(prompt)
                except Exception as exc:
                    attempt_errors.append(str(exc))
                    logger.warning("SQL generation attempt %s failed: %s", attempts, exc)
                    continue

                if sql_brut is None:
                    attempt_errors.append("sql vide")
                    continue

                validation = self._validate_sql(sql_brut)
                if not validation["valid"]:
                    attempt_errors.append(str(validation["error"]))
                    continue

                sql_used = validation["sql_safe"]
                df = self._execute_sql(sql_used)
                if df is not None and len(df.index) < _MIN_ANALYSIS_ROWS:
                    group_column = (
                        filters.get("group_filter_column")
                        if isinstance(filters, dict)
                        else None
                    )
                    sparse_sql = self._build_series_fallback_sql(
                        tables,
                        _target_column,
                        reduced_schema,
                        group_column if isinstance(group_column, str) else None,
                    )
                    df_sparse = self._execute_sql(sparse_sql)
                    if (
                        df_sparse is not None
                        and len(df_sparse.index) >= _MIN_ANALYSIS_ROWS
                    ):
                        logger.warning(
                            "SQL LLM trop peu de lignes (%s), "
                            "fallback serie brute (%s lignes)",
                            len(df.index),
                            len(df_sparse.index),
                        )
                        sql_used = sparse_sql
                        df = df_sparse
                if df is not None:
                    break
                attempt_errors.append("execution sql échouée")

            if df is None:
                fallback_table = tables[0] if tables else next(iter(schema.keys()), None)
                if fallback_table is None:
                    raise RuntimeError("aucune table disponible pour fallback SQL")
                sql_used = (
                    f"SELECT * FROM {self._safe_identifier(fallback_table)} "
                    "ORDER BY timestamp DESC LIMIT 100"
                )
                df = self._execute_sql(sql_used)
                if df is None:
                    raise RuntimeError("fallback SQL execution failed")
                if attempt_errors:
                    state.setdefault("warnings", [])
                    state["warnings"].append(
                        "SQL LLM: " + "; ".join(attempt_errors)
                    )

            state["df_raw"] = df
            state["sql"] = sql_used

            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "agent_2_sql",
                "status": "success",
                "sql": sql_used,
                "row_count": int(len(df.index)),
                "columns": list(df.columns),
                "execution_time_ms": execution_time_ms,
                "attempts": attempts,
                "error": None,
            }
        except Exception as exc:
            logger.exception("agent_2_sql failed")
            state["errors"].append(str(exc))
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "agent_2_sql",
                "status": "error",
                "sql": sql_used,
                "row_count": 0,
                "columns": [],
                "execution_time_ms": execution_time_ms,
                "attempts": attempts,
                "error": str(exc),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    tests = [
        {
            "question": "anomalies capteurs température",
            "state": {
                "tables": ["formage_data"],
                "columns": ["timestamp", "four_3", "four_1", "anomalie"],
                "target_column": "four_3",
                "filters": {
                    "time_filter_hours": None,
                    "group_filter_column": None,
                    "group_filter_value": None,
                },
            },
        },
        {
            "question": "vitesse de coupe dernières 48h",
            "state": {
                "tables": ["ebauche_data"],
                "columns": ["timestamp", "vitesse_coupe"],
                "target_column": "vitesse_coupe",
                "filters": {
                    "time_filter_hours": 48,
                    "group_filter_column": None,
                    "group_filter_value": None,
                },
            },
        },
        {
            "question": "compare modèles filage",
            "state": {
                "tables": ["filage_data"],
                "columns": ["timestamp", "modele", "pyrometre", "lvdt_moyenne"],
                "target_column": "pyrometre",
                "filters": {
                    "time_filter_hours": None,
                    "group_filter_column": "modele",
                    "group_filter_value": None,
                },
            },
        },
    ]

    agent = SQLAgent()
    for test in tests:
        print(f"\n{'='*50}")
        print(f"Q: {test['question']}")
        result = agent.run(test["question"], test["state"])
        sql_preview = result["sql"][:80] + "..." if isinstance(result["sql"], str) else "None"
        print(f"SQL        : {sql_preview}")
        print(f"Lignes     : {result['row_count']}")
        print(f"Colonnes   : {result['columns']}")
        print(f"Tentatives : {result['attempts']}")
        print(f"Temps      : {result['execution_time_ms']}ms")
        print(f"Erreur     : {result['error']}")
