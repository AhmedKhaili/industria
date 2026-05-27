"""
Pré-formatage des entrées S5 — zéro dict brut envoyé au LLM.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext

_AGENT_ALIASES = {
    "CpCpkSpecialist": "cp_cpk",
    "AnovaKruskalSpecialist": "anova_kruskal",
    "MannKendallSpecialist": "mann_kendall",
    "ZScoreSpecialist": "zscore",
    "SpcSpecialist": "spc",
    "EwmaCusumSpecialist": "ewma_cusum",
    "RegressionSpecialist": "regression",
}


def canonical_agent(agent: str | None) -> str:
    if not agent:
        return ""
    return _AGENT_ALIASES.get(agent, str(agent).strip().lower())


def profile_config(context: "ClientContext", profile: str) -> dict:
    profils = context.profils or {}
    default = profils.get("technicien", {})
    if not isinstance(default, dict):
        default = {}
    cfg = profils.get(profile, default)
    return cfg if isinstance(cfg, dict) else default


def descriptions_list(s4_output: dict) -> list[str]:
    items: list[str] = []
    raw = s4_output.get("descriptions_tabulaires", "")
    if isinstance(raw, list):
        items.extend(str(d).strip() for d in raw if d)
    elif isinstance(raw, str) and raw.strip():
        items.extend(p.strip() for p in raw.split("\n\n") if p.strip())
    for table in s4_output.get("tables") or []:
        desc = table.get("description") if isinstance(table, dict) else None
        tid = table.get("id", "tableau") if isinstance(table, dict) else "tableau"
        if desc:
            items.append(f"Tableau {tid} : {desc}")
    for graph in s4_output.get("graphs", s4_output.get("charts", [])) or []:
        if not isinstance(graph, dict):
            continue
        desc = graph.get("description")
        gtype = graph.get("type", "graphique")
        title = graph.get("title", gtype)
        if desc:
            items.append(f"Graphique {title} ({gtype}) : {desc}")
    return items


def flatten_numbers(obj: Any, prefix: str = "") -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.extend(flatten_numbers(v, key))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.extend(flatten_numbers(v, f"{prefix}[{i}]"))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        try:
            out.append((prefix, float(obj)))
        except (TypeError, ValueError):
            pass
    return out


def reference_numbers_for_result(result: dict) -> dict[str, float]:
    """Nombres de référence pour un résultat spécialiste."""
    refs: dict[str, float] = {}
    payload = result.get("result") or {}
    if not isinstance(payload, dict):
        return refs
    agent = canonical_agent(result.get("agent"))
    for key, val in flatten_numbers(payload):
        refs[f"{agent}.{key}"] = val
        refs[key.split(".")[-1]] = val
    return refs


def format_specialist_prompt(result: dict) -> str:
    """Texte prêt pour R1 — chiffres clés + unités + seuils."""
    agent = canonical_agent(result.get("agent"))
    status = result.get("status", "")
    if status != "success":
        return (
            f"Spécialiste : {agent}\n"
            f"Statut calcul : {status}\n"
            f"Message : {result.get('error') or result.get('result', {}).get('reason', 'non disponible')}\n"
            "Rédige une phrase factuelle courte pour l'utilisateur."
        )

    p = result.get("result") or {}
    lines = [f"Spécialiste : {agent}", "Données certifiées Python (ne modifie aucun chiffre) :"]

    if agent == "cp_cpk":
        lines.extend(
            [
                f"- Variable : {p.get('colonne', 'N/A')}",
                f"- Cpk = {p.get('Cpk')}",
                f"- Cp = {p.get('Cp')}",
                f"- Conforme EN9100 (seuil Cpk >= 1,33) : {p.get('conforme_EN9100')}",
                f"- Interprétation : {p.get('interpretation_Cpk', '')}",
                f"- Hors limites % : {p.get('hors_limites_pct')}",
                f"- n = {p.get('n')}",
            ]
        )
    elif agent == "anova_kruskal":
        lines.extend(
            [
                f"- Méthode : {p.get('methode_choisie')}",
                f"- p-value = {p.get('p_value')}",
                f"- Significatif (alpha={p.get('alpha', 0.05)}) : {p.get('significatif')}",
                f"- Interprétation : {p.get('interpretation', '')}",
            ]
        )
    elif agent == "mann_kendall":
        lines.extend(
            [
                f"- Variable : {p.get('colonne', 'N/A')}",
                f"- Tendance : {p.get('tendance')}",
                f"- p-value = {p.get('p_value')}",
                f"- Pente Sen = {p.get('sen_slope')}",
            ]
        )
    elif agent == "zscore":
        lines.extend(
            [
                f"- Anomalies détectées : {p.get('nb_anomalies', p.get('nombre_anomalies'))}",
                f"- Pourcentage anomalies : {p.get('pourcentage_anomalies')}",
            ]
        )
    else:
        for key, val in list(p.items())[:12]:
            if isinstance(val, (int, float, str, bool)) or val is None:
                lines.append(f"- {key} = {val}")

    lines.append(
        "\nConsigne : rédige 2 à 4 phrases en français, langage clair, "
        "en citant les chiffres EXACTEMENT comme ci-dessus."
    )
    return "\n".join(lines)


def python_fallback_interpretation(result: dict) -> str:
    """Résumé Python si LLM indisponible."""
    agent = canonical_agent(result.get("agent"))
    if result.get("status") != "success":
        reason = result.get("error") or (result.get("result") or {}).get("reason", "")
        return f"Analyse {agent} : calcul non disponible ({reason})."

    p = result.get("result") or {}
    if agent == "cp_cpk":
        cpk = p.get("Cpk")
        conforme = p.get("conforme_EN9100")
        col = p.get("colonne", "")
        verdict = "conforme" if conforme else "non conforme"
        return (
            f"Pour {col}, Cpk = {cpk} : pièce {verdict} au regard du seuil EN9100 (Cpk >= 1,33). "
            f"{p.get('interpretation_Cpk', '')}"
        )
    if agent == "anova_kruskal":
        sig = p.get("significatif")
        pval = p.get("p_value")
        if sig:
            return (
                f"La comparaison de groupes ({p.get('methode_choisie')}) montre une "
                f"différence significative (p = {pval})."
            )
        return (
            f"Aucune différence significative entre groupes "
            f"({p.get('methode_choisie')}, p = {pval})."
        )
    if agent == "mann_kendall":
        return (
            f"Tendance sur {p.get('colonne')} : {p.get('tendance')} "
            f"(p = {p.get('p_value')}, pente Sen = {p.get('sen_slope')})."
        )
    return f"Résultat {agent} : " + ", ".join(
        f"{k}={v}" for k, v in list(p.items())[:6] if isinstance(v, (int, float, str))
    )


def format_graph_prompt(description: str, index: int) -> str:
    return (
        f"Graphique n°{index + 1}\n"
        f"Description certifiée :\n{description}\n\n"
        "Rédige 1 à 2 phrases expliquant ce que montre le graphique, "
        "sans inventer de chiffres absents de la description."
    )


def extract_numbers_from_text(text: str) -> list[float]:
    found: list[float] = []
    for m in re.finditer(r"-?\d+(?:[.,]\d+)?", text):
        s = m.group().replace(",", ".")
        try:
            found.append(float(s))
        except ValueError:
            continue
    return found


def verify_number_against_refs(value: float, refs: dict[str, float]) -> tuple[str, float | None]:
    """Retourne (Accept|Review|Reject, meilleur écart relatif)."""
    if not refs:
        return "Accept", None
    best_rel = None
    matched = False
    for ref in refs.values():
        if ref == 0:
            if abs(value - ref) < 1e-6:
                matched = True
                best_rel = 0.0
            continue
        rel = abs(value - ref) / abs(ref)
        if rel <= 0.01:
            return "Accept", rel
        if best_rel is None or rel < best_rel:
            best_rel = rel
        if rel <= 0.05:
            matched = True
    if matched and best_rel is not None:
        return "Review", best_rel
    if best_rel is not None and best_rel > 0.05:
        return "Reject", best_rel
    return "Reject", best_rel


def compute_fidelity_score(interpretations: list[dict]) -> float:
    if not interpretations:
        return 0.0
    scores = []
    for item in interpretations:
        st = item.get("statut", "")
        if st == "Accept":
            scores.append(1.0)
        elif st == "Review":
            scores.append(0.75)
        elif st == "fallback":
            scores.append(0.9)
        else:
            scores.append(0.3)
    return round(sum(scores) / len(scores), 3)
