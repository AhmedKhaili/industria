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
_MAX_JSON_KEYS = 4
_NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-zPp])-?\d+(?:[.,]\d+)?")

PRIORITY_DELAI_MINUTES: dict[str, float] = {
    "P1": 15.0,
    "P2": 30.0,
    "P3": 240.0,
}

PROFIL_CONFIG: dict[str, dict[str, Any]] = {
    "operateur": {
        "num_predict": 100,
        "temperature": 0.1,
        "style": (
            "2 phrases max. Verdict binaire. "
            "Action immédiate. "
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
            "sigma",
            "ucl",
            "lcl",
            "cpk",
            "ewma",
            "cusum",
        ],
    },
    "technicien": {
        "num_predict": 180,
        "temperature": 0.1,
        "style": (
            "3 phrases max. Diagnostic clair. "
            "Composant concerné. "
            "Action de maintenance."
        ),
        "mots_interdits": [],
    },
    "ingenieur": {
        "num_predict": 250,
        "temperature": 0.1,
        "style": (
            "4-5 phrases. Analyse complète. "
            "Méthodes citées. Valeurs clés. "
            "Recommandation technique."
        ),
        "mots_interdits": [],
    },
    "directeur": {
        "num_predict": 120,
        "temperature": 0.1,
        "style": (
            "2 phrases max. Impact business. "
            "TRS/OEE. Conformité EN9100. "
            "Coût si non traité."
        ),
        "mots_interdits": [
            "z-score",
            "zscore",
            "ucl",
            "lcl",
            "shapiro",
            "anova",
            "p-value",
            "sigma",
            "ewma",
            "cusum",
        ],
    },
}

FALLBACK_TEMPLATES: dict[str, str] = {
    "operateur": (
        "Anomalie détectée sur {target}. "
        "Priorité {priority}. "
        "Intervention requise."
    ),
    "technicien": (
        "Analyse de {target} terminée. "
        "Priorité {priority} détectée. "
        "Vérifier le composant concerné."
    ),
    "ingenieur": (
        "Analyse statistique de {target} : "
        "priorité {priority} identifiée. "
        "{n_specialistes} méthodes appliquées."
    ),
    "directeur": (
        "Analyse {target} : priorité {priority}. "
        "Action requise pour maintenir "
        "la conformité EN9100."
    ),
}

FEWSHOT_BY_PROFILE: dict[str, dict[str, str]] = {
    "operateur": {
        "json": (
            '{"priority":"P2","target":"four_3",'
            '"anomaly_detected":true}'
        ),
        "output": (
            "Anomalie détectée sur le four 3. "
            "Intervention dans les 30 minutes."
        ),
    },
    "technicien": {
        "json": (
            '{"priority":"P2","target":"inducteur_1",'
            '"n_specialistes":3,"anomaly_detected":true}'
        ),
        "output": (
            "L'inducteur 1 présente des anomalies confirmées par "
            "3 méthodes statistiques. Une intervention maintenance est "
            "requise dans les 30 minutes."
        ),
    },
    "ingenieur": {
        "json": (
            '{"priority":"P2","target":"inducteur_1",'
            '"n_specialistes":3,"anomaly_detected":true}'
        ),
        "output": (
            "L'analyse multi-méthodes (3 spécialistes) de l'inducteur 1 "
            "confirme des anomalies de niveau P2. Les méthodes z-score, "
            "SPC et EWMA convergent vers une anomalie process nécessitant "
            "une intervention technique urgente."
        ),
    },
    "directeur": {
        "json": (
            '{"priority":"P2","target":"inducteur_1",'
            '"n_specialistes":3,"anomaly_detected":true}'
        ),
        "output": (
            "Anomalie confirmée sur inducteur 1. "
            "Risque de non-conformité EN9100. "
            "Action corrective requise sous 30 minutes "
            "pour éviter impact sur le TRS."
        ),
    },
}


class Agent6bSynthesis:
    """Agent 6b — executive summary from compact aggregates (never raw 6a texts)."""

    def _is_validated_specialist(self, result: dict) -> bool:
        """Return True when a validated_results entry counts as a specialist."""
        if not isinstance(result, dict):
            return False
        if result.get("judge_valid") is False:
            return False
        status = str(result.get("status", "")).lower()
        return status in ("success", "ok", "valid")

    def _count_specialists(self, state: dict) -> int:
        """Count judge-validated specialists in pipeline state."""
        validated = state.get("validated_results", [])
        if not isinstance(validated, list):
            return 0
        return sum(1 for item in validated if self._is_validated_specialist(item))

    def _aggregate_anomalies(self, state: dict) -> int | None:
        """
        Sum anomaly counts from specialist payloads (Python only).

        Args:
            state: Shared pipeline state.

        Returns:
            int | None: Total anomalies when at least one count exists.
        """
        validated = state.get("validated_results", [])
        if not isinstance(validated, list):
            return None

        total = 0
        found = False
        for item in validated:
            if not self._is_validated_specialist(item):
                continue
            payload = item.get("result", {})
            if not isinstance(payload, dict):
                continue
            count = payload.get("anomalies_count")
            if isinstance(count, (int, float)) and not isinstance(count, bool):
                total += int(count)
                found = True

        return total if found else None

    def _resolve_priority(self, state: dict) -> str:
        """Read priority from state or OAPC report."""
        priority = state.get("priority")
        if isinstance(priority, str) and priority.upper().startswith("P"):
            return priority.upper()

        rapport = state.get("rapport_oapc", {})
        if isinstance(rapport, dict):
            rapport_priority = rapport.get("priority")
            if isinstance(rapport_priority, str) and rapport_priority.strip():
                return rapport_priority.strip().upper()

        return "P4"

    def _resolve_goal(self, state: dict) -> str:
        """Read analytical goal from intention block."""
        intention = state.get("intention", {})
        if isinstance(intention, dict):
            goal = intention.get("goal")
            if isinstance(goal, str) and goal.strip():
                return goal.strip()
        return "resume"

    def _resolve_anomaly_detected(self, state: dict, priority: str) -> bool:
        """Resolve anomaly flag from state or priority level."""
        flag = state.get("anomaly_detected")
        if isinstance(flag, bool):
            return flag
        return priority in ("P1", "P2")

    def _build_json_compact(self, state: dict) -> dict:
        """
        Build compact JSON for the LLM (max 4 keys, no 6a texts or DataFrames).

        Args:
            state: Shared LangGraph state.

        Returns:
            dict: At most four aggregate keys for synthesis.
        """
        priority = self._resolve_priority(state)
        target = state.get("target_column", "")
        if not isinstance(target, str):
            target = str(target or "")

        n_specialistes = self._count_specialists(state)
        anomaly_detected = self._resolve_anomaly_detected(state, priority)

        goal = self._resolve_goal(state)
        n_anomalies = self._aggregate_anomalies(state)

        candidate: dict[str, Any] = {
            "priority": priority,
            "goal": goal,
            "target": target.strip(),
            "n_specialistes": n_specialistes,
            "anomaly_detected": anomaly_detected,
        }
        if n_anomalies is not None:
            candidate["n_anomalies"] = n_anomalies

        key_order = [
            "priority",
            "target",
            "n_specialistes",
            "anomaly_detected",
            "goal",
            "n_anomalies",
        ]
        compact: dict[str, Any] = {}
        for key in key_order:
            if key in candidate and len(compact) < _MAX_JSON_KEYS:
                compact[key] = candidate[key]

        return compact

    def _fewshot_block(self, user_profile: str) -> str:
        """Build profile-specific few-shot XML for the synthesis prompt."""
        sample = FEWSHOT_BY_PROFILE.get(user_profile)
        if not sample:
            return ""
        return f"""
<exemple>
<json>{sample["json"]}</json>
<resume>{sample["output"]}</resume>
</exemple>
""".strip()

    def _build_prompt(
        self,
        json_compact: dict,
        user_profile: str,
    ) -> list[dict[str, str]]:
        """
        Build Ollama messages with XML structure for executive synthesis.

        Args:
            json_compact: Pre-aggregated metrics (max 4 keys).
            user_profile: User profile key.

        Returns:
            list[dict]: Chat messages for Ollama.
        """
        profile = user_profile if user_profile in PROFIL_CONFIG else _DEFAULT_PROFILE
        config = PROFIL_CONFIG[profile]
        compact_json = json.dumps(json_compact, ensure_ascii=False, indent=2)

        numeric_hints = []
        for key, value in json_compact.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric_hints.append(f"{key}={value}")
        priority = json_compact.get("priority", "")
        if isinstance(priority, str) and priority in PRIORITY_DELAI_MINUTES:
            numeric_hints.append(f"delai_minutes={PRIORITY_DELAI_MINUTES[priority]:.0f}")
        allowed_numbers = ", ".join(numeric_hints) if numeric_hints else "aucun"

        system_content = f"""
<system_prompt>
Rôle : synthétiseur industriel IndustrIA (Agent 6b).
Mission : rédiger le résumé exécutif global à partir des agrégats JSON uniquement.

Profil lecteur : {profile}
Style : {config["style"]}

RÈGLES ABSOLUES :
- Aucun calcul, aucune hypothèse non fournie dans le JSON.
- Chiffres autorisés uniquement : {allowed_numbers}, et chiffres présents dans le nom de la cible.
- Ne pas recopier d'interprétations de spécialistes non fournies dans le JSON.
- Pas de titre, pas de markdown, pas de préambule.
- Réponse : texte direct, 3 à 5 phrases selon le profil.
</system_prompt>

{self._fewshot_block(profile)}

<agregats>
{compact_json}
</agregats>
""".strip()

        return [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": (
                    "Rédige le résumé exécutif pour cette analyse industrielle. "
                    "Texte seul, sans formatage."
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
            logger.exception("agent_6b_synthesis Ollama call failed")
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

    def _collect_numeric_allowed(
        self,
        json_compact: dict,
        state: dict | None = None,
    ) -> set[float]:
        """Extrait tous les nombres autorisés depuis compact + state."""
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

    def _number_whitelist(
        self,
        json_compact: dict,
        state: dict | None = None,
    ) -> set[float]:
        """Chiffres autorisés : cible, priorité, délais standard."""
        whitelist: set[float] = set()

        target = json_compact.get("target", json_compact.get("target_column", ""))
        if isinstance(target, str):
            for token in re.findall(r"\d+", target):
                whitelist.add(float(token))

        priority = json_compact.get("priority", "")
        if isinstance(priority, str):
            match = re.match(r"P(\d)", priority.upper())
            if match:
                whitelist.add(float(match.group(1)))
            delai = PRIORITY_DELAI_MINUTES.get(priority.upper())
            if delai is not None:
                whitelist.add(delai)

        if isinstance(state, dict):
            sp = state.get("priority")
            if isinstance(sp, str):
                m = re.match(r"P(\d)", sp.upper())
                if m:
                    whitelist.add(float(m.group(1)))

        return whitelist

    def _number_is_allowed(
        self,
        number: float,
        allowed_numbers: set[float],
        number_whitelist: set[float],
    ) -> bool:
        """Check aggregate or whitelist tolerance (±0.5 for metrics)."""
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
        Validate synthesis text (flexible form, strict numeric content).

        Args:
            text: Generated executive summary.
            json_compact: Aggregates sent to the LLM.
            user_profile: User profile key.

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

        allowed_numbers = self._collect_numeric_allowed(json_compact, state)
        number_whitelist = self._number_whitelist(json_compact, state)
        if profile == "directeur":
            number_whitelist.add(100.0)
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
                    return {"valid": False, "error": f"chiffre inventé: {match}"}

        return {"valid": True}

    def _apply_fallback(
        self,
        user_profile: str,
        json_compact: dict,
    ) -> str:
        """
        Return deterministic fallback executive summary.

        Args:
            user_profile: User profile key.
            json_compact: Compact aggregates for template variables.

        Returns:
            str: Fallback text.
        """
        profile = user_profile if user_profile in PROFIL_CONFIG else _DEFAULT_PROFILE
        template = FALLBACK_TEMPLATES.get(
            profile,
            FALLBACK_TEMPLATES[_DEFAULT_PROFILE],
        )

        context = {
            "target": json_compact.get("target", json_compact.get("target_column", "")),
            "priority": json_compact.get("priority", "P4"),
            "n_specialistes": json_compact.get("n_specialistes", 0),
            "goal": json_compact.get("goal", "analyse"),
            "n_anomalies": json_compact.get("n_anomalies", ""),
        }

        class _SafeFormatDict(dict):
            def __missing__(self, key: str) -> str:
                return ""

        try:
            return template.format_map(_SafeFormatDict(context))
        except (KeyError, ValueError):
            return FALLBACK_TEMPLATES[_DEFAULT_PROFILE].format_map(_SafeFormatDict(context))

    def run(self, state: dict) -> dict:
        """
        Generate executive summary and store it in ``state['resume_executif']``.

        Args:
            state: Shared LangGraph state.

        Returns:
            dict: Structured 6b result payload.
        """
        start_time = time.time()
        used_fallback = False
        texte_final = ""
        status = "error"
        error_message: str | None = None

        user_profile = state.get("user_profile", _DEFAULT_PROFILE)
        if user_profile not in PROFIL_CONFIG:
            user_profile = _DEFAULT_PROFILE

        json_compact = self._build_json_compact(state if isinstance(state, dict) else {})

        if not json_compact:
            texte_final = self._apply_fallback(user_profile, {"target": "", "priority": "P4"})
            used_fallback = True
            status = "fallback"
        else:
            raw_text: str | None = None
            for _attempt in range(3):
                messages = self._build_prompt(json_compact, user_profile)
                raw_text = self._call_ollama(messages, user_profile)
                if not raw_text:
                    continue
                validation = self._validate_output(
                    raw_text,
                    json_compact,
                    user_profile,
                    state,
                )
                if validation["valid"]:
                    texte_final = self._normalize_text(raw_text)
                    status = "success"
                    break
                logger.warning(
                    "agent_6b validation (%s): %s",
                    user_profile,
                    validation.get("error"),
                )

            if status != "success":
                texte_final = self._apply_fallback(user_profile, json_compact)
                used_fallback = True
                status = "fallback"

        if isinstance(state, dict):
            state["resume_executif"] = texte_final

        execution_time_ms = int((time.time() - start_time) * 1000)
        return {
            "agent": "agent_6b_synthesis",
            "status": status,
            "resume_executif": texte_final,
            "user_profile": user_profile,
            "used_fallback": used_fallback,
            "execution_time_ms": execution_time_ms,
            "error": error_message,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    state_test: dict = {
        "question": "Y a-t-il des anomalies sur les capteurs ?",
        "target_column": "inducteur_1",
        "intention": {"goal": "detection_anomalies"},
        "anomaly_detected": True,
        "validated_results": [
            {
                "agent": "ZScoreSpecialist",
                "status": "success",
                "judge_valid": True,
                "result": {"anomalies_count": 13},
            },
            {
                "agent": "SpcSpecialist",
                "status": "success",
                "judge_valid": True,
            },
            {
                "agent": "EwmaCusumSpecialist",
                "status": "success",
                "judge_valid": True,
            },
        ],
        "rapport_oapc": {
            "priority": "P2",
            "observer": "13 anomalies détectées.",
            "prescrire": "Intervention 30 minutes.",
        },
        "interpretations": {
            "ZScoreSpecialist": "13 anomalies process.",
            "SpcSpecialist": "3 points hors limites.",
            "EwmaCusumSpecialist": "Dérive progressive.",
        },
    }

    agent = Agent6bSynthesis()

    for profil in ["operateur", "technicien", "ingenieur", "directeur"]:
        state_test["user_profile"] = profil
        result = agent.run(state_test)

        print(f"\n{'=' * 50}")
        print(f"PROFIL   : {profil}")
        print(f"Status   : {result['status']}")
        print(f"Résumé   : {result['resume_executif']}")
        print(f"Fallback : {result['used_fallback']}")
        print(f"Temps    : {result['execution_time_ms']}ms")
