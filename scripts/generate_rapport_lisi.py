#!/usr/bin/env python3
"""Génère un rapport PDF LISI (S1→S7) — sortie à la racine du dépôt."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from systems.s1.pipeline import S1Pipeline
from systems.s2.pipeline import S2Pipeline
from systems.s3.pipeline import S3Pipeline
from systems.s4.pipeline import S4Pipeline
from systems.s5.pipeline import S5Pipeline
from systems.s6.pipeline import S6Pipeline
from systems.s7.pipeline import S7Pipeline

YAML = REPO / "configs/lisi_aerospace/client_config.yaml"
QUESTION = "La matrice a-t-elle un impact sur la forme intrados de M2L1A1C ?"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, help="Chemin PDF de sortie")
    parser.add_argument("--profile", default="technicien")
    args = parser.parse_args()

    yaml = str(YAML)
    print("S1…", flush=True)
    s1 = S1Pipeline(yaml).run(QUESTION)
    intent = s1["intent"]
    if intent.get("clarification_needed"):
        print("Intent incomplet:", intent.get("clarification_message"))
        return 1

    print("S2…", flush=True)
    s2 = S2Pipeline(yaml).run(intent)
    if s2.get("error"):
        print("S2 error:", s2["error"])
        return 1

    print("S3…", flush=True)
    s3 = S3Pipeline(yaml).run(intent, s2["df_propre"])
    if s3.get("error"):
        print("S3 error:", s3["error"])
        return 1

    print("S4…", flush=True)
    s4 = S4Pipeline(yaml).run(intent, s2["df_propre"], s3)
    if s4.get("error"):
        print("S4 error:", s4["error"])
        return 1

    print("S5…", flush=True)
    s5 = S5Pipeline(yaml).run(intent, s3, s4, profile=args.profile)
    if s5.get("error"):
        print("S5 error:", s5["error"])
        return 1

    print("S6…", flush=True)
    s6 = S6Pipeline(yaml).run(intent, s3, s5, profile=args.profile)
    if s6.get("error"):
        print("S6 error:", s6["error"])
        return 1

    print("S7…", flush=True)
    s7 = S7Pipeline(yaml).run(
        QUESTION,
        intent,
        s3,
        s4,
        s5,
        s6,
        profile=args.profile,
    )
    if s7.get("error"):
        print("S7 error:", s7["error"])
        return 1

    out_path = args.output if args.output.is_absolute() else REPO / args.output
    out_path.write_bytes(s7["pdf_bytes"])
    print(f"OK {out_path} ({len(s7['pdf_bytes'])} bytes)")
    print(f"SHA-256 {s7['sha256']}")
    if s7.get("warnings"):
        print(f"Warnings ({len(s7['warnings'])}):")
        for w in s7["warnings"][:8]:
            print(" -", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
