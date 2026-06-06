#!/usr/bin/env python3
"""
Génère localement les 4 PDF F2 pastilles validés (client démo aéronautique).

Pipeline S1 → S7 inchangé ; active ``f2_compact_enabled`` uniquement en mémoire.
Les PDF sont écrits dans ``outputs/`` (gitignored) — ne jamais ``git add``.
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_CONFIG = REPO / "configs/lisi_aerospace/client_config_traceability.yaml"
DEFAULT_OUTPUT_DIR = REPO / "outputs"
EXPORT_CSV = REPO / "data/lisi_capteurs_export_complet_tracabilite.csv"

from systems.s1.pipeline import S1Pipeline  # noqa: E402
from systems.s2.pipeline import S2Pipeline  # noqa: E402
from systems.s3.pipeline import S3Pipeline  # noqa: E402
from systems.s4.pipeline import S4Pipeline  # noqa: E402
from systems.s5.pipeline import S5Pipeline  # noqa: E402
from systems.s6.pipeline import S6Pipeline  # noqa: E402
from systems.s7 import prep  # noqa: E402
from systems.s7.pipeline import S7Pipeline  # noqa: E402


@dataclass(frozen=True)
class DemoCase:
    case_id: str
    label: str
    question: str
    output_name: str


DEMO_CASES: tuple[DemoCase, ...] = (
    DemoCase(
        "passage-ext",
        "Passage pastille extérieure (F2 standard)",
        "Comparer CR1 selon le numéro de passage de la pastille extérieure sur RD4L1A1C au filage",
        "f2_pastilles_passage_ext_RD4L1A1C.pdf",
    ),
    DemoCase(
        "passage-int",
        "Passage pastille intérieure (F2 standard)",
        "Comparer CR1 selon le numéro de passage de la pastille intérieure sur RD4L1A1C au filage",
        "f2_pastilles_passage_int_RD4L1A1C.pdf",
    ),
    DemoCase(
        "retaille-ext",
        "Retaille pastille extérieure (F2 high-cardinality)",
        "Comparer CR1 selon le niveau de retaille de la pastille extérieure sur RD4L1A1C au filage",
        "f2_pastilles_retaille_ext_RD4L1A1C.pdf",
    ),
    DemoCase(
        "retaille-int",
        "Retaille pastille intérieure (F2 high-cardinality)",
        "Comparer CR1 selon le niveau de retaille de la pastille intérieure sur RD4L1A1C au filage",
        "f2_pastilles_retaille_int_RD4L1A1C.pdf",
    ),
)

_CASE_BY_ID = {c.case_id: c for c in DEMO_CASES}


def _enable_f2_compact_in_memory() -> Callable[[], None]:
    """Active f2_compact_enabled via monkeypatch prep.rapport_pdf_config (mémoire uniquement)."""
    original = prep.rapport_pdf_config

    def _wrapped(context):
        cfg = original(context)
        merged = dict(cfg)
        merged["f2_compact_enabled"] = True
        return merged

    prep.rapport_pdf_config = _wrapped

    def _restore() -> None:
        prep.rapport_pdf_config = original

    return _restore


def _pdf_page_count(pdf_bytes: bytes) -> int | None:
    try:
        from pypdf import PdfReader

        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:
        return None


def _priority_group(s3_output: dict) -> str:
    blocks = s3_output.get("group_descriptive") or []
    if blocks and blocks[0].get("worst_group") is not None:
        return str(blocks[0]["worst_group"])
    return "—"


def _run_case(
    case: DemoCase,
    *,
    yaml_path: str,
    output_dir: Path,
    profile: str,
    dry_run: bool,
) -> int:
    out_path = output_dir / case.output_name
    print(f"\n=== {case.label} ({case.case_id}) ===")
    print(f"Question : {case.question}")
    print(f"PDF      : {out_path}")

    if dry_run:
        return 0

    restore_cfg = _enable_f2_compact_in_memory()
    try:
        print("S1…", flush=True)
        s1 = S1Pipeline(yaml_path).run(case.question)
        intent = s1["intent"]
        if intent.get("clarification_needed"):
            print("Intent incomplet — clarification requise.")
            return 1

        print("S2…", flush=True)
        s2 = S2Pipeline(yaml_path).run(intent)
        if s2.get("error"):
            print("S2 error:", s2["error"])
            return 1

        print("S3…", flush=True)
        s3 = S3Pipeline(yaml_path).run(intent, s2["df_propre"])
        if s3.get("error"):
            print("S3 error:", s3["error"])
            return 1

        print("S4…", flush=True)
        s4 = S4Pipeline(yaml_path).run(intent, s2["df_propre"], s3)
        if s4.get("error"):
            print("S4 error:", s4["error"])
            return 1

        print("S5…", flush=True)
        s5 = S5Pipeline(yaml_path).run(intent, s3, s4, profile=profile)
        if s5.get("error"):
            print("S5 error:", s5["error"])
            return 1

        print("S6…", flush=True)
        s6 = S6Pipeline(yaml_path).run(intent, s3, s5, profile=profile)
        if s6.get("error"):
            print("S6 error:", s6["error"])
            return 1

        print("S7…", flush=True)
        s7 = S7Pipeline(yaml_path).run(
            case.question,
            intent,
            s3,
            s4,
            s5,
            s6,
            profile=profile,
            df_propre=s2["df_propre"],
        )
        if s7.get("error"):
            print("S7 error:", s7["error"])
            return 1

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(s7["pdf_bytes"])
        pages = _pdf_page_count(s7["pdf_bytes"])
        meta = dict(s7.get("metadata") or {})
        sel_meta = dict(meta.get("f2_compact_selection") or {})
        hc_active = bool(sel_meta.get("high_cardinality_active"))
        verdict = str(meta.get("verdict") or meta.get("verdict_key") or "—")
        priority = _priority_group(s3)

        print(f"OK       : {out_path}")
        print(f"Taille   : {len(s7['pdf_bytes'])} bytes")
        if pages is not None:
            print(f"Pages    : {pages}")
        print(f"SHA-256  : {s7.get('sha256', '')}")
        print(f"Verdict  : {verdict}")
        print(f"Priorité : {priority}")
        print(f"High-cardinality : {'oui' if hc_active else 'non'}")
        if s7.get("warnings"):
            print(f"Warnings ({len(s7['warnings'])}):")
            for w in s7["warnings"][:5]:
                print(" -", w)
        return 0
    finally:
        restore_cfg()


def _resolve_cases(args: argparse.Namespace) -> list[DemoCase]:
    if args.all:
        return list(DEMO_CASES)
    if args.case:
        unknown = [c for c in args.case if c not in _CASE_BY_ID]
        if unknown:
            valid = ", ".join(_CASE_BY_ID)
            raise SystemExit(f"Cas inconnu(s) : {', '.join(unknown)}. Valides : {valid}")
        return [_CASE_BY_ID[c] for c in args.case]
    raise SystemExit("Précisez --all ou --case <id> (ex. --case passage-ext).")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Génère les PDF F2 pastilles validés (client démo aéronautique). "
            "Sortie locale dans outputs/ — ne pas versionner."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Génère les 4 PDF de la campagne",
    )
    parser.add_argument(
        "--case",
        action="append",
        metavar="ID",
        help="Cas ciblé : passage-ext, passage-int, retaille-ext, retaille-int",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Config YAML (défaut : {DEFAULT_CONFIG.relative_to(REPO)})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Répertoire de sortie PDF (défaut : outputs/)",
    )
    parser.add_argument(
        "--profile",
        default="technicien",
        help="Profil rapport S5/S6/S7 (défaut : technicien)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche questions et chemins sans générer de PDF",
    )
    args = parser.parse_args()

    cases = _resolve_cases(args)
    config_path = args.config if args.config.is_absolute() else REPO / args.config
    if not config_path.is_file():
        print(f"Config introuvable : {config_path}")
        return 1

    output_dir = args.output_dir if args.output_dir.is_absolute() else REPO / args.output_dir

    if not args.dry_run and not EXPORT_CSV.is_file():
        print(
            f"Export traçabilité absent ({EXPORT_CSV}). "
            "Placez le CSV local (gitignored) ou utilisez --dry-run."
        )
        return 1

    yaml_path = str(config_path)
    print(f"Config   : {config_path.relative_to(REPO)}")
    print(f"Sortie   : {output_dir.relative_to(REPO)}/")
    if args.dry_run:
        print("Mode     : dry-run (aucun PDF généré)")

    rc = 0
    for case in cases:
        if _run_case(
            case,
            yaml_path=yaml_path,
            output_dir=output_dir,
            profile=args.profile,
            dry_run=args.dry_run,
        ):
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
