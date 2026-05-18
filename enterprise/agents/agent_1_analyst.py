import json
import logging
import re
import time
import psycopg2
import psycopg2.extras
import ollama
from typing import Any
from tenacity import retry, stop_after_attempt, \
                     wait_exponential

logger = logging.getLogger(__name__)


class AnalystAgent:
    """Generic semantic analyst agent driven by DB schema and JSON-only LLM extraction."""

    def __init__(self) -> None:
        """Initialize DB connection settings and in-memory schema cache."""
        self._schema_cache: dict[str, Any] | None = None
        self._db_config = {
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "password": "industria123",
            "dbname": "postgres",
        }

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
            logger.info("Schema loaded from database: %s tables", len(schema))
            return schema
        except Exception as exc:
            logger.exception("Failed to load schema from DB")
            raise exc
        finally:
            if conn is not None:
                conn.close()

    def _get_relevant_tables(
        self,
        question: str,
        schema: dict,
    ) -> list:
        """
        Rank tables by keyword overlap between question words, table names, and column names.

        Args:
            question: User question in French.
            schema: Live DB schema.

        Returns:
            list: Relevant table names sorted by score descending.
        """
        translation = str.maketrans(
            {
                ".": " ",
                ",": " ",
                ";": " ",
                ":": " ",
                "!": " ",
                "?": " ",
                "(": " ",
                ")": " ",
                "[": " ",
                "]": " ",
                "{": " ",
                "}": " ",
                "'": " ",
                '"': " ",
                "/": " ",
                "\\": " ",
                "\t": " ",
                "\n": " ",
                "-": " ",
                "_": " ",
            }
        )
        words = [w for w in question.lower().translate(translation).split() if w]
        scored: list[tuple[str, int]] = []

        for table_name, table_info in schema.items():
            score = 0
            table_name_l = table_name.lower()
            for word in words:
                if word in table_name_l:
                    score += 3
                for column_name in table_info.get("columns", {}):
                    if word in column_name.lower():
                        score += 1
            scored.append((table_name, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        relevant = [table_name for table_name, score in scored if score > 0]
        if not relevant:
            return list(schema.keys())
        return relevant

    def _build_prompt(
        self,
        question: str,
        relevant_tables: list,
        schema: dict,
    ) -> dict:
        """
        Build reduced-schema system and user prompts for JSON-only extraction.

        Args:
            question: User question.
            relevant_tables: Tables selected by Python pre-ranking.
            schema: Full schema dictionary.

        Returns:
            dict: {"system": "...", "user": "..."}
        """
        reduced_schema = {
            table_name: schema[table_name]
            for table_name in relevant_tables
            if table_name in schema
        }
        schema_json = json.dumps(reduced_schema, ensure_ascii=False, indent=2)

        system_prompt = (
            "Tu es un extracteur de paramètres JSON\n"
            "pour une plateforme d'analyse industrielle.\n"
            "Tu analyses des questions sur des données\n"
            "de capteurs industriels.\n"
            "Tu ne fais AUCUN calcul.\n"
            "Tu retournes UNIQUEMENT ce JSON :\n"
            "{\n"
            "  'relevant_tables': ['table1', 'table2'],\n"
            "  'relevant_columns': ['col1', 'col2'],\n"
            "  'target_column': 'colonne_principale',\n"
            "  'filters': {\n"
            "    'time_filter_hours': null ou entier,\n"
            "    'group_filter_column': null ou 'colonne',\n"
            "    'group_filter_value': null ou 'valeur'\n"
            "  }\n"
            "}\n\n"
            "Tables disponibles :\n"
            f"{schema_json}\n\n"
            "Règles :\n"
            "- target_column = la colonne numérique\n"
            "  la plus pertinente pour la question\n"
            "- relevant_columns = toutes les colonnes\n"
            "  utiles pour répondre + timestamp\n"
            "- time_filter_hours = null si pas de\n"
            "  filtre temps dans la question\n\n"
            "Si la question parle de comparer\n"
            "ou de différences entre groupes :\n"
            "  → inclure une colonne catégorielle\n"
            "    (modele, piece_id, type, categorie)\n"
            "    dans relevant_columns\n"
            "  → filters.group_filter_column = cette colonne\n"
            "  → NE PAS laisser group_filter_column à null\n"
            "  → privilégier les tables qui ont modele\n"
            "    (filage_data, formage_data)\n\n"
            "EXEMPLE :\n"
            "Question: 'Compare les différents modèles'\n"
            "Réponse:\n"
            "{\n"
            "  'relevant_tables': ['filage_data'],\n"
            "  'relevant_columns': ['timestamp', 'modele', 'inducteur_1'],\n"
            "  'target_column': 'inducteur_1',\n"
            "  'filters': {\n"
            "    'time_filter_hours': null,\n"
            "    'group_filter_column': 'modele',\n"
            "    'group_filter_value': null\n"
            "  }\n"
            "}\n\n"
            "Réponds UNIQUEMENT avec le JSON.\n"
            "Pas de markdown. Pas d'explication.\n"
            "Pas de texte avant ou après le JSON."
        )

        user_prompt = (
            f"Question : {question}\n\n"
            "Réponds UNIQUEMENT avec le JSON.\n"
            "Pas de markdown. Pas d'explication.\n"
            "Pas de texte avant ou après le JSON."
        )
        return {"system": system_prompt, "user": user_prompt}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _call_ollama(self, prompt: dict) -> dict | None:
        """
        Call Ollama and parse a JSON response after manual cleanup.

        Args:
            prompt: Prompt dictionary with system and user messages.

        Returns:
            dict | None: Parsed JSON payload or None on parse failure.
        """
        try:
            response = ollama.chat(
                model="qwen2.5-coder:7b",
                messages=[
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": prompt["user"]},
                ],
                format="json",
                options={
                    "num_ctx": 8000,
                    "num_predict": 150,
                    "temperature": 0.1,
                },
            )
        except Exception as exc:
            logger.exception("Ollama call failed")
            raise exc

        raw_text = ""
        if isinstance(response, dict):
            message = response.get("message", {})
            if isinstance(message, dict):
                raw_text = str(message.get("content", "") or "")
        else:
            message = getattr(response, "message", None)
            if message is not None:
                raw_text = str(getattr(message, "content", "") or "")

        logger.debug(f"Réponse brute : {raw_text}")

        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            logger.warning("Ollama response did not contain a valid JSON object")
            return None

        cleaned = cleaned[start : end + 1]

        try:
            return json.loads(cleaned)
        except Exception:
            match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if match is None:
                logger.warning("Failed to decode Ollama JSON response")
                return None
            try:
                return json.loads(match.group(0))
            except Exception:
                logger.warning("Failed to decode Ollama JSON response")
                return None

    def _is_comparison_question(self, question: str) -> bool:
        """Return True when the user question asks for group comparison."""
        lowered = question.lower()
        return any(
            keyword in lowered
            for keyword in (
                "compar",
                "différen",
                "differen",
                "groupe",
                "modèle",
                "modele",
            )
        )

    def _infer_group_filter_column(
        self,
        relevant_tables: list[str],
        schema: dict,
    ) -> str | None:
        """Pick a categorical column for group comparisons from the schema."""
        for table_name in relevant_tables:
            columns = schema.get(table_name, {}).get("columns", {})
            for preferred in ("modele", "categorie", "type", "piece_id"):
                if preferred in columns:
                    return preferred
        return None

    def _validate_output(
        self,
        output: dict,
        schema: dict,
        question: str = "",
    ) -> dict:
        """
        Validate and normalize LLM output using Python-only checks.

        Args:
            output: Raw LLM output dictionary.
            schema: Live database schema.

        Returns:
            dict: Normalized payload with valid tables, columns, target column, and filters.
        """
        all_tables = list(schema.keys())
        requested_tables = output.get("relevant_tables", [])
        if not isinstance(requested_tables, list):
            requested_tables = []
        relevant_tables = [table for table in requested_tables if table in schema]
        if not relevant_tables:
            relevant_tables = all_tables

        allowed_columns: set[str] = set()
        timestamp_exists = False
        for table_name in relevant_tables:
            for column_name in schema[table_name].get("columns", {}):
                allowed_columns.add(column_name)
                if column_name == "timestamp":
                    timestamp_exists = True

        requested_columns = output.get("relevant_columns", [])
        if not isinstance(requested_columns, list):
            requested_columns = []
        relevant_columns: list[str] = []
        for column_name in requested_columns:
            if column_name in allowed_columns and column_name not in relevant_columns:
                relevant_columns.append(column_name)
        if timestamp_exists and "timestamp" not in relevant_columns:
            relevant_columns.append("timestamp")

        numeric_types = {
            "double precision",
            "numeric",
            "real",
            "float",
            "integer",
        }

        target_column = output.get("target_column")
        target_is_valid = False
        if isinstance(target_column, str):
            for table_name in relevant_tables:
                table_columns = schema[table_name].get("columns", {})
                data_type = str(table_columns.get(target_column, "")).lower()
                if target_column in table_columns and data_type in numeric_types:
                    target_is_valid = True
                    break

        if not target_is_valid:
            target_column = None
            for table_name in relevant_tables:
                for column_name, data_type in schema[table_name].get("columns", {}).items():
                    data_type_l = str(data_type).lower()
                    if data_type_l in numeric_types:
                        target_column = column_name
                        break
                if target_column:
                    break

        filters = output.get("filters", {})
        if not isinstance(filters, dict):
            filters = {}
        time_filter_hours = filters.get("time_filter_hours")
        if not isinstance(time_filter_hours, int) or time_filter_hours <= 0 or time_filter_hours >= 8760:
            time_filter_hours = None

        group_filter_column = filters.get("group_filter_column")
        if not isinstance(group_filter_column, str) or group_filter_column not in allowed_columns:
            group_filter_column = None

        group_filter_value = filters.get("group_filter_value")
        if group_filter_column is None:
            group_filter_value = None

        if question and self._is_comparison_question(question):
            modele_tables = [
                table_name
                for table_name, table_info in schema.items()
                if "modele" in table_info.get("columns", {})
            ]
            if modele_tables and modele_tables[0] not in relevant_tables:
                relevant_tables = [modele_tables[0], *relevant_tables[:2]]

            allowed_columns = set()
            timestamp_exists = False
            for table_name in relevant_tables:
                for column_name in schema[table_name].get("columns", {}):
                    allowed_columns.add(column_name)
                    if column_name == "timestamp":
                        timestamp_exists = True

            if group_filter_column is None:
                group_filter_column = self._infer_group_filter_column(
                    relevant_tables,
                    schema,
                )

        if (
            group_filter_column
            and group_filter_column not in relevant_columns
            and group_filter_column in allowed_columns
        ):
            relevant_columns.append(group_filter_column)

        if target_column and target_column not in relevant_columns:
            relevant_columns.append(target_column)

        if not relevant_columns and timestamp_exists:
            relevant_columns = ["timestamp"]

        return {
            "relevant_tables": relevant_tables,
            "relevant_columns": relevant_columns,
            "target_column": target_column,
            "filters": {
                "time_filter_hours": time_filter_hours,
                "group_filter_column": group_filter_column,
                "group_filter_value": group_filter_value,
            },
        }

    def run(self, question: str, state: dict) -> dict:
        """
        Execute schema loading, table ranking, JSON extraction, validation, and state update.

        Args:
            question: User question.
            state: Shared LangGraph-like state dictionary.

        Returns:
            dict: Structured agent result that never raises.
        """
        start_time = time.time()
        attempts = 0
        state.setdefault("errors", [])

        try:
            schema = self._load_schema_from_db()
            relevant_tables = self._get_relevant_tables(question, schema)

            validated: dict[str, Any] | None = None
            attempt_errors: list[str] = []
            for attempt in range(3):
                attempts = attempt + 1
                prompt = self._build_prompt(question, relevant_tables, schema)
                try:
                    output = self._call_ollama(prompt)
                except Exception as exc:
                    logger.warning("Ollama attempt %s failed: %s", attempts, exc)
                    attempt_errors.append(str(exc))
                    continue
                if output is None:
                    continue
                candidate = self._validate_output(output, schema, question)
                if candidate.get("relevant_tables") and candidate.get("target_column") is not None:
                    validated = candidate
                    break

            if validated is None:
                fallback_target = None
                numeric_types = {
                    "double precision",
                    "numeric",
                    "real",
                    "integer",
                    "bigint",
                    "smallint",
                    "decimal",
                }
                for table_name in relevant_tables:
                    for column_name, data_type in schema.get(table_name, {}).get("columns", {}).items():
                        if str(data_type).lower() in numeric_types:
                            fallback_target = column_name
                            break
                    if fallback_target:
                        break

                fallback_columns = []
                for table_name in relevant_tables:
                    if "timestamp" in schema.get(table_name, {}).get("columns", {}):
                        fallback_columns = ["timestamp"]
                        break

                validated = {
                    "relevant_tables": relevant_tables,
                    "relevant_columns": fallback_columns,
                    "target_column": fallback_target,
                    "filters": {
                        "time_filter_hours": None,
                        "group_filter_column": None,
                        "group_filter_value": None,
                    },
                }
                if attempt_errors:
                    state["errors"].append("; ".join(attempt_errors))

            state["tables"] = validated["relevant_tables"]
            state["columns"] = validated["relevant_columns"]
            state["target_column"] = validated["target_column"]
            state["filters"] = validated["filters"]

            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "agent_1_analyst",
                "status": "success",
                "tables": validated["relevant_tables"],
                "columns": validated["relevant_columns"],
                "target_column": validated["target_column"],
                "filters": validated["filters"],
                "attempts": attempts,
                "execution_time_ms": execution_time_ms,
                "error": None,
            }
        except Exception as exc:
            logger.exception("agent_1_analyst failed")
            state["errors"].append(str(exc))
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "agent_1_analyst",
                "status": "error",
                "tables": [],
                "columns": [],
                "target_column": None,
                "filters": {
                    "time_filter_hours": None,
                    "group_filter_column": None,
                    "group_filter_value": None,
                },
                "attempts": attempts,
                "execution_time_ms": execution_time_ms,
                "error": str(exc),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    agent = AnalystAgent()
    state = {}

    questions = [
        "Y a-t-il des anomalies sur les capteurs ?",
        "Quelle est la température maximale ?",
        "Compare les deux modèles de pièces",
        "Problème détecté depuis lundi",
    ]

    for q in questions:
        state = {}
        print(f"\n{'='*50}")
        print(f"Q: {q}")
        result = agent.run(q, state)
        print(f"Tables     : {result['tables']}")
        print(f"Colonnes   : {result['columns']}")
        print(f"Cible      : {result['target_column']}")
        print(f"Filtres    : {result['filters']}")
        print(f"Tentatives : {result['attempts']}")
        print(f"Temps      : {result['execution_time_ms']}ms")
        print(f"Erreur     : {result['error']}")
