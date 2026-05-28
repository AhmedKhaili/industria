"""
Modèle intermédiaire S7 — sections pré-formatées pour le rendu PDF.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReportBlock:
    block_type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportDocument:
    meta: dict[str, Any] = field(default_factory=dict)
    blocks: list[ReportBlock] = field(default_factory=list)

    def block_types(self) -> list[str]:
        return [b.block_type for b in self.blocks]

    def find(self, block_type: str) -> ReportBlock | None:
        for block in self.blocks:
            if block.block_type == block_type:
                return block
        return None

    def all_text(self) -> str:
        parts: list[str] = []
        for block in self.blocks:
            data = block.data
            if isinstance(data.get("paragraphs"), list):
                parts.extend(str(p) for p in data["paragraphs"])
            if isinstance(data.get("label"), str):
                parts.append(data["label"])
            if isinstance(data.get("rows"), list):
                for row in data["rows"]:
                    if isinstance(row, (list, tuple)):
                        parts.extend(str(c) for c in row)
            for key in (
                "action",
                "text",
                "caption",
                "title",
                "synthese_s5",
                "synthese_s6",
                "intro",
                "verdict_normalite",
                "loi_retenue",
            ):
                val = data.get(key)
                if isinstance(val, str):
                    parts.append(val)
            for card in data.get("variables") or []:
                if isinstance(card, dict):
                    parts.append(str(card.get("variable", "")))
                    parts.append(str(card.get("verdict_normalite", "")))
                    parts.append(str(card.get("loi_retenue", "")))
                    for row in card.get("rows") or []:
                        if isinstance(row, (list, tuple)):
                            parts.extend(str(c) for c in row)
            for line in data.get("dunn_summary") or []:
                parts.append(str(line))
            for item in data.get("items") or data.get("recommendations") or []:
                if isinstance(item, dict):
                    for k in ("action", "text", "specialist", "justification"):
                        if item.get(k):
                            parts.append(str(item[k]))
        return "\n".join(parts)
