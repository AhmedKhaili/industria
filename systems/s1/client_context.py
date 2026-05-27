"""
Charge et expose le YAML S0 (client_config) pour S1.
Zéro LLM — seul point d'entrée du YAML (règle PHILOSOPHY §26).
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from systems.s1.parsing import piece_pattern_from_modeles

_REQUIRED_SECTIONS = (
    "client",
    "dataset",
    "entites",
    "pieces",
)


@dataclass
class ClientContext:
    raw: dict
    colonnes: dict
    operations_actives: list
    modeles_actifs: list
    entites_facteurs: dict
    entites_variables: dict
    entites_intentions: dict
    pieces: dict
    regles_nettoyage: dict
    temps: dict
    profils: dict
    recommandations: dict
    rapport_pdf: dict
    financier: dict
    machine_sens: dict
    s1_piece_patterns: list
    s1_operations_synonymes: dict

    @classmethod
    def load(cls, yaml_path: str) -> "ClientContext":
        path = Path(yaml_path)
        if not path.is_file():
            raise FileNotFoundError(f"Configuration client introuvable : {yaml_path}")

        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not isinstance(raw, dict):
            raise ValueError(f"YAML invalide (racine non-dict) : {yaml_path}")

        missing = [s for s in _REQUIRED_SECTIONS if s not in raw]
        if missing:
            raise ValueError(
                f"Sections obligatoires manquantes dans {yaml_path} : {', '.join(missing)}"
            )

        dataset = raw["dataset"]
        entites = raw["entites"]
        operations_actives = list(dataset.get("operations_actives", []))
        modeles_actifs = list(dataset.get("modeles_actifs", []))
        s1_cfg = dict(dataset.get("s1_parsing", {}))
        piece_pattern_strs = list(s1_cfg.get("piece_patterns", []))
        if not piece_pattern_strs:
            piece_pattern_strs = [piece_pattern_from_modeles(modeles_actifs)]
        s1_piece_patterns = [re.compile(p, re.IGNORECASE) for p in piece_pattern_strs]
        s1_operations_synonymes = dict(s1_cfg.get("operations_synonymes", {}))
        for op in operations_actives:
            s1_operations_synonymes.setdefault(op, [op.lower()])

        return cls(
            raw=raw,
            colonnes=dataset.get("colonnes", {}),
            operations_actives=operations_actives,
            modeles_actifs=modeles_actifs,
            entites_facteurs=dict(entites.get("facteurs_analyse", {})),
            entites_variables=dict(entites.get("groupes_variables", {})),
            entites_intentions=dict(entites.get("intentions", {})),
            pieces=dict(raw["pieces"]),
            regles_nettoyage=dict(dataset.get("regles_nettoyage", {})),
            temps=dict(raw.get("temps", {})),
            profils=dict(raw.get("profils", {})),
            recommandations=dict(raw.get("recommandations", {})),
            rapport_pdf=dict(raw.get("rapport_pdf", {})),
            financier=dict(raw.get("financier", {})),
            machine_sens=dict(dataset.get("machine_sens_par_operation", {})),
            s1_piece_patterns=s1_piece_patterns,
            s1_operations_synonymes=s1_operations_synonymes,
        )

    def iter_facteurs(self) -> list[tuple[str, str, dict]]:
        """(scope_op, facteur_key, config) — scope COMMUN, FILAGE ou EQUATOR."""
        out: list[tuple[str, str, dict]] = []
        for scope, facteurs in self.entites_facteurs.items():
            if not isinstance(facteurs, dict):
                continue
            for key, cfg in facteurs.items():
                if isinstance(cfg, dict):
                    out.append((scope, key, cfg))
        return out

    def iter_variables(self) -> list[tuple[str, str, dict]]:
        """(operation, variable_key, config) — FILAGE ou EQUATOR."""
        out: list[tuple[str, str, dict]] = []
        for op, groups in self.entites_variables.items():
            if not isinstance(groups, dict):
                continue
            for key, cfg in groups.items():
                if isinstance(cfg, dict):
                    out.append((op, key, cfg))
        return out

    def get_facteur_config(
        self, facteur_key: str, scope: str | None = None
    ) -> dict | None:
        if scope:
            scope_cfg = self.entites_facteurs.get(scope, {})
            if isinstance(scope_cfg, dict) and facteur_key in scope_cfg:
                return scope_cfg[facteur_key]
            return None
        for _, key, cfg in self.iter_facteurs():
            if key == facteur_key:
                return cfg
        return None

    def get_operation_from_variable(self, variable_key: str) -> str | None:
        for op, vars_dict in self.entites_variables.items():
            if isinstance(vars_dict, dict) and variable_key in vars_dict:
                return op
        return None

    def get_operation_from_facteur(self, facteur_key: str) -> list[str]:
        result: list[str] = []
        for scope, key, _ in self.iter_facteurs():
            if key != facteur_key:
                continue
            if scope == "COMMUN":
                result.extend(self.operations_actives)
            else:
                result.append(scope)
        return list(set(result))

    def infer_operation_from_facteur(self, facteur_key: str) -> list[str]:
        """Alias conservé pour compatibilité interne."""
        return self.get_operation_from_facteur(facteur_key)

    def get_tags_for(self, piece: str, operation: str) -> list[str]:
        piece_cfg = self.pieces.get(piece, {})
        ops = piece_cfg.get("operations", {})
        op_cfg = ops.get(operation, {})
        tags = op_cfg.get("tags", {})
        if not isinstance(tags, dict):
            return []
        return list(tags.keys())

    def get_tolerance(self, piece: str, operation: str, tag: str) -> dict | None:
        piece_cfg = self.pieces.get(piece, {})
        ops = piece_cfg.get("operations", {})
        op_cfg = ops.get(operation, {})
        tags = op_cfg.get("tags", {})
        if not isinstance(tags, dict):
            return None
        tol = tags.get(tag)
        return dict(tol) if isinstance(tol, dict) else None

    def get_group_by_defaut(self, piece: str, operation: str) -> str | None:
        piece_cfg = self.pieces.get(piece, {})
        ops = piece_cfg.get("operations", {})
        op_cfg = ops.get(operation, {})
        return op_cfg.get("group_by_defaut")

    def resolve_tags_for_variable_group(
        self, piece: str, operation: str, group_key: str
    ) -> list[str]:
        """Résout un groupe de variables (ex. forme) en liste de tags pièce+opération."""
        op_groups = self.entites_variables.get(operation, {})
        group = op_groups.get(group_key, {}) if isinstance(op_groups, dict) else {}
        pattern = group.get("pattern_tag", "")
        if not pattern:
            return []
        all_tags = self.get_tags_for(piece, operation)
        regex = pattern.replace("*", ".*")
        if "[" in pattern:
            return [t for t in all_tags if re.search(regex, t)]
        return [t for t in all_tags if fnmatch.fnmatch(t, pattern)]

    def get_recommandations(self) -> dict:
        """Section YAML recommandations (S6) — seuils, délais, responsables."""
        return self.recommandations if isinstance(self.recommandations, dict) else {}

    def get_rapport_pdf(self) -> dict:
        """Section YAML rapport_pdf (S7) — limites graphiques, libellés verdict."""
        return self.rapport_pdf if isinstance(self.rapport_pdf, dict) else {}

    def get_contrat_rapport(self) -> dict:
        """Section YAML contrat_rapport — exigences EN9100 du PDF."""
        raw = self.raw.get("contrat_rapport", {})
        return raw if isinstance(raw, dict) else {}

    def facteur_colonne(
        self, facteur_key: str, scope: str | None = None
    ) -> str | list[str] | None:
        """Colonne(s) YAML associées à un facteur d'analyse."""
        f = self.get_facteur_config(facteur_key, scope)
        if not f:
            return None
        if "colonne" in f:
            return f["colonne"]
        cols = []
        if "colonne_ext" in f:
            cols.append(f["colonne_ext"])
        if "colonne_int" in f:
            cols.append(f["colonne_int"])
        return cols[0] if len(cols) == 1 else (cols if cols else None)
