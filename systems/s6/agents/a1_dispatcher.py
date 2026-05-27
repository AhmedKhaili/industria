"""
A1 — Dispatcher priorités P1–P4 (Python pur).
Lit specialist_results uniquement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from systems.s6 import prep

if TYPE_CHECKING:
    from systems.s1.client_context import ClientContext


def run(
    specialist_results: list[dict],
    intent: dict,
    context: "ClientContext",
    profile: str,
) -> dict:
    try:
        cfg = prep.reco_config(context)
        seuils = cfg.get("seuils_cpk", {})
        p1_cpk = float(seuils.get("p1_sous", 1.0))
        p2_cpk = float(seuils.get("p2_sous", 1.33))
        p3_cpk = float(seuils.get("p3_sous", 1.67))
        zs = cfg.get("zscore", {})
        z_p1 = float(zs.get("absolu_p1", 3.0))
        anom_p1 = float(zs.get("anomaly_pct_p1", 20.0))
        anom_p2 = float(zs.get("anomaly_pct_p2", 10.0))
        responsable = prep.responsable_for(context, profile)

        raw_items: list[dict] = []

        for result in specialist_results:
            if result.get("status") != "success":
                continue
            agent = prep.canonical_agent(result.get("agent"))
            p = result.get("result") or {}
            cause_key, cause_label = prep.infer_cause_key(intent, result, cfg)

            if agent == "cp_cpk":
                cpk = p.get("Cpk")
                if not isinstance(cpk, (int, float)):
                    continue
                cpk_f = float(cpk)
                col = p.get("colonne", cause_label)
                if cpk_f < p1_cpk:
                    raw_items.append(
                        _item(
                            "P1",
                            "capabilite_critique",
                            responsable,
                            prep.delai_for(cfg, "P1"),
                            f"Cpk = {cpk_f} sur {col} (< {p1_cpk}) — non capable.",
                            cause_key,
                            cause_label,
                            use_llm=True,
                            chiffres={"Cpk": cpk_f, "colonne": col},
                        )
                    )
                elif cpk_f < p2_cpk:
                    raw_items.append(
                        _item(
                            "P2",
                            "capabilite_limite",
                            responsable,
                            prep.delai_for(cfg, "P2"),
                            f"Cpk = {cpk_f} sur {col} — sous le seuil EN9100 (1,33).",
                            cause_key,
                            cause_label,
                            use_llm=True,
                            chiffres={"Cpk": cpk_f, "colonne": col},
                        )
                    )
                elif cpk_f < p3_cpk:
                    raw_items.append(
                        _item(
                            "P3",
                            "capabilite_surveillance",
                            responsable,
                            prep.delai_for(cfg, "P3"),
                            f"Cpk = {cpk_f} sur {col} — zone limite, surveillance renforcée.",
                            cause_key,
                            cause_label,
                            use_llm=False,
                            chiffres={"Cpk": cpk_f, "colonne": col},
                        )
                    )

            elif agent == "zscore":
                max_z = p.get("max_zscore")
                pct = p.get("pourcentage_anomalies")
                col = p.get("colonne", cause_label)
                if isinstance(max_z, (int, float)) and float(max_z) >= z_p1:
                    raw_items.append(
                        _item(
                            "P1",
                            "anomalie_ponctuelle",
                            responsable,
                            prep.delai_for(cfg, "P1"),
                            f"Signal anormal sur {col} (écart max {max_z}).",
                            cause_key,
                            cause_label,
                            use_llm=True,
                            chiffres={"max_zscore": float(max_z), "colonne": col},
                        )
                    )
                elif isinstance(pct, (int, float)) and float(pct) >= anom_p1:
                    raw_items.append(
                        _item(
                            "P1",
                            "anomalies_massives",
                            responsable,
                            prep.delai_for(cfg, "P1"),
                            f"{pct}% de mesures anormales sur {col}.",
                            cause_key,
                            cause_label,
                            use_llm=True,
                            chiffres={"pourcentage_anomalies": float(pct)},
                        )
                    )
                elif isinstance(pct, (int, float)) and float(pct) >= anom_p2:
                    raw_items.append(
                        _item(
                            "P2",
                            "anomalies_moderees",
                            responsable,
                            prep.delai_for(cfg, "P2"),
                            f"{pct}% d'anomalies sur {col} — analyse sous 48h.",
                            cause_key,
                            cause_label,
                            use_llm=True,
                            chiffres={"pourcentage_anomalies": float(pct)},
                        )
                    )

            elif agent == "mann_kendall":
                if not p.get("significatif"):
                    continue
                tendance = str(p.get("tendance", "")).lower()
                degrading = any(
                    w in tendance
                    for w in ("décro", "decro", "baisse", "degrad", "hausse défavorable")
                )
                col = p.get("colonne", cause_label)
                if degrading:
                    raw_items.append(
                        _item(
                            "P2",
                            "tendance_degradante",
                            responsable,
                            prep.delai_for(cfg, "P2"),
                            f"Tendance {p.get('tendance')} sur {col} (p = {p.get('p_value')}).",
                            cause_key,
                            cause_label,
                            use_llm=True,
                            chiffres={"p_value": p.get("p_value"), "colonne": col},
                        )
                    )

            elif agent == "anova_kruskal":
                if p.get("significatif"):
                    raw_items.append(
                        _item(
                            "P3",
                            "effet_facteur",
                            responsable,
                            prep.delai_for(cfg, "P3"),
                            f"Effet significatif ({p.get('methode_choisie')}, p = {p.get('p_value')}).",
                            cause_key,
                            cause_label,
                            use_llm=False,
                            chiffres={"p_value": p.get("p_value")},
                        )
                    )

        p1_items = [i for i in raw_items if i["priorite"] == "P1"]
        other = [i for i in raw_items if i["priorite"] != "P1"]
        grouped_other = _group_by_cause(other, cfg)
        items = p1_items + grouped_other

        if not items:
            items = [
                _item(
                    "P4",
                    "surveillance",
                    responsable,
                    prep.delai_for(cfg, "P4"),
                    "Processus dans les tolérances — poursuivre la surveillance standard.",
                    "global:surveillance",
                    "ensemble du processus",
                    use_llm=False,
                    chiffres={},
                )
            ]

        items = _apply_profile_structure(items, context, profile)

        return {"error": None, "items": items}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "items": []}


def _item(
    priorite: str,
    action_type: str,
    responsable: str,
    delai: str,
    justification: str,
    cause_key: str,
    cause_label: str,
    *,
    use_llm: bool,
    chiffres: dict,
) -> dict:
    return {
        "priorite": priorite,
        "action_type": action_type,
        "responsable": responsable,
        "delai": delai,
        "justification": justification,
        "cause_key": cause_key,
        "cause_label": cause_label,
        "use_llm": use_llm,
        "chiffres": chiffres,
        "action": "",
        "rag_excerpt": "",
        "rag_used": False,
    }


def _group_by_cause(items: list[dict], cfg: dict) -> list[dict]:
    """P2/P3 agrégées par cause_key ; P1 jamais passées ici."""
    p2p3: dict[str, list[dict]] = {}
    for it in items:
        if it["priorite"] in ("P2", "P3"):
            p2p3.setdefault(it["cause_key"], []).append(it)

    out: list[dict] = []
    for key, group in p2p3.items():
        worst = min(group, key=lambda x: prep.priority_rank(x["priorite"]))
        labels = sorted({g["cause_label"] for g in group})
        justifs = " | ".join(g["justification"] for g in group[:4])
        merged = dict(worst)
        merged["justification"] = f"{justifs} (regroupé : {', '.join(labels)})"
        merged["use_llm"] = any(g["use_llm"] for g in group)
        merged["chiffres"] = group[0].get("chiffres", {})
        out.append(merged)

    return out


def _apply_profile_structure(
    items: list[dict], context: "ClientContext", profile: str
) -> list[dict]:
    detail = prep.profile_detail_config(context, profile)
    allowed = set(detail.get("inclure_priorites", ["P1", "P2", "P3", "P4"]))
    p1 = [i for i in items if i["priorite"] == "P1"]
    rest = [i for i in items if i["priorite"] != "P1" and i["priorite"] in allowed]

    if detail.get("agreger_p2_p3") and profile in ("directeur", "operateur"):
        p23 = [i for i in rest if i["priorite"] in ("P2", "P3")]
        p4 = [i for i in rest if i["priorite"] == "P4"]
        rest_out: list[dict] = []
        if p23:
            worst = min(p23, key=lambda x: prep.priority_rank(x["priorite"]))
            summary = dict(worst)
            summary["justification"] = " ; ".join(i["justification"] for i in p23[:6])
            summary["cause_label"] = "points de vigilance consolidés"
            summary["use_llm"] = any(i["use_llm"] for i in p23)
            rest_out.append(summary)
        max_extra = int(detail.get("max_lignes_hors_p1", 2))
        rest_out.extend(p4[:1])
        if profile == "directeur":
            rest_out = rest_out[:max_extra]
        return p1 + rest_out

    return p1 + rest
