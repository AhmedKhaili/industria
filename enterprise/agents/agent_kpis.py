"""
Agent KPIs — OEE/TRS, MTBF, MTTR, First Pass Yield, Scrap Rate.
Calcul Python pur depuis TimescaleDB. Zéro LLM.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.config import FINANCIAL_PARAMS, get_machine
from enterprise.report.charts import build_gauge
from enterprise.report.formatters import format_number, format_percentage

logger = logging.getLogger(__name__)


class AgentKPIs:
    """Calcule les KPIs production/maintenance et exporte des jauges PNG."""

    def run(
        self,
        db_conn: Any,
        machine_id: str,
        time_window: str = "7 days",
    ) -> dict:
        """
        Calcule OEE, MTBF, MTTR, FPY, scrap rate et jauges Plotly.

        Args:
            db_conn: Connexion psycopg2 TimescaleDB (postgres_readonly).
            machine_id: Identifiant machine (clé MACHINE_CONFIG).
            time_window: Fenêtre SQL INTERVAL, ex. ``'7 days'``.

        Returns:
            dict: Métriques, PNG jauges, config machine, ``error`` éventuel.
        """
        machine_config = get_machine(machine_id)
        try:
            raw = self._query_kpis(db_conn, machine_id, time_window)
            if raw.get("query_error"):
                return self._result_from_raw(
                    raw,
                    machine_config,
                    error=raw["query_error"],
                )
            return self._result_from_raw(raw, machine_config, error=None)
        except Exception as exc:
            logger.exception("AgentKPIs.run failed")
            return self._empty_result(machine_config, str(exc))

    def _empty_result(self, machine_config: dict, error: str | None) -> dict:
        """Retourne un dict complet avec métriques nulles et jauges placeholder."""
        return self._result_from_raw(
            {
                "disponibilite": None,
                "performance": None,
                "qualite": None,
                "oee": None,
                "nb_pannes": None,
                "mtbf_h": None,
                "mttr_h": None,
                "nb_pieces_total": None,
                "nb_pieces_conformes": None,
                "first_pass_yield": None,
                "scrap_rate": None,
            },
            machine_config,
            error=error,
        )

    def _result_from_raw(
        self,
        raw: dict,
        machine_config: dict,
        error: str | None,
    ) -> dict:
        disponibilite = raw.get("disponibilite")
        performance = raw.get("performance")
        qualite = raw.get("qualite")
        oee = raw.get("oee")
        if oee is None and all(
            v is not None for v in (disponibilite, performance, qualite)
        ):
            oee = float(disponibilite) * float(performance) * float(qualite)

        mtbf_h = raw.get("mtbf_h")
        first_pass_yield = raw.get("first_pass_yield")
        capacite = float(machine_config.get("capacite_nominale") or 100)
        mtbf_target_h = float(machine_config.get("mtbf_cible_h", 2000))

        oee_val = float(oee) if oee is not None else 0.0
        mtbf_val = float(mtbf_h) if mtbf_h is not None else 0.0
        fpy_val = float(first_pass_yield) if first_pass_yield is not None else 0.0

        gauge_oee = build_gauge(
            oee_val,
            title=f"OEE — {machine_config.get('nom', machine_id)}",
            min_val=0,
            max_val=1,
            seuils={"P3": 0.6, "P2": 0.4, "P1": 0.2},
        )
        gauge_mtbf = build_gauge(
            min(mtbf_val, mtbf_target_h),
            title="MTBF (heures)",
            min_val=0,
            max_val=mtbf_target_h,
            seuils={
                "P3": mtbf_target_h * 0.5,
                "P2": mtbf_target_h * 0.25,
                "P1": mtbf_target_h * 0.1,
            },
        )
        gauge_fpy = build_gauge(
            fpy_val,
            title="First Pass Yield",
            min_val=0,
            max_val=1,
            seuils={"P3": 0.95, "P2": 0.90, "P1": 0.80},
        )

        return {
            "oee": oee,
            "trs": oee,
            "mtbf_h": mtbf_h,
            "mttr_h": raw.get("mttr_h"),
            "first_pass_yield": first_pass_yield,
            "scrap_rate": raw.get("scrap_rate"),
            "disponibilite": disponibilite,
            "performance": performance,
            "qualite": qualite,
            "nb_pannes": raw.get("nb_pannes"),
            "nb_pieces_total": raw.get("nb_pieces_total"),
            "nb_pieces_conformes": raw.get("nb_pieces_conformes"),
            "gauge_oee_png": gauge_oee,
            "gauge_mtbf_png": gauge_mtbf,
            "gauge_fpyield_png": gauge_fpy,
            "machine_config": machine_config,
            "error": error,
        }

    def _table_exists(self, db_conn: Any, table_name: str) -> bool:
        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = %s
                    )
                    """,
                    (table_name,),
                )
                row = cur.fetchone()
                return bool(row[0]) if row else False
        except Exception:
            return False

    def _query_kpis(
        self,
        db_conn: Any,
        machine_id: str,
        window: str,
    ) -> dict:
        """
        Requêtes TimescaleDB sur ``production_logs`` et ``maintenance_logs``.

        Colonnes attendues (production_logs) :
            timestamp, machine_id, pieces_produites, pieces_conformes,
            pieces_rejetees, temps_production_min, temps_arret_min, temps_planifie_min

        Colonnes attendues (maintenance_logs) :
            timestamp, machine_id, type_event, duree_reparation_min
        """
        out: dict[str, Any] = {
            "disponibilite": None,
            "performance": None,
            "qualite": None,
            "oee": None,
            "nb_pannes": None,
            "mtbf_h": None,
            "mttr_h": None,
            "nb_pieces_total": None,
            "nb_pieces_conformes": None,
            "first_pass_yield": None,
            "scrap_rate": None,
            "query_error": None,
        }

        if db_conn is None:
            out["query_error"] = "Connexion base de données absente"
            return out

        machine_config = get_machine(machine_id)
        capacite_h = float(machine_config.get("capacite_nominale") or 100)
        errors: list[str] = []

        if self._table_exists(db_conn, "production_logs"):
            try:
                prod = self._query_production(db_conn, machine_id, window)
                out.update(prod)
            except Exception as exc:
                logger.warning("production_logs query failed: %s", exc)
                errors.append(f"production_logs: {exc}")
        else:
            errors.append("Table production_logs absente")

        if self._table_exists(db_conn, "maintenance_logs"):
            try:
                maint = self._query_maintenance(db_conn, machine_id, window)
                out.update(maint)
            except Exception as exc:
                logger.warning("maintenance_logs query failed: %s", exc)
                errors.append(f"maintenance_logs: {exc}")
        else:
            errors.append("Table maintenance_logs absente")

        if out.get("disponibilite") is not None and out.get("performance") is None:
            total_h = out.get("temps_planifie_h") or out.get("temps_prod_h")
            pieces = out.get("nb_pieces_total") or 0
            if total_h and float(total_h) > 0 and capacite_h > 0:
                out["performance"] = min(
                    1.0,
                    float(pieces) / (float(total_h) * capacite_h),
                )

        if (
            out.get("disponibilite") is not None
            and out.get("performance") is not None
            and out.get("qualite") is not None
        ):
            out["oee"] = (
                float(out["disponibilite"])
                * float(out["performance"])
                * float(out["qualite"])
            )

        if errors and all(
            out.get(k) is None
            for k in (
                "oee",
                "mtbf_h",
                "first_pass_yield",
                "nb_pieces_total",
            )
        ):
            out["query_error"] = "; ".join(errors)

        return out

    def _query_production(
        self,
        db_conn: Any,
        machine_id: str,
        window: str,
    ) -> dict:
        interval = self._safe_interval(window)
        sql = f"""
            SELECT
                COALESCE(SUM(pieces_produites), 0)::bigint AS total,
                COALESCE(SUM(pieces_conformes), 0)::bigint AS conformes,
                COALESCE(SUM(pieces_rejetees), 0)::bigint AS rejetees,
                COALESCE(SUM(temps_production_min), 0) / 60.0 AS temps_prod_h,
                COALESCE(SUM(temps_arret_min), 0) / 60.0 AS temps_arret_h,
                COALESCE(SUM(temps_planifie_min), 0) / 60.0 AS temps_planifie_h
            FROM production_logs
            WHERE timestamp >= NOW() - INTERVAL '{interval}'
              AND (%s = 'default' OR machine_id = %s)
        """
        with db_conn.cursor() as cur:
            cur.execute(sql, (machine_id, machine_id))
            row = cur.fetchone()

        if not row:
            return {}

        total = int(row[0] or 0)
        conformes = int(row[1] or 0)
        rejetees = int(row[2] or 0)
        temps_prod_h = float(row[3] or 0)
        temps_arret_h = float(row[4] or 0)
        temps_planifie_h = float(row[5] or 0)

        if total == 0 and conformes == 0 and rejetees == 0:
            total = conformes + rejetees

        qualite = (conformes / total) if total > 0 else None
        scrap_rate = (rejetees / total) if total > 0 else None
        fpy = qualite

        planifie = temps_planifie_h if temps_planifie_h > 0 else (temps_prod_h + temps_arret_h)
        disponibilite = None
        if planifie > 0:
            disponibilite = max(0.0, min(1.0, (planifie - temps_arret_h) / planifie))

        return {
            "nb_pieces_total": total,
            "nb_pieces_conformes": conformes,
            "first_pass_yield": fpy,
            "scrap_rate": scrap_rate,
            "qualite": qualite,
            "disponibilite": disponibilite,
            "temps_prod_h": temps_prod_h,
            "temps_planifie_h": planifie,
        }

    def _query_maintenance(
        self,
        db_conn: Any,
        machine_id: str,
        window: str,
    ) -> dict:
        interval = self._safe_interval(window)
        sql_pannes = f"""
            SELECT COUNT(*)::int
            FROM maintenance_logs
            WHERE timestamp >= NOW() - INTERVAL '{interval}'
              AND (%s = 'default' OR machine_id = %s)
              AND LOWER(COALESCE(type_event, '')) IN (
                  'panne', 'failure', 'breakdown', 'arret'
              )
        """
        sql_mttr = f"""
            SELECT COALESCE(SUM(duree_reparation_min), 0) / 60.0,
                   COUNT(*) FILTER (WHERE duree_reparation_min > 0)::int
            FROM maintenance_logs
            WHERE timestamp >= NOW() - INTERVAL '{interval}'
              AND (%s = 'default' OR machine_id = %s)
        """
        sql_window_h = f"""
            SELECT EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) / 3600.0
            FROM maintenance_logs
            WHERE timestamp >= NOW() - INTERVAL '{interval}'
              AND (%s = 'default' OR machine_id = %s)
        """

        with db_conn.cursor() as cur:
            cur.execute(sql_pannes, (machine_id, machine_id))
            nb_pannes = int(cur.fetchone()[0] or 0)

            cur.execute(sql_mttr, (machine_id, machine_id))
            mttr_row = cur.fetchone()
            somme_rep_h = float(mttr_row[0] or 0) if mttr_row else 0.0
            nb_interventions = int(mttr_row[1] or 0) if mttr_row else 0

            cur.execute(sql_window_h, (machine_id, machine_id))
            span_row = cur.fetchone()
            temps_total_h = float(span_row[0] or 0) if span_row and span_row[0] else None

        if temps_total_h is None or temps_total_h <= 0:
            parts = window.strip().split()
            if len(parts) == 2 and parts[1] in ("day", "days"):
                temps_total_h = float(parts[0]) * 24.0
            elif len(parts) == 2 and parts[1] in ("hour", "hours"):
                temps_total_h = float(parts[0])
            else:
                temps_total_h = 24.0 * 7.0

        mtbf_h = (temps_total_h / nb_pannes) if nb_pannes > 0 else None
        mttr_h = (somme_rep_h / nb_interventions) if nb_interventions > 0 else None

        return {
            "nb_pannes": nb_pannes,
            "mtbf_h": mtbf_h,
            "mttr_h": mttr_h,
        }

    @staticmethod
    def _safe_interval(window: str) -> str:
        """Valide une fenêtre temporelle simple (évite injection SQL)."""
        allowed = {
            "1 day",
            "7 days",
            "14 days",
            "30 days",
            "24 hours",
            "168 hours",
        }
        w = (window or "7 days").strip().lower()
        if w in allowed:
            return w
        parts = w.split()
        if len(parts) == 2 and parts[0].isdigit():
            unit = parts[1].rstrip("s")
            if unit in ("day", "hour"):
                return f"{parts[0]} {unit}s" if int(parts[0]) != 1 else f"1 {unit}"
        return "7 days"
