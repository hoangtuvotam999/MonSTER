"""
Combat engine — port of fight.js (PvE) and pvp.js (PvP).

Both original files implemented an almost identical turn-based battle:
- Whoever has higher SPD attacks first and gets multiple turns in a row,
  proportional to the SPD ratio (floor(mySPD / theirSPD) turns per "round").
- Every attack builds 25 Mana; at 100+ Mana the attack becomes a 1.5x
  "skill" hit and Mana resets to 0.
- Damage = max((ATK - DEF * ArmorPiercing) * multiplier, 1).

This module unifies both into one `_run_battle` core, matching the
original output shape (a `log` of per-turn snapshots, plus a `winner`).
"""
from __future__ import annotations

import math
from typing import TypedDict


class CombatStats(TypedDict):
    HP: float
    ATK: float
    DEF: float
    SPD: float
    AP: float  # ArmorPiercing multiplier (1 = no mitigation, 0 = full pierce)
    Mana: float


def _turns_for(speed: float, other_speed: float) -> int:
    if other_speed <= 0:
        return 1
    return math.floor(speed / other_speed)


def _run_battle(a_stats: CombatStats, b_stats: CombatStats, a_label: str, b_label: str) -> dict:
    log = []
    turn = 0
    a_turns = _turns_for(a_stats["SPD"], b_stats["SPD"])
    b_turns = _turns_for(b_stats["SPD"], a_stats["SPD"])
    current = a_label if a_stats["SPD"] >= b_stats["SPD"] else b_label

    def damage_multiplier(attacker: CombatStats) -> float:
        if attacker["Mana"] >= 100:
            attacker["Mana"] = 0
            return 1.5
        return 1.0

    def calculate_damage(attacker: CombatStats, defender: CombatStats):
        multiplier = damage_multiplier(attacker)
        reduced_def = defender["DEF"] * attacker["AP"]
        damage = max((attacker["ATK"] - reduced_def) * multiplier, 1)
        # Kept from the original: this is *not* the defender's remaining
        # DEF, it's the attacker's ATK minus the damage actually dealt.
        attacker_remainder = attacker["ATK"] - damage
        return round(damage), attacker_remainder

    while a_stats["HP"] > 0 and b_stats["HP"] > 0:
        attacker = a_stats if current == a_label else b_stats
        defender = b_stats if current == a_label else a_stats

        attacker["Mana"] += 25
        damage, defender_def = calculate_damage(attacker, defender)
        defender["HP"] -= damage

        log.append({
            "turn": turn,
            a_label: dict(a_stats),
            b_label: dict(b_stats),
            "damage": damage,
            "defenderDef": defender_def,
            "attacker": current,
            "skill": "skill" if attacker["Mana"] == 0 else "normal",
        })
        turn += 1

        if current == a_label:
            a_turns -= 1
            if a_turns <= 0:
                current = b_label
                a_turns = 0
                b_turns = max(1, _turns_for(b_stats["SPD"], a_stats["SPD"]))
        else:
            b_turns -= 1
            if b_turns <= 0:
                current = a_label
                b_turns = 0
                a_turns = max(1, _turns_for(a_stats["SPD"], b_stats["SPD"]))

    winner = b_label if a_stats["HP"] <= 0 else a_label
    return {"winner": winner, "log": log, a_label: a_stats, b_label: b_stats}


def fight_monster(player_stats: CombatStats, monster_stats: CombatStats) -> dict:
    """Port of fight.js. Returns {'winner': bool, 'log': [...], 'playerPow': {...}}
    matching the original's return contract (winner=True means the player won)."""
    result = _run_battle(dict(player_stats), dict(monster_stats), "player", "monster")
    return {
        "winner": result["winner"] == "player",
        "log": result["log"],
        "playerPow": result["player"],
    }


def build_combat_stats(character: dict) -> CombatStats:
    """Derive HP/ATK/DEF/SPD/AP from a character + its equipped weapon,
    exactly like the ad-hoc object literals built inline in index.js's
    match() and pvp.js's caller."""
    w = character["weapon"]
    return {
        "HP": (character["hp"] + w["HP"]) * w["hpBonus"],
        "ATK": (character["atk"] + w["ATK"]) * w["dmgBonus"],
        "DEF": (character["def"] + w["DEF"]) * w["defBonus"],
        "SPD": (character["spd"] + w["SPD"]) * w["spdBonus"],
        "AP": w["ArmorPiercing"],
        "Mana": 1,
    }


def fight_pvp(char1: dict, char2: dict) -> dict:
    """Port of pvp.js. Both args are full character dicts with an equipped
    weapon; stats are derived automatically."""
    p1 = build_combat_stats(char1)
    p2 = build_combat_stats(char2)
    return _run_battle(p1, p2, "player1", "player2")
