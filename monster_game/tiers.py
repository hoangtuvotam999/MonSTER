"""Item-tier registry.

Authors add a row here, then a tier_<id>.json catalog under weapon, equipment,
or drop. Shop, forge, attacks, and drops read this file. Monster Tier on a map
(I, II, V, X, XX) is a separate axis: it only caps how high a drop can be.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_PATH = Path(__file__).resolve().parent / "data" / "tiers.json"
_cache: Optional[list[dict]] = None

# Monster encounter grade -> highest item rank that fight may drop.
MONSTER_ITEM_CAP = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 6,
    "X": 8,
    "XX": 10,
}


def reload() -> None:
    global _cache
    _cache = None


def all_tiers() -> list[dict]:
    global _cache
    if _cache is None:
        _cache = json.loads(_PATH.read_text(encoding="utf-8"))
    return _cache


def resolve(token) -> Optional[dict]:
    """Match a catalog tier id, an alias such as A, or a rank number."""
    if token is None or token == "":
        return None
    key = str(token).strip()
    upper = key.upper()
    for row in all_tiers():
        if str(row.get("id")) == key or str(row.get("id")).upper() == upper:
            return row
        aliases = {str(alias).upper() for alias in row.get("aliases") or []}
        if upper in aliases:
            return row
    return None


def label_of(token) -> str:
    row = resolve(token)
    return str(row["label"]) if row else str(token or "")


def is_shop(item: Optional[dict]) -> bool:
    if not item:
        return False
    row = resolve(item.get("tier"))
    return bool(row and row.get("shop"))


def drop_tiers() -> list[dict]:
    return [row for row in all_tiers() if row.get("drop") and float(row.get("drop_chance") or 0) > 0]


def monster_item_cap(monster_tier) -> Optional[int]:
    return MONSTER_ITEM_CAP.get(str(monster_tier or "").upper())


def attack_letter(rank: int) -> str:
    """Ranks 1–3 keep the A/B/C kits. Rank 4 and above use the D kit."""
    return {1: "A", 2: "B", 3: "C"}.get(int(rank), "D")


def attack_scale(rank: int) -> float:
    """Ranks 5 and up hit harder than the D kit. Earlier ranks stay as written."""
    rank = int(rank)
    if rank < 5:
        return 1.0
    return 1 + 0.03 * (rank - 4)


def same_tier(item: Optional[dict], row: dict) -> bool:
    found = resolve((item or {}).get("tier"))
    return bool(found and str(found.get("id")) == str(row.get("id")))
