import hashlib
import io
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import ollama
import pandas as pd
import plotly.graph_objects as go
from reportlab.lib import colors
from reportlab.lib.enums import (
    TA_CENTER,
    TA_LEFT,
    TA_RIGHT,
    TA_JUSTIFY,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from state.schema import AgentState

logger = logging.getLogger(__name__)

COULEURS_PRIORITE = {
    "P1": colors.HexColor("#DC2626"),
    "P2": colors.HexColor("#EA580C"),
    "P3": colors.HexColor("#CA8A04"),
    "P4": colors.HexColor("#16A34A"),
}

DELAIS_INTERVENTION = {
    "P1": "Immédiat — arrêt requis",
    "P2": "< 30 minutes",
    "P3": "< 4 heures",
    "P4": "Prochaine maintenance planifiée",
}

RESPONSABLE_PROFIL = {
    "operateur": "Opérateur de ligne",
    "technicien": "Technicien maintenance",
    "ingenieur": "Ingénieur méthodes / qualité",
    "directeur": "Responsable de production",
}

_AGENT_CANONICAL = {
    "ZScoreSpecialist": "zscore",
    "zscore": "zscore",
    "SpcSpecialist": "spc",
    "spc": "spc",
    "EwmaCusumSpecialist": "ewma_cusum",
    "ewma_cusum": "ewma_cusum",
    "CpCpkSpecialist": "cp_cpk",
    "cp_cpk": "cp_cpk",
    "RegressionSpecialist": "regression",
    "regression": "regression",
    "MannKendallSpecialist": "mann_kendall",
    "mann_kendall": "mann_kendall",
    "AnovaKruskalSpecialist": "anova_kruskal",
    "anova_kruskal": "anova_kruskal",
    "PivotSpecialist": "pivot",
    "pivot": "pivot",
    "CorrelationSpecialist": "correlation",
    "correlation": "correlation",
}

_OLLAMA_MODEL = "qwen2.5-coder:14b"
_VERSION = "IndustrIA v2.1"


class ReportAgent:
    """Agent 6 — PDF ReportLab + Plotly; LLM réservé au résumé exécutif."""

    def _canonical_agent(self, agent_name: str | None) -> str:
        """Normalize specialist agent names."""
        if not isinstance(agent_name, str):
            return ""
        return _AGENT_CANONICAL.get(agent_name, agent_name.strip().lower())

    def _find_result(self, validated_results: list[dict], canonical: str) -> dict | None:
        """Return the first validated result for a canonical agent name."""
        for result in validated_results:
            if not isinstance(result, dict):
                continue
            if self._canonical_agent(result.get("agent")) == canonical:
                return result
        return None

    def _generate_resume_executif(
        self,
        state: dict,
        rapport_oapc: dict,
        user_profile: str,
    ) -> str:
        """
        Generate Section 1 executive summary via LLM (14B) with Python fallback.

        Args:
            state: Shared pipeline state.
            rapport_oapc: OAPC report from Agent 5.
            user_profile: User profile key.

        Returns:
            str: Executive summary text.
        """
        priority = rapport_oapc.get("priority", "P4")
        goal = rapport_oapc.get("goal", "resume")
        target = state.get("target_column", "")
        observer = rapport_oapc.get("observer", "")
        analyser = rapport_oapc.get("analyser", "")
        prescrire = rapport_oapc.get("prescrire", "")

        system_prompt = (
            "Tu rédiges le résumé exécutif d'un rapport industriel IndustrIA.\n"
            "Tu ne fais AUCUN calcul. Tu n'inventes AUCUN chiffre.\n"
            "Tu t'appuies UNIQUEMENT sur le contexte OAPC fourni.\n"
            f"Profil lecteur : {user_profile}.\n"
            "Réponds en 3 à 5 phrases en français, sans markdown, sans titre."
        )
        user_prompt = (
            f"Priorité : {priority}\n"
            f"Objectif : {goal}\n"
            f"Cible : {target}\n"
            f"OBSERVER : {observer}\n"
            f"ANALYSER : {analyser}\n"
            f"PRESCRIRE : {prescrire}\n\n"
            "Rédige le résumé exécutif adapté au profil."
        )

        try:
            response = ollama.chat(
                model=_OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                options={
                    "temperature": 0.1,
                    "num_predict": 200,
                    "num_ctx": 4096,
                },
            )
            raw = ""
            if isinstance(response, dict):
                raw = str(response.get("message", {}).get("content", "") or "")
            else:
                message = getattr(response, "message", None)
                if message is not None:
                    raw = str(getattr(message, "content", "") or "")
            cleaned = raw.strip()
            if cleaned:
                return cleaned
        except Exception:
            logger.exception("report_agent resume executif LLM failed")

        return (
            f"Analyse {goal} terminée. Priorité {priority} détectée sur {target}. "
            f"Action : {prescrire}"
        )

    def _generate_graphique_principal(
        self,
        state: dict,
        rapport_oapc: dict,
    ) -> bytes | None:
        """
        Build the main Plotly time-series chart as PNG bytes.

        Args:
            state: Shared pipeline state.
            rapport_oapc: OAPC report (unused, reserved for titles).

        Returns:
            bytes | None: PNG image bytes or None when data is insufficient.
        """
        _ = rapport_oapc
        df = state.get("df_propre")
        if df is None or getattr(df, "empty", True):
            return None

        target = state.get("target_column", "")
        if not isinstance(target, str) or target not in df.columns:
            return None

        work = df.copy()
        series = pd.to_numeric(work[target], errors="coerce")
        if series.notna().sum() < 3:
            return None

        if "timestamp" in work.columns:
            x_values = pd.to_datetime(work["timestamp"], errors="coerce")
        else:
            x_values = pd.Series(range(len(work)), index=work.index)

        rolling_mean = series.rolling(window=10, min_periods=1).mean()
        rolling_std = series.rolling(window=10, min_periods=1).std().fillna(0.0)
        mean_line = rolling_mean
        ucl_2 = mean_line + 2 * rolling_std
        lcl_2 = mean_line - 2 * rolling_std
        ucl_3 = mean_line + 3 * rolling_std
        lcl_3 = mean_line - 3 * rolling_std

        figure = go.Figure()
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=lcl_3,
                mode="lines",
                line=dict(color="rgba(220,38,38,0.25)", width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=ucl_3,
                mode="lines",
                fill="tonexty",
                fillcolor="rgba(220,38,38,0.12)",
                line=dict(color="rgba(220,38,38,0.25)", width=0),
                name="Zone ±3σ",
            )
        )
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=lcl_2,
                mode="lines",
                line=dict(color="rgba(234,88,12,0.3)", width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=ucl_2,
                mode="lines",
                fill="tonexty",
                fillcolor="rgba(22,163,74,0.15)",
                line=dict(color="rgba(22,163,74,0.3)", width=0),
                name="Zone ±2σ",
            )
        )
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=series,
                mode="lines",
                name=target,
                line=dict(color="#1D4ED8", width=2),
            )
        )
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=rolling_mean,
                mode="lines",
                name="Moyenne mobile (10)",
                line=dict(color="#64748B", width=1.5, dash="dash"),
            )
        )

        df_anomalies = state.get("df_anomalies")
        if (
            df_anomalies is not None
            and not getattr(df_anomalies, "empty", True)
            and target in df_anomalies.columns
        ):
            anomaly_series = pd.to_numeric(df_anomalies[target], errors="coerce")
            if "timestamp" in df_anomalies.columns:
                anomaly_x = pd.to_datetime(df_anomalies["timestamp"], errors="coerce")
            else:
                anomaly_x = df_anomalies.index
            figure.add_trace(
                go.Scatter(
                    x=anomaly_x,
                    y=anomaly_series,
                    mode="markers",
                    name="Anomalies",
                    marker=dict(color="#DC2626", size=7, symbol="x"),
                )
            )

        figure.update_layout(
            title=f"Analyse {target}",
            xaxis_title="Temps",
            yaxis_title=target,
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=50, r=30, t=60, b=50),
            height=420,
            width=900,
        )

        try:
            return figure.to_image(format="png", scale=2)
        except Exception:
            logger.exception("Plotly PNG export failed (kaleido required?)")
            return None

    def _generate_causes_probables(
        self,
        validated_results: list[dict],
        rapport_oapc: dict,
    ) -> list[dict]:
        """
        Infer probable causes from validated specialist outputs (Python only).

        Args:
            validated_results: Judge-validated specialist results.
            rapport_oapc: OAPC report payload.

        Returns:
            list[dict]: Up to five cause entries sorted by probability.
        """
        _ = rapport_oapc
        causes: list[dict] = []

        zscore_result = self._find_result(validated_results, "zscore")
        if zscore_result and zscore_result.get("status") == "success":
            payload = zscore_result.get("result", {})
            if isinstance(payload, dict):
                total = float(payload.get("total_points", 0) or 0)
                process_count = float(payload.get("anomalie_process_count", 0) or 0)
                bruit_count = float(payload.get("bruit_capteur_count", 0) or 0)
                if total > 0 and process_count > 0:
                    causes.append({
                        "cause": "Anomalie process détectée",
                        "probabilite": round(min(process_count / total * 100, 90), 1),
                        "agent": "zscore",
                    })
                if total > 0 and bruit_count > 0:
                    causes.append({
                        "cause": "Bruit capteur",
                        "probabilite": round(min(bruit_count / total * 100, 60), 1),
                        "agent": "zscore",
                    })

        spc_result = self._find_result(validated_results, "spc")
        if spc_result and spc_result.get("status") == "success":
            payload = spc_result.get("result", {})
            if isinstance(payload, dict) and not bool(payload.get("sous_controle", True)):
                causes.append({
                    "cause": "Processus hors contrôle statistique",
                    "probabilite": 75.0,
                    "agent": "spc",
                })

        ewma_result = self._find_result(validated_results, "ewma_cusum")
        if ewma_result and ewma_result.get("status") == "success":
            payload = ewma_result.get("result", {})
            if isinstance(payload, dict) and bool(payload.get("derive_detectee", False)):
                causes.append({
                    "cause": "Dérive progressive du processus",
                    "probabilite": 70.0,
                    "agent": "ewma_cusum",
                })

        cp_result = self._find_result(validated_results, "cp_cpk")
        if cp_result and cp_result.get("status") == "success":
            payload = cp_result.get("result", {})
            if isinstance(payload, dict):
                cpk = float(payload.get("Cpk", 999))
                if cpk < 1.33:
                    causes.append({
                        "cause": f"Capabilité insuffisante (Cpk={cpk})",
                        "probabilite": 80.0,
                        "agent": "cp_cpk",
                    })

        regression_result = self._find_result(validated_results, "regression")
        if regression_result and regression_result.get("status") == "success":
            payload = regression_result.get("result", {})
            if isinstance(payload, dict):
                meilleure = payload.get("meilleure_variable")
                if isinstance(meilleure, dict):
                    variable = meilleure.get("variable", "")
                    r_squared = float(meilleure.get("r_squared", 0) or 0)
                    if variable and r_squared > 0:
                        causes.append({
                            "cause": f"Corrélation avec {variable}",
                            "probabilite": round(min(r_squared * 100, 95), 1),
                            "agent": "regression",
                        })

        causes.sort(key=lambda item: item["probabilite"], reverse=True)
        return causes[:5]

    def _flatten_result_metrics(self, payload: dict) -> list[tuple[str, str]]:
        """Flatten a specialist result dict into key/value rows for tables."""
        rows: list[tuple[str, str]] = []
        if not isinstance(payload, dict):
            return rows
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                rows.append((str(key), json.dumps(value, ensure_ascii=False)[:200]))
            else:
                rows.append((str(key), str(value)))
        return rows

    def _generate_annexe_technique(
        self,
        validated_results: list[dict],
        state: dict,
    ) -> list[dict]:
        """
        Build structured technical appendix rows for engineers.

        Args:
            validated_results: Judge-validated specialist results.
            state: Shared pipeline state.

        Returns:
            list[dict]: Appendix entries per agent.
        """
        _ = state
        annex: list[dict] = []
        for result in validated_results:
            if not isinstance(result, dict):
                continue
            if result.get("status") != "success":
                continue
            payload = result.get("result", {})
            if not isinstance(payload, dict):
                payload = {}
            annex.append({
                "agent": str(result.get("agent", "")),
                "methode": self._canonical_agent(result.get("agent")),
                "judge_valid": bool(result.get("judge_valid", True)),
                "judge_warnings": list(result.get("judge_warnings", []) or []),
                "metriques": self._flatten_result_metrics(payload),
                "execution_time_ms": result.get("execution_time_ms", 0),
            })
        return annex

    def _generate_tracabilite(
        self,
        state: dict,
        rapport_oapc: dict,
        resume_executif: str,
    ) -> dict:
        """
        Build EN9100 traceability metadata and SHA-256 hash.

        Args:
            state: Shared pipeline state.
            rapport_oapc: OAPC report.
            resume_executif: Section 1 text (hashed for integrity).

        Returns:
            dict: Traceability block.
        """
        validated_results = state.get("validated_results", [])
        if not isinstance(validated_results, list):
            validated_results = []
        judge_warnings = state.get("judge_warnings", [])
        if not isinstance(judge_warnings, list):
            judge_warnings = []

        timestamp = datetime.now().isoformat()
        question = state.get("question", "")
        target_column = state.get("target_column", "")
        priority = rapport_oapc.get("priority", "P4")
        user_profile = state.get("user_profile", "technicien")

        hash_payload = {
            "question": question,
            "timestamp": timestamp,
            "target": target_column,
            "priority": priority,
            "resume_len": len(resume_executif),
        }
        hash_data = json.dumps(hash_payload, sort_keys=True, ensure_ascii=False)
        sha256 = hashlib.sha256(hash_data.encode()).hexdigest()

        return {
            "version": _VERSION,
            "timestamp": timestamp,
            "agents_appeles": list(state.get("agents_called", [])),
            "target_column": target_column,
            "priority": priority,
            "user_profile": user_profile,
            "question": question,
            "n_specialistes": len(validated_results),
            "n_warnings": len(judge_warnings),
            "judge_warnings": judge_warnings,
            "sha256": sha256,
        }

    def _priority_color(self, priority: str):
        """Return ReportLab color for a priority level."""
        return COULEURS_PRIORITE.get(priority, COULEURS_PRIORITE["P4"])

    def _oapc_block(
        self,
        label: str,
        text: str,
        styles: Any,
        accent_color,
    ) -> Table:
        """Build a colored OAPC block table."""
        label_style = ParagraphStyle(
            f"OAPC_{label}",
            parent=styles["Heading4"],
            textColor=colors.white,
            fontSize=10,
        )
        body_style = ParagraphStyle(
            f"OAPC_{label}_body",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
        )
        table = Table(
            [
                [Paragraph(label, label_style)],
                [Paragraph(text or "—", body_style)],
            ],
            colWidths=[17 * cm],
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), accent_color),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, accent_color),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return table

    def _build_pdf(
        self,
        state: dict,
        rapport_oapc: dict,
        resume_executif: str,
        graphique_bytes: bytes | None,
        causes_probables: list[dict],
        annexe_technique: list[dict],
        tracabilite: dict,
        output_path: str,
    ) -> tuple[str, int]:
        """
        Assemble the full PDF report with ReportLab.

        Args:
            state: Shared pipeline state.
            rapport_oapc: OAPC report.
            resume_executif: Section 1 text.
            graphique_bytes: Optional Plotly PNG.
            causes_probables: Probable causes list.
            annexe_technique: Technical appendix rows.
            tracabilite: Traceability metadata.
            output_path: Destination PDF path.

        Returns:
            tuple[str, int]: Written PDF path and page count.
        """
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            title="Rapport IndustrIA",
            author=_VERSION,
        )
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name="IndustriaTitle",
            parent=styles["Title"],
            fontSize=22,
            alignment=TA_CENTER,
            spaceAfter=12,
        ))
        styles.add(ParagraphStyle(
            name="SectionHeader",
            parent=styles["Heading2"],
            fontSize=14,
            spaceBefore=14,
            spaceAfter=8,
            textColor=colors.HexColor("#1E3A5F"),
        ))
        styles.add(ParagraphStyle(
            name="BodyJustify",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            alignment=TA_LEFT,
        ))

        priority = rapport_oapc.get("priority", "P4")
        priority_color = self._priority_color(priority)
        user_profile = state.get("user_profile", "technicien")
        question = state.get("question", "")
        now_display = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        story: list[Any] = []

        story.append(Paragraph("IndustrIA", styles["IndustriaTitle"]))
        story.append(Paragraph("Rapport d'Analyse Industrielle", styles["Heading1"]))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(f"<b>Date :</b> {now_display}", styles["Normal"]))
        badge = Table(
            [[Paragraph(f"<b>PRIORITÉ {priority}</b>", ParagraphStyle(
                "badge",
                parent=styles["Normal"],
                textColor=colors.white,
                alignment=TA_CENTER,
            ))]],
            colWidths=[4 * cm],
        )
        badge.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), priority_color),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(badge)
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(f"<b>Question :</b> {question}", styles["BodyJustify"]))
        story.append(Paragraph(f"<b>Profil :</b> {user_profile}", styles["BodyJustify"]))
        story.append(PageBreak())

        story.append(Paragraph("1. Résumé exécutif", styles["SectionHeader"]))
        story.append(Paragraph(resume_executif, styles["BodyJustify"]))
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Verdict OAPC", styles["Heading3"]))
        oapc_colors = {
            "OBSERVER": colors.HexColor("#2563EB"),
            "ANALYSER": colors.HexColor("#7C3AED"),
            "PRESCRIRE": colors.HexColor("#EA580C"),
            "CERTIFIER": colors.HexColor("#16A34A"),
        }
        for label, key in (
            ("OBSERVER", "observer"),
            ("ANALYSER", "analyser"),
            ("PRESCRIRE", "prescrire"),
            ("CERTIFIER", "certifier"),
        ):
            story.append(self._oapc_block(
                label,
                str(rapport_oapc.get(key, "")),
                styles,
                oapc_colors[label],
            ))
            story.append(Spacer(1, 0.15 * cm))

        story.append(PageBreak())
        story.append(Paragraph("2. Graphique principal", styles["SectionHeader"]))
        if graphique_bytes:
            image_stream = io.BytesIO(graphique_bytes)
            story.append(Image(image_stream, width=17 * cm, height=9 * cm))
            story.append(Spacer(1, 0.2 * cm))
            story.append(Paragraph(
                "Légende : zone verte ±2σ, zone rouge ±3σ, "
                "trait bleu = série capteur, croix rouges = anomalies.",
                styles["Normal"],
            ))
        else:
            story.append(Paragraph(
                "Données insuffisantes pour générer le graphique.",
                styles["BodyJustify"],
            ))

        story.append(PageBreak())
        story.append(Paragraph("3. Causes probables", styles["SectionHeader"]))
        if causes_probables:
            table_data = [["Cause", "Probabilité (%)", "Agent source"]]
            for item in causes_probables:
                table_data.append([
                    item.get("cause", ""),
                    f"{item.get('probabilite', 0):.1f}",
                    item.get("agent", ""),
                ])
            cause_table = Table(table_data, colWidths=[9 * cm, 3 * cm, 4 * cm])
            cause_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#F1F5F9")]),
            ]))
            story.append(cause_table)
        else:
            story.append(Paragraph("Aucune cause identifiée automatiquement.", styles["Normal"]))

        story.append(PageBreak())
        story.append(Paragraph("4. Recommandation", styles["SectionHeader"]))
        story.append(Paragraph(
            f"<b>{rapport_oapc.get('prescrire', '')}</b>",
            ParagraphStyle(
                "PrescrireBig",
                parent=styles["BodyJustify"],
                fontSize=12,
                leading=16,
            ),
        ))
        story.append(Spacer(1, 0.3 * cm))
        delai = DELAIS_INTERVENTION.get(priority, DELAIS_INTERVENTION["P4"])
        responsable = RESPONSABLE_PROFIL.get(user_profile, "Responsable atelier")
        story.append(Paragraph(f"<b>Délai d'intervention :</b> {delai}", styles["BodyJustify"]))
        story.append(Paragraph(f"<b>Responsable :</b> {responsable}", styles["BodyJustify"]))

        if user_profile in ("ingenieur", "technicien"):
            story.append(PageBreak())
            story.append(Paragraph("5. Annexe technique", styles["SectionHeader"]))
            for entry in annexe_technique:
                story.append(Paragraph(
                    f"<b>{entry.get('agent', '')}</b> "
                    f"({'valide' if entry.get('judge_valid') else 'invalide'})",
                    styles["Heading4"],
                ))
                rows = [["Métrique", "Valeur"]] + entry.get("metriques", [])[:12]
                if len(rows) > 1:
                    tech_table = Table(rows, colWidths=[6 * cm, 10 * cm])
                    tech_table.setStyle(TableStyle([
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                    ]))
                    story.append(tech_table)
                warnings = entry.get("judge_warnings", [])
                if warnings:
                    story.append(Paragraph(
                        f"Warnings : {'; '.join(warnings)}",
                        styles["Normal"],
                    ))
                story.append(Spacer(1, 0.25 * cm))
            judge_warnings = tracabilite.get("judge_warnings", [])
            if judge_warnings:
                story.append(Paragraph("<b>Warnings Judge globaux</b>", styles["Heading4"]))
                for warning in judge_warnings:
                    story.append(Paragraph(f"• {warning}", styles["Normal"]))

        story.append(PageBreak())
        story.append(Paragraph("6. Traçabilité EN9100", styles["SectionHeader"]))
        trace_rows = [
            ["Champ", "Valeur"],
            ["Version", tracabilite.get("version", "")],
            ["Horodatage", tracabilite.get("timestamp", "")],
            ["Question", tracabilite.get("question", "")],
            ["Cible", tracabilite.get("target_column", "")],
            ["Priorité", tracabilite.get("priority", "")],
            ["Profil", tracabilite.get("user_profile", "")],
            ["Spécialistes", str(tracabilite.get("n_specialistes", 0))],
            ["Warnings", str(tracabilite.get("n_warnings", 0))],
            ["Agents", ", ".join(tracabilite.get("agents_appeles", [])[:8])],
            ["SHA-256", tracabilite.get("sha256", "")],
        ]
        trace_table = Table(trace_rows, colWidths=[5 * cm, 11 * cm])
        trace_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ]))
        story.append(trace_table)
        story.append(Spacer(1, 0.5 * cm))
        signature_block = (
            "┌─────────────────────────────────┐\n"
            "│ Opérateur terrain : __________ │\n"
            "│ Date : ________________________│\n"
            "│                                 │\n"
            "│ Responsable qualité : _________ │\n"
            "│ Date : ________________________│\n"
            "└─────────────────────────────────┘"
        )
        story.append(Paragraph(
            f"<pre>{signature_block}</pre>",
            ParagraphStyle("Sign", parent=styles["Normal"], fontName="Courier", fontSize=8),
        ))

        doc.build(story)
        return output_path, int(getattr(doc, "page", 1) or 1)

    def run(self, state: AgentState | dict) -> dict:
        """
        Generate the full PDF report and update ``state['pdf_path']``.

        Args:
            state: Shared LangGraph state after Agent 5.

        Returns:
            dict: Structured report agent result.
        """
        start_time = time.time()

        if isinstance(state, dict):
            state.setdefault("errors", [])
            state.setdefault("agents_called", [])

        try:
            rapport_oapc = state.get("rapport_oapc", {}) if isinstance(state, dict) else {}
            if not isinstance(rapport_oapc, dict) or not rapport_oapc:
                return {
                    "agent": "report_agent",
                    "status": "error",
                    "pdf_path": "",
                    "pages": 0,
                    "tracabilite": {},
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                    "error": "rapport_oapc absent — exécuter Agent 5 avant le rapport",
                }

            validated_results = state.get("validated_results", []) if isinstance(state, dict) else []
            if not isinstance(validated_results, list):
                validated_results = []

            user_profile = state.get("user_profile", "technicien") if isinstance(state, dict) else "technicien"

            resume = self._generate_resume_executif(state, rapport_oapc, user_profile)
            graphique = self._generate_graphique_principal(state, rapport_oapc)
            causes = self._generate_causes_probables(validated_results, rapport_oapc)
            annexe = self._generate_annexe_technique(validated_results, state)
            tracabilite = self._generate_tracabilite(state, rapport_oapc, resume)

            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = _ROOT / "outputs"
            output_dir.mkdir(exist_ok=True)
            output_path = str(output_dir / f"rapport_industria_{timestamp_str}.pdf")

            pdf_path, pages = self._build_pdf(
                state,
                rapport_oapc,
                resume,
                graphique,
                causes,
                annexe,
                tracabilite,
                output_path,
            )

            if isinstance(state, dict):
                state["pdf_path"] = pdf_path
                if "report_agent" not in state["agents_called"]:
                    state["agents_called"].append("report_agent")

            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "report_agent",
                "status": "success",
                "pdf_path": pdf_path,
                "pages": pages,
                "tracabilite": tracabilite,
                "execution_time_ms": execution_time_ms,
                "error": None,
            }
        except Exception as exc:
            logger.exception("report_agent failed")
            if isinstance(state, dict):
                state["errors"].append(str(exc))
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": "report_agent",
                "status": "error",
                "pdf_path": "",
                "pages": 0,
                "tracabilite": {},
                "execution_time_ms": execution_time_ms,
                "error": str(exc),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    np.random.seed(42)
    n = 100

    df_test = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="1min"),
        "inducteur_1": np.concatenate([
            np.random.normal(100, 5, 80),
            np.random.normal(130, 5, 20),
        ]),
    })

    df_anomalies = df_test[df_test["inducteur_1"] > 115].copy()

    state_test = {
        "question": "Y a-t-il des anomalies sur les capteurs ?",
        "target_column": "inducteur_1",
        "user_profile": "technicien",
        "agents_called": [
            "agent_1",
            "agent_2",
            "agent_3",
            "ZScoreSpecialist",
            "SpcSpecialist",
            "statistician_judge",
            "agent_5",
        ],
        "df_propre": df_test,
        "df_anomalies": df_anomalies,
        "rapport_oapc": {
            "observer": "13 anomalies détectées sur inducteur_1.",
            "analyser": "max_zscore de 4.7 indique une anomalie significative.",
            "prescrire": (
                "Intervention dans les 30 minutes. "
                "Vérifier le capteur concerné."
            ),
            "certifier": "IndustrIA v2.1 | inducteur_1 | P2",
            "priority": "P2",
            "goal": "detection_anomalies",
            "user_profile": "technicien",
        },
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
            },
            {
                "agent": "SpcSpecialist",
                "status": "success",
                "judge_valid": True,
                "result": {
                    "sous_controle": False,
                    "hors_limites_x": [8, 12, 15],
                    "UCL_x": 115.2,
                    "LCL_x": 84.8,
                },
            },
        ],
        "judge_warnings": [
            "Résultats contradictoires entre agents",
        ],
    }

    agent = ReportAgent()
    result = agent.run(state_test)

    print(f"Status   : {result['status']}")
    print(f"PDF      : {result['pdf_path']}")
    print(f"Pages    : {result['pages']}")
    if result.get("tracabilite"):
        print(f"Hash     : {result['tracabilite']['sha256'][:16]}...")
    print(f"Temps    : {result['execution_time_ms']}ms")

    if result["status"] == "success":
        print(f"\nPDF généré → {result['pdf_path']}")
        print("Ouvre le fichier pour vérifier.")
