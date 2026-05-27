import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import ollama

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from state.schema import AgentState

logger = logging.getLogger(__name__)

PROFIL_CONFIG = {
    "operateur": {
        "num_predict": 150,
        "temperature": 0.1,
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
        ],
        "style": (
            "Ultra court. Phrases de 5 mots max. "
            "Action physique immédiate. "
            "Jamais de jargon statistique."
        ),
    },
    "technicien": {
        "num_predict": 250,
        "temperature": 0.2,
        "mots_interdits": [],
        "style": (
            "Diagnostic technique précis. "
            "Identifier le composant défaillant. "
            "Citer le type d'anomalie."
        ),
    },
    "ingenieur": {
        "num_predict": 350,
        "temperature": 0.3,
        "mots_interdits": [],
        "style": (
            "Analyse complète avec méthodes. "
            "Citer les tests statistiques. "
            "Inclure les seuils et valeurs."
        ),
    },
    "directeur": {
        "num_predict": 200,
        "temperature": 0.2,
        "mots_interdits": [
            "z-score",
            "zscore",
            "écart-type",
            "shapiro",
            "anova",
        ],
        "style": (
            "Résumé exécutif. "
            "Impact sur TRS/OEE. "
            "Risque qualité EN9100. "
            "Coût estimé si non traité."
        ),
    },
}

REGLES_PRESCRIRE = {
    "detection_anomalies": {
        "P1": (
            "Arrêt immédiat de la machine. "
            "Alerter le responsable maintenance."
        ),
        "P2": (
            "Intervention dans les 30 minutes. "
            "Vérifier le capteur concerné."
        ),
        "P3": (
            "Surveiller pendant 2h. "
            "Planifier une inspection."
        ),
        "P4": (
            "Noter dans le registre. "
            "Vérifier lors de la prochaine maintenance."
        ),
    },
    "tendance": {
        "P1": "Dérive critique. Arrêt préventif requis.",
        "P2": "Dérive significative. Intervention sous 2h.",
        "P3": "Dérive légère. Surveillance renforcée.",
        "P4": "Tendance à surveiller. Rapport hebdomadaire.",
    },
    "capabilite": {
        "P1": (
            "Cpk < 0.67. Production non conforme EN9100. "
            "Arrêt et inspection obligatoires."
        ),
        "P2": (
            "Cpk < 1.0. Risque de rebut élevé. "
            "Revoir les réglages machine."
        ),
        "P3": (
            "Cpk < 1.33. Amélioration nécessaire. "
            "Analyser les causes."
        ),
        "P4": "Capabilité acceptable. Maintenir la surveillance.",
    },
    "correlation": {
        "P3": "Corrélation détectée. Investiguer la cause commune.",
        "P4": "Corrélation faible. Information à noter.",
    },
    "comparaison_groupes": {
        "P2": (
            "Différence significative entre groupes. "
            "Identifier la cause racine."
        ),
        "P3": "Différence détectée. Analyser les conditions.",
        "P4": "Groupes similaires. Aucune action requise.",
    },
    "resume": {
        "P3": "Anomalies détectées. Analyse approfondie recommandée.",
        "P4": "Processus stable. Continuer la surveillance.",
    },
}

_PRIORITY_RANK = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
_DEFAULT_PROFILE = "technicien"
_OLLAMA_MODEL = "qwen2.5-coder:14b"
_OAPC_SECTION_RE = re.compile(
    r"(?is)(?:^|[\n\r])\s*(?:#{1,3}\s*)?(?:\*{0,2})?"
    r"(?P<label>observer|analyser)\s*(?:\*{0,2})?\s*:?\s*"
    r"(?P<content>[^\n\r#*]+)",
)
_NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-zPp])-?\d+(?:[.,]\d+)?")

PROFILE_FEWSHOTS: dict[str, dict[str, str]] = {
    "operateur": {
        "json": (
            '{"goal": "detection_anomalies", "target_column": "inducteur_1", '
            '"anomalies_count": 13, "pourcentage_anomalies": 13.0}'
        ),
        "observer": "Treize points anormaux sur inducteur un.",
        "analyser": "Situation urgente sur la ligne production.",
    },
    "technicien": {
        "json": (
            '{"goal": "detection_anomalies", "target_column": "inducteur_1", '
            '"anomalies_count": 13, "pourcentage_anomalies": 13.0, "max_zscore": 4.7}'
        ),
        "observer": "13 anomalies detectees sur inducteur_1 dont 11 process.",
        "analyser": "max_zscore 4.7 confirme anomalie process sur la cible.",
    },
    "ingenieur": {
        "json": (
            '{"goal": "detection_anomalies", "target_column": "inducteur_1", '
            '"total_points": 100, "anomalies_count": 13, '
            '"pourcentage_anomalies": 13.0, "max_zscore": 4.7}'
        ),
        "observer": (
            "Sur 100 points, 13 anomalies (13.0 %) avec max_zscore 4.7 "
            "sur inducteur_1."
        ),
        "analyser": (
            "Taux d'anomalies 13.0 % depasse le seuil operationnel "
            "pour detection_anomalies."
        ),
    },
    "directeur": {
        "json": (
            '{"goal": "detection_anomalies", "target_column": "inducteur_1", '
            '"anomalies_count": 13, "pourcentage_anomalies": 13.0}'
        ),
        "observer": "13 anomalies impactent la production sur inducteur_1.",
        "analyser": (
            "Risque qualite EN9100 et baisse TRS si non traite rapidement."
        ),
    },
}


class InterpreterAgent:
    """Agent 5 — observe/analyse via LLM, prescrire/certifier en Python pur."""

    def _is_valid_result(self, result: dict) -> bool:
        """Return True when a specialist result may drive priority logic."""
        if not isinstance(result, dict):
            return False
        if result.get("status") != "success":
            return False
        if result.get("judge_valid") is False:
            return False
        return True

    def _priority_from_single_result(self, result: dict, goal: str) -> str:
        """
        Compute one priority level from a single validated specialist payload.

        Args:
            result: Validated specialist result.
            goal: Classified analytical goal.

        Returns:
            str: Priority level P1–P4.
        """
        payload = result.get("result", {})
        if not isinstance(payload, dict):
            return "P4"

        if goal == "capabilite":
            cpk = float(payload.get("Cpk", 999))
            if cpk < 0.67:
                return "P1"
            if cpk < 1.0:
                return "P2"
            if cpk < 1.33:
                return "P3"
            return "P4"

        if goal == "detection_anomalies":
            pct = float(payload.get("pourcentage_anomalies", 0))
            if pct > 20:
                return "P1"
            if pct > 10:
                return "P2"
            if pct > 5:
                return "P3"
            return "P4"

        if goal == "tendance":
            derive = bool(payload.get("derive_detectee", False))
            tendance_block = payload.get("tendance", {})
            significative = False
            if isinstance(tendance_block, dict):
                significative = bool(tendance_block.get("significative", False))
            if not significative:
                significative = bool(payload.get("significatif", False))
            if derive and significative:
                return "P2"
            if derive or significative:
                return "P3"
            return "P4"

        return "P4"

    def _determine_priority(
        self,
        validated_results: list[dict],
        goal: str,
    ) -> str:
        """
        Determine the highest severity priority across validated results.

        Args:
            validated_results: Judge-validated specialist outputs.
            goal: Classified analytical goal.

        Returns:
            str: Priority level P1–P4.
        """
        priorities: list[str] = []
        for result in validated_results:
            if not self._is_valid_result(result):
                continue
            priorities.append(self._priority_from_single_result(result, goal))

        if not priorities:
            return "P4"

        return min(priorities, key=lambda level: _PRIORITY_RANK.get(level, 4))

    def _merge_metric(
        self,
        compact: dict[str, Any],
        key: str,
        value: Any,
        max_keys: int = 7,
    ) -> None:
        """Insert one metric into the compact dict when under the key limit."""
        if len(compact) >= max_keys:
            return
        if value is None:
            return
        compact[key] = value

    def _build_json_compact(
        self,
        validated_results: list[dict],
        state: dict,
    ) -> dict:
        """
        Build a compact JSON summary for the LLM (max 7 keys, no raw data).

        Args:
            validated_results: Judge-validated specialist outputs.
            state: Shared pipeline state.

        Returns:
            dict: Compact metrics for LLM observation only.
        """
        intention = state.get("intention", {}) if isinstance(state, dict) else {}
        goal = intention.get("goal", "resume") if isinstance(intention, dict) else "resume"

        compact: dict[str, Any] = {
            "goal": goal,
            "target_column": state.get("target_column", "") if isinstance(state, dict) else "",
        }

        for result in validated_results:
            if not self._is_valid_result(result):
                continue
            payload = result.get("result", {})
            if not isinstance(payload, dict):
                continue

            for key in (
                "n",
                "total_points",
                "anomalies_count",
                "pourcentage_anomalies",
                "max_zscore",
                "Cpk",
                "derive_detectee",
            ):
                if key in payload and key not in compact:
                    self._merge_metric(compact, key, payload[key])

            tendance_block = payload.get("tendance")
            if isinstance(tendance_block, dict):
                direction = tendance_block.get("direction")
                if direction is not None and "tendance_direction" not in compact:
                    self._merge_metric(compact, "tendance_direction", direction)

            if len(compact) >= 7:
                break

        return dict(list(compact.items())[:7])

    def _build_prescrire(self, priority: str, goal: str) -> str:
        """
        Return the hard-coded prescription for a goal and priority level.

        Args:
            priority: Priority level P1–P4.
            goal: Classified analytical goal.

        Returns:
            str: Prescription text (Python only).
        """
        goal_rules = REGLES_PRESCRIRE.get(goal, REGLES_PRESCRIRE["resume"])
        prescription = goal_rules.get(priority)
        if prescription:
            return prescription
        return REGLES_PRESCRIRE["resume"]["P4"]

    def _build_certifier(
        self,
        state: dict,
        json_compact: dict,
        priority: str,
    ) -> str:
        """
        Build the deterministic certification footer.

        Args:
            state: Shared pipeline state.
            json_compact: Compact metrics hashed for traceability.
            priority: Selected priority level.

        Returns:
            str: Certification string.
        """
        timestamp = datetime.now().isoformat()
        version = "IndustrIA v2.1"
        agents = state.get("agents_called", []) if isinstance(state, dict) else []
        target = state.get("target_column", "") if isinstance(state, dict) else ""

        hash_data = json.dumps(json_compact, sort_keys=True, ensure_ascii=False)
        sha256 = hashlib.sha256(hash_data.encode()).hexdigest()[:16]

        return (
            f"Analyse : {version} | "
            f"Cible : {target} | "
            f"Priorité : {priority} | "
            f"Agents : {len(agents)} | "
            f"Hash : {sha256} | "
            f"Horodatage : {timestamp}"
        )

    def _fewshot_block(self, profile: str) -> str:
        """Return a profile-specific few-shot XML block for the system prompt."""
        sample = PROFILE_FEWSHOTS.get(profile, PROFILE_FEWSHOTS[_DEFAULT_PROFILE])
        return f"""
<exemple profil="{profile}">
<input_json_exemple>
{sample["json"]}
</input_json_exemple>
<sortie_attendue>
OBSERVER: {sample["observer"]}
ANALYSER: {sample["analyser"]}
</sortie_attendue>
</exemple>
""".strip()

    def _build_prompt(
        self,
        json_compact: dict,
        user_profile: str,
        prescrire: str,
    ) -> list[dict[str, str]]:
        """
        Build Ollama chat messages for OBSERVER / ANALYSER generation.

        Args:
            json_compact: Compact metrics (no raw data).
            user_profile: Target user profile key.
            prescrire: Prescription text (not sent to the LLM).

        Returns:
            list[dict]: Ollama messages list.
        """
        _ = prescrire
        profile = user_profile if user_profile in PROFIL_CONFIG else _DEFAULT_PROFILE
        config = PROFIL_CONFIG[profile]
        compact_json = json.dumps(json_compact, ensure_ascii=False, indent=2)
        allowed_keys = ", ".join(json_compact.keys()) if json_compact else "aucune"
        numeric_hints = []
        for key, value in json_compact.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric_hints.append(f"{key}={value}")
        numeric_line = ", ".join(numeric_hints) if numeric_hints else "aucun"

        system_content = f"""
<system_prompt>
Rôle : Agent Interpréteur OAPC IndustrIA (industrie, capteurs, production).

Mission : produire exactement deux lignes à partir du JSON compact.
- OBSERVER = constat factuel (chiffres autorisés UNIQUEMENT depuis le JSON)
- ANALYSER = contexte / conséquence (sans inventer de cause non présente)

Profil : {profile}
Style : {config["style"]}

RÈGLES ABSOLUES :
- Aucun calcul, aucune statistique nouvelle, aucune hypothèse de cause.
- Chiffres autorisés : {numeric_line}
- Clés JSON disponibles : {allowed_keys}
- Pas de markdown, pas de liste, pas de titre, pas de PRESCRIRE, pas de CERTIFIER.

FORMAT EXACT (copier ce gabarit, deux lignes seulement) :
OBSERVER: ...
ANALYSER: ...

Variantes acceptées côté validation : OBSERVER / observer / OBSERVER : / sans deux-points.
</system_prompt>

{self._fewshot_block(profile)}

<consignes_profil_{profile}>
Respecte strictement le style du profil {profile} et le few-shot ci-dessus.
Ne cite que les valeurs numériques présentes dans input_json.
</consignes_profil_{profile}>

<input_json>
{compact_json}
</input_json>
""".strip()

        return [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": (
                    "À partir de <input_json> uniquement, écris exactement :\n"
                    "OBSERVER: [une phrase]\n"
                    "ANALYSER: [une phrase]\n"
                    "Rien d'autre."
                ),
            },
        ]

    def _call_ollama(
        self,
        messages: list[dict[str, str]],
        user_profile: str,
    ) -> str | None:
        """
        Call Ollama for narrative OBSERVER / ANALYSER lines.

        Args:
            messages: Ollama chat messages.
            user_profile: Target user profile key.

        Returns:
            str | None: Raw model text or None on failure.
        """
        profile = user_profile if user_profile in PROFIL_CONFIG else _DEFAULT_PROFILE
        config = PROFIL_CONFIG[profile]

        try:
            response = ollama.chat(
                model=_OLLAMA_MODEL,
                messages=messages,
                options={
                    "temperature": config["temperature"],
                    "num_predict": config["num_predict"],
                    "num_ctx": 4096,
                },
            )
        except Exception:
            logger.exception("agent_5_interpreter Ollama call failed")
            raise

        raw_text = ""
        if isinstance(response, dict):
            raw_text = str(response.get("message", {}).get("content", "") or "")
        else:
            message = getattr(response, "message", None)
            if message is not None:
                raw_text = str(getattr(message, "content", "") or "")

        cleaned = raw_text.strip()
        return cleaned if cleaned else None

    def _normalize_llm_text(self, text: str) -> str:
        """Strip markdown fences and light formatting before validation."""
        cleaned = text.strip()
        cleaned = re.sub(r"```[a-zA-Z]*", "", cleaned)
        cleaned = cleaned.replace("```", "")
        cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
        cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*[-*]\s+", "", cleaned, flags=re.MULTILINE)
        return cleaned.strip()

    def _collect_numeric_allowed(
        self,
        json_compact: dict,
        state: dict | None = None,
    ) -> set[float]:
        """Extrait tous les nombres autorisés (métriques + state), récursif."""
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

        walk(json_compact)
        if isinstance(state, dict):
            for bucket in ("specialist_results", "validated_results"):
                walk(state.get(bucket))
            walk(state.get("intention"))
            for text in (state.get("target_column"), state.get("question")):
                if isinstance(text, str):
                    for token in re.findall(r"\d+", text):
                        register(float(token))
        return allowed

    def _build_number_whitelist(
        self,
        json_compact: dict,
        state: dict | None = None,
    ) -> set[float]:
        """Chiffres issus des noms de colonnes / cible / question."""
        whitelist: set[float] = set()
        names: list[str] = []

        for key in ("target_column", "target"):
            val = json_compact.get(key)
            if isinstance(val, str) and val.strip():
                names.append(val.strip())

        if isinstance(state, dict):
            tc = state.get("target_column")
            if isinstance(tc, str) and tc.strip():
                names.append(tc.strip())
            q = state.get("question")
            if isinstance(q, str):
                for token in re.findall(r"\d+", q):
                    whitelist.add(float(token))

        for name in names:
            for token in re.findall(r"\d+", name):
                whitelist.add(float(token))

        return whitelist

    def _parse_sections(self, text: str) -> tuple[str, str]:
        """
        Extract OBSERVER and ANALYSER sections from model output.

        Accepts flexible labels (case, spaces, optional colon, light markdown).

        Args:
            text: Raw or fallback model output.

        Returns:
            tuple[str, str]: Observer and analyser strings.
        """
        normalized = self._normalize_llm_text(text)
        observer = ""
        analyser = ""
        for match in _OAPC_SECTION_RE.finditer(normalized):
            label = match.group("label").upper()
            content = match.group("content").strip()
            content = re.sub(r"\s+", " ", content)
            if label == "OBSERVER":
                observer = content
            elif label == "ANALYSER":
                analyser = content
        return observer, analyser

    def _has_oapc_sections(self, text: str) -> bool:
        """Return True when both OAPC labels are present with non-empty content."""
        observer, analyser = self._parse_sections(text)
        return bool(observer) and bool(analyser)

    def _number_is_allowed(
        self,
        number: float,
        allowed_numbers: set[float],
        number_whitelist: set[float],
    ) -> bool:
        """Check JSON metrics (±0.5) or column-name digits (exact)."""
        if any(abs(number - whitelisted) < 0.001 for whitelisted in number_whitelist):
            return True
        return any(abs(number - allowed) <= 0.5 for allowed in allowed_numbers)

    def _validate_output(
        self,
        text: str,
        json_compact: dict,
        user_profile: str,
        state: dict | None = None,
    ) -> dict:
        """
        Validate LLM output: flexible form, strict content.

        Form: OBSERVER / ANALYSER (case, spaces, optional colon, markdown tolerated).
        Content: forbidden words per profile; invented digits for all profiles.

        Args:
            text: Raw LLM output.
            json_compact: Allowed metrics.
            user_profile: Target user profile key.

        Returns:
            dict: Validation status and optional error message.
        """
        normalized = self._normalize_llm_text(text)

        if not self._has_oapc_sections(normalized):
            return {"valid": False, "error": "sections manquantes ou vides"}

        profile = user_profile if user_profile in PROFIL_CONFIG else _DEFAULT_PROFILE
        forbidden_words = PROFIL_CONFIG[profile]["mots_interdits"]
        lowered_text = normalized.lower()
        for word in forbidden_words:
            if word.lower() in lowered_text:
                return {"valid": False, "error": f"mot interdit: {word}"}

        allowed_numbers = self._collect_numeric_allowed(json_compact, state)
        number_whitelist = self._build_number_whitelist(json_compact, state)
        combined = allowed_numbers | number_whitelist
        if combined:
            text_for_numbers = re.sub(
                r"\bP\s*[1-4]\b", "", normalized, flags=re.IGNORECASE
            )
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
                    return {
                        "valid": False,
                        "error": f"chiffre inventé: {match}",
                    }

        return {"valid": True}

    def _get_fallback(
        self,
        goal: str,
        priority: str,
        user_profile: str,
        json_compact: dict,
    ) -> str:
        """
        Return deterministic OBSERVER / ANALYSER text when the LLM fails.

        Args:
            goal: Classified analytical goal.
            priority: Selected priority level.
            user_profile: Target user profile key.
            json_compact: Compact metrics.

        Returns:
            str: Two-line fallback narrative.
        """
        _ = goal
        profile = user_profile if user_profile in PROFIL_CONFIG else _DEFAULT_PROFILE

        if profile == "operateur":
            return (
                f"OBSERVER: Anomalie détectée.\n"
                f"ANALYSER: Niveau {priority}."
            )

        if profile == "technicien":
            return (
                f"OBSERVER: Analyse {json_compact.get('goal', 'industrielle')} terminée.\n"
                f"ANALYSER: Priorité {priority} détectée."
            )

        if profile == "ingenieur":
            sample_size = json_compact.get("n", json_compact.get("total_points", "N/A"))
            return (
                f"OBSERVER: {sample_size} points analysés.\n"
                f"ANALYSER: Résultat {priority}."
            )

        return (
            "OBSERVER: Analyse terminée.\n"
            f"ANALYSER: Action {priority} requise."
        )

    def run(self, state: AgentState | dict) -> dict:
        """
        Build prescription/certification in Python and OBSERVER/ANALYSER via LLM.

        Args:
            state: Shared LangGraph state after the statistician judge.

        Returns:
            dict: Structured interpreter result payload.
        """
        start_time = time.time()

        if isinstance(state, dict):
            state.setdefault("errors", [])
            state.setdefault("agents_called", [])

        try:
            user_profile = (
                state.get("user_profile", _DEFAULT_PROFILE)
                if isinstance(state, dict)
                else _DEFAULT_PROFILE
            )
            if user_profile not in PROFIL_CONFIG:
                user_profile = _DEFAULT_PROFILE

            validated_results = (
                state.get("validated_results", [])
                if isinstance(state, dict)
                else []
            )
            if not isinstance(validated_results, list):
                validated_results = []

            intention = state.get("intention", {}) if isinstance(state, dict) else {}
            goal = intention.get("goal", "resume") if isinstance(intention, dict) else "resume"

            priority = self._determine_priority(validated_results, goal)
            json_compact = self._build_json_compact(validated_results, state)
            prescrire = self._build_prescrire(priority, goal)
            certifier = self._build_certifier(state, json_compact, priority)

            raw_text: str | None = None
            for _attempt in range(3):
                messages = self._build_prompt(json_compact, user_profile, prescrire)
                try:
                    raw_text = self._call_ollama(messages, user_profile)
                except Exception:
                    raw_text = None
                    continue

                if raw_text:
                    validation = self._validate_output(
                        raw_text,
                        json_compact,
                        user_profile,
                        state,
                    )
                    if validation["valid"]:
                        break
                    logger.warning(
                        "agent_5 validation attempt %s (%s): %s",
                        _attempt + 1,
                        user_profile,
                        validation.get("error"),
                    )

            final_validation = (
                self._validate_output(raw_text, json_compact, user_profile, state)
                if raw_text
                else {"valid": False}
            )
            if not raw_text or not final_validation["valid"]:
                logger.warning(
                    "agent_5 fallback actif pour profil %s: %s",
                    user_profile,
                    final_validation.get("error", "sortie vide"),
                )
                raw_text = self._get_fallback(goal, priority, user_profile, json_compact)

            observer, analyser = self._parse_sections(raw_text)

            rapport_final = {
                "observer": observer,
                "analyser": analyser,
                "prescrire": prescrire,
                "certifier": certifier,
                "priority": priority,
                "user_profile": user_profile,
                "goal": goal,
            }

            if isinstance(state, dict):
                state["explanation"] = observer
                state["recommendation"] = prescrire
                state["rapport_oapc"] = rapport_final
                state["priority"] = priority
                state["anomaly_detected"] = priority in ("P1", "P2")
                state["confidence"] = (
                    "haute" if len(validated_results) >= 2 else "faible"
                )
                if "agent_5_interpreter" not in state["agents_called"]:
                    state["agents_called"].append("agent_5_interpreter")

            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "agent_5_interpreter",
                "status": "success",
                "rapport": rapport_final,
                "execution_time_ms": execution_time_ms,
                "error": None,
            }
        except Exception as exc:
            logger.exception("agent_5_interpreter failed")
            if isinstance(state, dict):
                state["errors"].append(str(exc))
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "agent_5_interpreter",
                "status": "error",
                "rapport": {},
                "execution_time_ms": execution_time_ms,
                "error": str(exc),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    state_test: dict = {
        "intention": {"goal": "detection_anomalies"},
        "target_column": "inducteur_1",
        "agents_called": [
            "agent_1_analyst",
            "agent_2_sql",
            "ZScoreSpecialist",
            "SpcSpecialist",
        ],
        "validated_results": [
            {
                "agent": "ZScoreSpecialist",
                "status": "success",
                "judge_valid": True,
                "result": {
                    "anomalies_count": 13,
                    "bruit_capteur_count": 2,
                    "anomalie_process_count": 11,
                    "max_zscore": 4.7,
                    "pourcentage_anomalies": 13.0,
                    "total_points": 100,
                },
            }
        ],
        "judge_warnings": [],
    }

    agent = InterpreterAgent()

    for profil in ["operateur", "technicien", "ingenieur", "directeur"]:
        state_test["user_profile"] = profil
        result = agent.run(state_test)

        print(f"\n{'=' * 50}")
        print(f"PROFIL : {profil}")
        print(f"Status : {result['status']}")
        if result["status"] == "success":
            rapport = result["rapport"]
            print(f"Priorité  : {rapport['priority']}")
            print(f"OBSERVER  : {rapport['observer']}")
            print(f"ANALYSER  : {rapport['analyser']}")
            print(f"PRESCRIRE : {rapport['prescrire']}")
            print(f"CERTIFIER : {rapport['certifier'][:60]}...")
        print(f"Temps     : {result['execution_time_ms']}ms")
