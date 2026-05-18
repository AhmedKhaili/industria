import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

import ollama

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger(__name__)

_OLLAMA_MODEL = "qwen2.5-coder:14b"
_DEFAULT_PROFILE = "technicien"
_MAX_METRIC_KEYS = 4
_NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-zPp])-?\d+(?:[.,]\d+)?")

SPECIALIST_METRICS: dict[str, list[str]] = {
    "ZScoreSpecialist": [
        "anomalies_count",
        "max_zscore",
        "pourcentage_anomalies",
        "anomalie_process_count",
    ],
    "SpcSpecialist": [
        "sous_controle",
        "hors_limites_x",
        "UCL_x",
        "LCL_x",
    ],
    "EwmaCusumSpecialist": [
        "derive_detectee",
        "tendance",
        "ewma",
    ],
    "CpCpkSpecialist": [
        "Cpk",
        "Cp",
        "conforme_EN9100",
        "interpretation_Cpk",
    ],
    "CorrelationSpecialist": [
        "n_colonnes_comparées",
        "correlations_significatives",
        "correlation_max",
    ],
    "RegressionSpecialist": [
        "meilleure_variable",
        "variables_significatives",
    ],
    "MannKendallSpecialist": [
        "tendance",
        "p_value",
        "sen_slope",
        "significatif",
    ],
    "AnovaKruskalSpecialist": [
        "methode_choisie",
        "significatif",
        "interpretation",
        "p_value",
    ],
    "PivotSpecialist": [
        "global",
    ],
    "FourierSpecialist": [
        "signal_periodique",
        "frequence_dominante",
        "interpretation",
    ],
}

PROFIL_CONFIG: dict[str, dict[str, Any]] = {
    "operateur": {
        "num_predict": 80,
        "temperature": 0.1,
        "style": (
            "1 phrase max. Action physique. "
            "Zéro jargon statistique."
        ),
        "mots_interdits": [
            "z-score",
            "zscore",
            "écart-type",
            "variance",
            "p-value",
            "shapiro",
            "anova",
            "médiane",
            "percentile",
            "sigma",
            "ucl",
            "lcl",
            "cpk",
            "ewma",
        ],
    },
    "technicien": {
        "num_predict": 120,
        "temperature": 0.1,
        "style": (
            "2 phrases max. Diagnostic machine. "
            "Composant défaillant si possible."
        ),
        "mots_interdits": [],
    },
    "ingenieur": {
        "num_predict": 150,
        "temperature": 0.1,
        "style": (
            "3 phrases max. Analyse complète. "
            "Citer méthode et valeurs."
        ),
        "mots_interdits": [],
    },
    "directeur": {
        "num_predict": 80,
        "temperature": 0.1,
        "style": (
            "1 phrase max. Impact business. "
            "TRS/OEE/conformité EN9100."
        ),
        "mots_interdits": [
            "z-score",
            "zscore",
            "ucl",
            "lcl",
            "shapiro",
            "anova",
            "p-value",
        ],
    },
}

FALLBACK_TEMPLATES: dict[str, dict[str, str]] = {
    "ZScoreSpecialist": {
        "operateur": "Anomalie détectée sur le capteur.",
        "technicien": "{anomalies_count} anomalies détectées, zscore max {max_zscore}.",
        "ingenieur": (
            "{anomalies_count} anomalies ({pourcentage_anomalies}%), "
            "zscore max {max_zscore}."
        ),
        "directeur": "Anomalie process détectée. Intervention requise.",
    },
    "SpcSpecialist": {
        "operateur": "Processus hors contrôle.",
        "technicien": "SPC : {hors_count} points hors limites.",
        "ingenieur": (
            "Processus hors contrôle statistique. "
            "{hors_count} points dépassent UCL={UCL_x}."
        ),
        "directeur": "Processus non conforme. Risque qualité.",
    },
    "EwmaCusumSpecialist": {
        "operateur": "Dérive détectée sur le capteur.",
        "technicien": "Dérive progressive détectée ({tendance_direction}).",
        "ingenieur": (
            "Dérive confirmée (pente {tendance_slope}). "
            "{ewma_alertes_count} alertes EWMA."
        ),
        "directeur": "Dérive process. Surveillance renforcée requise.",
    },
    "default": {
        "operateur": "Analyse terminée. Vérifier la machine.",
        "technicien": "Résultat de l'analyse disponible.",
        "ingenieur": "Analyse statistique complète.",
        "directeur": "Analyse terminée.",
    },
}

FEWSHOT_EXAMPLES: dict[tuple[str, str], dict[str, str]] = {
    ("ZScoreSpecialist", "operateur"): {
        "metrics": '{"anomalies_count": 13, "anomalie_process_count": 11}',
        "output": "Anomalie détectée sur le capteur inducteur_1.",
    },
    ("ZScoreSpecialist", "technicien"): {
        "metrics": (
            '{"anomalies_count": 13, "max_zscore": 4.7, '
            '"pourcentage_anomalies": 13.0}'
        ),
        "output": (
            "13 anomalies détectées sur inducteur_1 avec un zscore maximal de 4.7."
        ),
    },
    ("SpcSpecialist", "ingenieur"): {
        "metrics": (
            '{"sous_controle": false, "hors_limites_x_count": 3, "UCL_x": 115.2}'
        ),
        "output": (
            "Le processus est hors contrôle : 3 points dépassent la limite UCL de 115.2."
        ),
    },
    ("EwmaCusumSpecialist", "directeur"): {
        "metrics": '{"derive_detectee": true, "ewma_alertes_count": 55}',
        "output": "Dérive process sur inducteur_1. Surveillance qualité renforcée.",
    },
}


class Agent6aInterpreter:
    """Agent 6a — interpret one specialist result as profile-adapted French text."""

    def _canonical_specialist(self, specialist_name: str) -> str:
        """Return the specialist key used in SPECIALIST_METRICS."""
        if specialist_name in SPECIALIST_METRICS:
            return specialist_name
        for key in SPECIALIST_METRICS:
            if key.lower() == specialist_name.lower():
                return key
        return specialist_name

    def _flatten_metric_value(
        self,
        key: str,
        value: Any,
        compact: dict[str, Any],
    ) -> None:
        """
        Insert one metric into the compact dict, flattening nested structures.

        Args:
            key: Metric key from SPECIALIST_METRICS.
            value: Raw value from the specialist payload.
            compact: Output compact metrics dict (mutated).
        """
        if value is None:
            return

        if key == "hors_limites_x" and isinstance(value, list):
            compact["hors_limites_x_count"] = len(value)
            return

        if key == "tendance" and isinstance(value, dict):
            if "direction" in value:
                compact["tendance_direction"] = value["direction"]
            if "significative" in value:
                compact["tendance_significative"] = value["significative"]
            if "slope" in value:
                compact["tendance_slope"] = value["slope"]
            return

        if key == "ewma" and isinstance(value, dict):
            if "alertes_count" in value:
                compact["ewma_alertes_count"] = value["alertes_count"]
            return

        if key == "global" and isinstance(value, dict):
            for sub_key in ("mean", "std", "min", "max"):
                if sub_key in value:
                    compact[f"global_{sub_key}"] = value[sub_key]
            return

        if key == "meilleure_variable" and isinstance(value, dict):
            if "variable" in value:
                compact["meilleure_variable_nom"] = value["variable"]
            if "r_squared" in value:
                compact["meilleure_r_squared"] = value["r_squared"]
            return

        if key == "correlation_max" and isinstance(value, dict):
            for sub_key in ("colonne", "pearson_r", "spearman_r"):
                if sub_key in value:
                    compact[f"correlation_max_{sub_key}"] = value[sub_key]
            return

        if key == "correlations_significatives" and isinstance(value, list):
            compact["n_correlations_significatives"] = len(value)
            return

        if key == "variables_significatives" and isinstance(value, list):
            compact["n_variables_significatives"] = len(value)
            return

        if isinstance(value, (dict, list)):
            compact[key] = json.dumps(value, ensure_ascii=False)[:120]
            return

        compact[key] = value

    def _extract_metrics(self, specialist_name: str, result: dict) -> dict:
        """
        Extract up to four metrics for the LLM from a specialist result payload.

        Args:
            specialist_name: Specialist class name.
            result: Specialist ``result`` dictionary.

        Returns:
            dict: Compact metrics (max 4 keys).
        """
        canonical = self._canonical_specialist(specialist_name)
        metric_keys = SPECIALIST_METRICS.get(canonical, [])
        compact: dict[str, Any] = {}

        for key in metric_keys:
            if len(compact) >= _MAX_METRIC_KEYS:
                break
            if key not in result:
                continue
            before_len = len(compact)
            self._flatten_metric_value(key, result[key], compact)
            if len(compact) == before_len and key in result:
                compact[key] = result[key]

        return dict(list(compact.items())[:_MAX_METRIC_KEYS])

    def _fewshot_block(
        self,
        specialist_name: str,
        user_profile: str,
    ) -> str:
        """Build an optional few-shot XML block for the prompt."""
        key = (specialist_name, user_profile)
        sample = FEWSHOT_EXAMPLES.get(key)
        if not sample:
            return ""
        return f"""
<exemple>
<metriques>{sample["metrics"]}</metriques>
<interpretation>{sample["output"]}</interpretation>
</exemple>
""".strip()

    def _build_prompt(
        self,
        specialist_name: str,
        metrics_compact: dict,
        user_profile: str,
        target_column: str,
    ) -> list[dict[str, str]]:
        """
        Build Ollama messages with XML structure for one specialist interpretation.

        Args:
            specialist_name: Specialist identifier.
            metrics_compact: Pre-selected metrics (max 4 keys).
            user_profile: User profile key.
            target_column: Target sensor column name.

        Returns:
            list[dict]: Chat messages for Ollama.
        """
        profile = user_profile if user_profile in PROFIL_CONFIG else _DEFAULT_PROFILE
        config = PROFIL_CONFIG[profile]
        metrics_json = json.dumps(metrics_compact, ensure_ascii=False, indent=2)
        allowed_numbers = ", ".join(
            str(v) for v in metrics_compact.values()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ) or "aucun"

        system_content = f"""
<system_prompt>
Rôle : interprète industriel IndustrIA (Agent 6a).
Mission : expliquer UN résultat du spécialiste {specialist_name} en français.

Colonne analysée : {target_column}
Profil lecteur : {profile}
Style : {config["style"]}

RÈGLES ABSOLUES :
- Aucun calcul, aucune hypothèse de cause non fournie.
- Utiliser UNIQUEMENT les métriques du JSON (chiffres autorisés : {allowed_numbers}).
- Pas de titre, pas de markdown, pas de préambule.
- Réponse : texte direct, 1 à 3 phrases selon le profil.
</system_prompt>

{self._fewshot_block(specialist_name, profile)}

<metriques>
{metrics_json}
</metriques>
""".strip()

        return [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": (
                    f"Interprète le résultat {specialist_name} pour la colonne "
                    f"{target_column}. Texte seul, sans formatage."
                ),
            },
        ]

    def _call_ollama(
        self,
        prompt: list[dict[str, str]],
        user_profile: str,
    ) -> str | None:
        """
        Call Ollama with profile-specific generation limits.

        Args:
            prompt: Chat messages.
            user_profile: User profile key.

        Returns:
            str | None: Generated text or None on failure.
        """
        profile = user_profile if user_profile in PROFIL_CONFIG else _DEFAULT_PROFILE
        config = PROFIL_CONFIG[profile]

        try:
            response = ollama.chat(
                model=_OLLAMA_MODEL,
                messages=prompt,
                options={
                    "temperature": config["temperature"],
                    "num_predict": config["num_predict"],
                    "num_ctx": 4096,
                },
            )
        except Exception:
            logger.exception("agent_6a_interpreter Ollama call failed")
            return None

        raw = ""
        if isinstance(response, dict):
            raw = str(response.get("message", {}).get("content", "") or "")
        else:
            message = getattr(response, "message", None)
            if message is not None:
                raw = str(getattr(message, "content", "") or "")

        cleaned = raw.strip()
        return cleaned if cleaned else None

    def _normalize_text(self, text: str) -> str:
        """Strip markdown and excess whitespace from model output."""
        cleaned = text.strip()
        cleaned = re.sub(r"```[a-zA-Z]*", "", cleaned)
        cleaned = cleaned.replace("```", "")
        cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _allowed_numbers(self, metrics_compact: dict) -> set[float]:
        """Collect numeric values allowed in the generated text."""
        allowed: set[float] = set()

        def register(number: float) -> None:
            allowed.add(number)
            allowed.add(float(round(number, 3)))
            allowed.add(float(round(number, 1)))
            if number == int(number):
                allowed.add(float(int(number)))

        def walk(value: Any) -> None:
            if isinstance(value, bool):
                return
            if isinstance(value, (int, float)):
                register(float(value))
                return
            if isinstance(value, dict):
                for nested in value.values():
                    walk(nested)
                return
            if isinstance(value, list):
                for nested in value:
                    walk(nested)

        walk(metrics_compact)
        return allowed

    def _number_whitelist_from_column(self, target_column: str) -> set[float]:
        """Allow digits that appear in the target column name (e.g. inducteur_1)."""
        whitelist: set[float] = set()
        for token in re.findall(r"\d+", target_column):
            whitelist.add(float(token))
        return whitelist

    def _number_is_allowed(
        self,
        number: float,
        allowed_numbers: set[float],
        number_whitelist: set[float],
    ) -> bool:
        """Check metric or column-name whitelist (±0.5 for metrics)."""
        if any(abs(number - whitelisted) < 0.001 for whitelisted in number_whitelist):
            return True
        return any(abs(number - allowed) <= 0.5 for allowed in allowed_numbers)

    def _validate_output(
        self,
        text: str,
        metrics_compact: dict,
        user_profile: str,
        target_column: str,
    ) -> dict:
        """
        Validate interpretation text (flexible form, strict numeric content).

        Args:
            text: Generated interpretation.
            metrics_compact: Metrics sent to the LLM.
            user_profile: User profile key.
            target_column: Target column for digit whitelist.

        Returns:
            dict: ``valid`` flag and optional ``error``.
        """
        normalized = self._normalize_text(text)
        if not normalized:
            return {"valid": False, "error": "texte vide"}

        profile = user_profile if user_profile in PROFIL_CONFIG else _DEFAULT_PROFILE
        lowered = normalized.lower()
        for word in PROFIL_CONFIG[profile]["mots_interdits"]:
            if word.lower() in lowered:
                return {"valid": False, "error": f"mot interdit: {word}"}

        allowed_numbers = self._allowed_numbers(metrics_compact)
        number_whitelist = self._number_whitelist_from_column(target_column)
        text_for_numbers = re.sub(r"\bP\s*[1-4]\b", "", normalized, flags=re.IGNORECASE)

        for match in _NUMBER_TOKEN_RE.findall(text_for_numbers):
            normalized_number = match.replace(",", ".")
            try:
                number = float(normalized_number)
            except ValueError:
                continue
            if not self._number_is_allowed(
                number,
                allowed_numbers,
                number_whitelist,
            ):
                return {"valid": False, "error": f"chiffre inventé: {match}"}

        return {"valid": True}

    def _fallback_context(
        self,
        specialist_name: str,
        metrics_compact: dict,
        result: dict,
    ) -> dict[str, Any]:
        """Build template format context from metrics and raw result."""
        context = dict(metrics_compact)
        hors = result.get("hors_limites_x")
        if isinstance(hors, list):
            context["hors_count"] = len(hors)
        else:
            context["hors_count"] = context.get("hors_limites_x_count", 0)

        tendance = result.get("tendance")
        if isinstance(tendance, dict):
            context.setdefault(
                "tendance_direction",
                tendance.get("direction", ""),
            )
            context.setdefault("tendance_slope", tendance.get("slope", ""))
            context.setdefault("sen_slope", tendance.get("slope", ""))

        ewma = result.get("ewma")
        if isinstance(ewma, dict):
            context.setdefault("ewma_alertes_count", ewma.get("alertes_count", 0))

        return context

    def _apply_fallback(
        self,
        specialist_name: str,
        user_profile: str,
        metrics_compact: dict,
        result: dict,
    ) -> str:
        """
        Return a deterministic fallback interpretation string.

        Args:
            specialist_name: Specialist identifier.
            user_profile: User profile key.
            metrics_compact: Compact metrics.
            result: Full specialist result payload.

        Returns:
            str: Fallback text.
        """
        profile = user_profile if user_profile in PROFIL_CONFIG else _DEFAULT_PROFILE
        canonical = self._canonical_specialist(specialist_name)
        templates = FALLBACK_TEMPLATES.get(
            canonical,
            FALLBACK_TEMPLATES["default"],
        )
        template = templates.get(profile, FALLBACK_TEMPLATES["default"][profile])
        context = self._fallback_context(canonical, metrics_compact, result)

        class _SafeFormatDict(dict):
            def __missing__(self, key: str) -> str:
                return ""

        try:
            return template.format_map(_SafeFormatDict(context))
        except (KeyError, ValueError):
            return FALLBACK_TEMPLATES["default"][profile]

    def run(
        self,
        specialist_name: str,
        specialist_result: dict,
        state: dict,
    ) -> dict:
        """
        Interpret one specialist result and store it in ``state['interpretations']``.

        Args:
            specialist_name: Specialist class name (e.g. ZScoreSpecialist).
            specialist_result: Wrapper dict with ``result`` payload.
            state: Shared LangGraph state.

        Returns:
            dict: Structured 6a result payload.
        """
        start_time = time.time()
        used_fallback = False
        texte_final = ""
        status = "error"
        error_message: str | None = None

        user_profile = state.get("user_profile", _DEFAULT_PROFILE)
        if user_profile not in PROFIL_CONFIG:
            user_profile = _DEFAULT_PROFILE

        target_column = state.get("target_column", "")
        if not isinstance(target_column, str):
            target_column = ""

        payload = specialist_result.get("result", {})
        if not isinstance(payload, dict):
            payload = {}

        metrics = self._extract_metrics(specialist_name, payload)

        if not metrics:
            texte_final = self._apply_fallback(
                specialist_name,
                user_profile,
                metrics,
                payload,
            )
            used_fallback = True
            status = "fallback"
        else:
            raw_text: str | None = None
            for _attempt in range(3):
                messages = self._build_prompt(
                    specialist_name,
                    metrics,
                    user_profile,
                    target_column,
                )
                raw_text = self._call_ollama(messages, user_profile)
                if not raw_text:
                    continue
                validation = self._validate_output(
                    raw_text,
                    metrics,
                    user_profile,
                    target_column,
                )
                if validation["valid"]:
                    texte_final = self._normalize_text(raw_text)
                    status = "success"
                    break
                logger.warning(
                    "agent_6a validation (%s, %s): %s",
                    specialist_name,
                    user_profile,
                    validation.get("error"),
                )

            if status != "success":
                texte_final = self._apply_fallback(
                    specialist_name,
                    user_profile,
                    metrics,
                    payload,
                )
                used_fallback = True
                status = "fallback"

        if isinstance(state, dict):
            state.setdefault("interpretations", {})
            state["interpretations"][specialist_name] = texte_final

        execution_time_ms = int((time.time() - start_time) * 1000)
        return {
            "agent": "agent_6a_interpreter",
            "specialist": specialist_name,
            "status": status,
            "interpretation": texte_final,
            "execution_time_ms": execution_time_ms,
            "used_fallback": used_fallback,
            "error": error_message,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    specialists_test = [
        {
            "name": "ZScoreSpecialist",
            "result": {
                "anomalies_count": 13,
                "bruit_capteur_count": 2,
                "anomalie_process_count": 11,
                "max_zscore": 4.7,
                "pourcentage_anomalies": 13.0,
                "total_points": 100,
            },
        },
        {
            "name": "SpcSpecialist",
            "result": {
                "sous_controle": False,
                "hors_limites_x": [8, 12, 15],
                "UCL_x": 115.2,
                "LCL_x": 84.8,
                "x_bar": 100.1,
            },
        },
        {
            "name": "EwmaCusumSpecialist",
            "result": {
                "derive_detectee": True,
                "tendance": {
                    "direction": "hausse progressive",
                    "significative": True,
                    "slope": 0.106,
                },
                "ewma": {
                    "alertes_count": 55,
                    "premier_alerte": "2026-01-01 01:20:00",
                },
            },
        },
    ]

    state: dict = {
        "target_column": "inducteur_1",
        "interpretations": {},
    }

    agent = Agent6aInterpreter()

    for specialist in specialists_test:
        for profil in ["operateur", "technicien", "ingenieur", "directeur"]:
            state["user_profile"] = profil
            result = agent.run(
                specialist["name"],
                {"result": specialist["result"]},
                state,
            )
            print(f"\n{'=' * 40}")
            print(f"Spécialiste : {specialist['name']}")
            print(f"Profil      : {profil}")
            print(f"Status      : {result['status']}")
            print(f"Texte       : {result['interpretation']}")
            print(f"Fallback    : {result['used_fallback']}")
            print(f"Temps       : {result['execution_time_ms']}ms")
