"""Random travel beats between hunts. Solo and party share the catalog."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

from . import adventure, data_store

_BEATS: Optional[list[dict]] = None
_PATH = Path(__file__).resolve().parent / "data" / "journey" / "beats.json"


def beats() -> list[dict]:
    global _BEATS
    if _BEATS is None:
        _BEATS = json.loads(_PATH.read_text(encoding="utf-8"))
    return _BEATS


def _eligible(location_name: str, mode: str) -> list[dict]:
    found = []
    for beat in beats():
        modes = beat.get("modes") or ["solo", "party"]
        if mode not in modes:
            continue
        maps = beat.get("maps") or ["*"]
        if "*" not in maps and location_name not in maps:
            continue
        found.append(beat)
    return found


def _apply_one(player_id: str, outcome: dict, rng: random.Random) -> list[str]:
    lines = []
    effects = outcome.get("effects") or {}
    if effects:
        applied = data_store.apply_effects(player_id, effects)
        if not isinstance(applied, dict):
            applied = {}
        if effects.get("the_luc"):
            delta = int(effects["the_luc"])
            lines.append(f"⚡ Thể lực {'+' if delta > 0 else ''}{delta}")
        gold_delta = int(applied.get("gold_delta") or 0)
        if gold_delta:
            data_store.add_gold(player_id, gold_delta)
            lines.append(f"💰 {'+' if gold_delta > 0 else ''}{gold_delta} vàng")
    for item in adventure.grant_drops(player_id, outcome.get("drops") or [], rng=rng):
        lines.append(f"🎁 {item.get('name', 'vật phẩm')} ×{item.get('qty', 1)}")
    return lines


def play(player_ids: list[str], location: dict, mode: str = "solo",
         rng: Optional[random.Random] = None) -> dict:
    """Roll a short or long trail and apply it to every listed hunter."""
    rng = rng or random.Random()
    name = location.get("name") or ""
    # One optional roadside event. Most hunts are only the fight.
    if rng.random() > 0.15:
        return {"length": 0, "beats": [], "lines": [], "happened": False}
    pool = _eligible(name, mode)
    length = 1
    chosen: list[dict] = []
    bag = list(pool)
    rng.shuffle(bag)
    while len(chosen) < length and bag:
        weights = [max(1, int(b.get("weight", 1))) for b in bag]
        pick = rng.choices(bag, weights=weights, k=1)[0]
        chosen.append(pick)
        bag = [b for b in bag if b.get("id") != pick.get("id")]
        if not bag and len(chosen) < length:
            break

    rendered = []
    flat_lines = [f"📍 {name}"]
    for beat in chosen:
        outcomes = beat.get("outcomes") or [{"log": beat.get("intro") or ""}]
        outcome = adventure._chance_choice(outcomes) or {}
        block = [f"✨ {beat.get('title', 'Sự kiện')}", beat.get("intro") or "", outcome.get("log") or ""]
        notes: list[str] = []
        for pid in player_ids:
            notes.extend(_apply_one(pid, outcome, rng))
        seen = set()
        for line in notes:
            if line in seen:
                continue
            seen.add(line)
            block.append(line)
        block = [ln for ln in block if ln]
        rendered.append({
            "id": beat.get("id"),
            "title": beat.get("title"),
            "intro": beat.get("intro"),
            "log": outcome.get("log"),
            "lines": block,
        })
        flat_lines.extend(block)
    return {"length": len(rendered), "beats": rendered, "lines": flat_lines, "happened": bool(rendered)}
