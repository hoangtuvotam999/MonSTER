"""
Combat engine — turn-based PvE / PvP with:
- SPD multi-hit rounds + Mana skill (1.5x)
- Equipment bonuses folded into combat stats
- Monster action scripts (weighted / conditional moves)
- 5-slot consumable belt: auto-heal, buffs, and special triggers
  (Đồng quy vô tận, sát thương tức thì, phoenix tear, smoke bomb)
"""
from __future__ import annotations

import math
import random
from typing import Optional, TypedDict

from . import equipment as equip_mod


class CombatStats(TypedDict, total=False):
    HP: float
    ATK: float
    DEF: float
    SPD: float
    AP: float
    Mana: float
    maxHP: float
    mana_gain: float
    atk_buff: float
    def_buff: float
    buff_atk_turns: int
    buff_def_turns: int
    incoming_reduce: float
    incoming_reduce_turns: int


MAX_TURNS = 5000
DEFAULT_MANA_GAIN = 25

_PLAIN_ATTACKS = [
    {"id": "swing", "name": "Vung", "weight": 1, "mult": 1.0, "flavor": "vung vũ khí"},
]

_ATTACK_CACHE: Optional[dict] = None


def _attack_catalog() -> dict:
    global _ATTACK_CACHE
    if _ATTACK_CACHE is None:
        from pathlib import Path
        import json
        path = Path(__file__).resolve().parent / "data" / "item" / "weapon" / "attacks.json"
        _ATTACK_CACHE = json.loads(path.read_text(encoding="utf-8"))
    return _ATTACK_CACHE


def player_attacks(weapon: Optional[dict]) -> list[dict]:
    """Flavor strikes for the equipped weapon. Untiered weapons stay plain."""
    if not weapon:
        return list(_PLAIN_ATTACKS)
    own = weapon.get("attacks")
    if own:
        return list(own)
    from . import tiers as tier_mod

    cat = weapon.get("category") or "*"
    tier = weapon.get("tier") or ""
    catalog = _attack_catalog()
    by_cat = (catalog.get("by_category") or {}).get(cat) or {}
    row = tier_mod.resolve(tier)
    letter = tier_mod.attack_letter(row["rank"]) if row else str(tier)
    scale = tier_mod.attack_scale(row["rank"]) if row else 1.0
    moves = by_cat.get(letter) if letter in by_cat else None
    if moves is None and tier in by_cat:
        moves = by_cat[tier]
    if moves is None and ("" in by_cat or "*" in by_cat):
        moves = by_cat.get("", by_cat.get("*", _PLAIN_ATTACKS))
    if moves is None:
        moves = (catalog.get("by_category") or {}).get("*", {}).get("*", _PLAIN_ATTACKS)
    copied = [dict(move) for move in moves]
    if scale != 1:
        for move in copied:
            move["mult"] = round(float(move.get("mult", 1)) * scale, 4)
    return copied


def _turns_for(speed: float, other_speed: float, rng: Optional[random.Random] = None) -> int:
    """Whole turns from the speed ratio, plus one extra when the fraction hits."""
    if other_speed <= 0:
        return 1
    ratio = speed / other_speed
    whole = math.floor(ratio)
    extra = 0
    frac = ratio - whole
    if frac > 0 and rng is not None and rng.random() < frac:
        extra = 1
    return max(1, whole + extra)


def _snap(stats: CombatStats) -> dict:
    return {
        "HP": stats["HP"],
        "ATK": stats["ATK"],
        "DEF": stats["DEF"],
        "SPD": stats["SPD"],
        "AP": stats.get("AP", 1),
        "Mana": stats.get("Mana", 0),
        "maxHP": stats.get("maxHP", stats["HP"]),
    }


def _pick_monster_action(actions: list[dict], monster_hp: float, monster_max: float,
                         rng: random.Random) -> dict:
    frac = monster_hp / monster_max if monster_max > 0 else 1
    eligible = []
    for act in actions or []:
        when = act.get("when")
        if when == "hp_below_40" and frac >= 0.4:
            continue
        if when == "hp_below_35" and frac >= 0.35:
            continue
        if when == "hp_below_30" and frac >= 0.30:
            continue
        if when == "hp_below_20" and frac >= 0.20:
            continue
        # Conditional moves get a weight boost when active
        weight = float(act.get("weight", 1))
        if when:
            weight *= 1.8
        eligible.append((act, weight))
    if not eligible:
        return {"id": "strike", "name": "Tấn công", "mult": 1.0, "flavor": "tấn công"}
    acts, weights = zip(*eligible)
    return rng.choices(list(acts), weights=list(weights), k=1)[0]


def _calc_damage(attacker: CombatStats, defender: CombatStats, mult: float = 1.0,
                  def_scale: float = 1.0) -> tuple[float, bool]:
    """Returns (damage, used_skill). `def_scale` below 1 ignores part of DEF."""
    mana_gain = attacker.get("mana_gain", DEFAULT_MANA_GAIN)
    attacker["Mana"] = attacker.get("Mana", 0) + mana_gain
    skill = False
    skill_mult = 1.0
    if attacker["Mana"] >= 100:
        attacker["Mana"] = 0
        skill_mult = 1.5
        skill = True

    atk = attacker["ATK"] * attacker.get("atk_buff", 1.0) * skill_mult * mult
    defense = defender["DEF"] * defender.get("def_buff", 1.0) * def_scale
    # ArmorPiercing above 1 reduces the defender's effective DEF. 1 is neutral.
    ap = float(attacker.get("AP", 1) or 1)
    if ap > 1:
        defense = defense / ap
    # DEF mitigates a fraction of ATK. Flat (ATK - DEF) used to floor at 1
    # whenever a weapon's DEF exceeded a low-level monster's ATK.
    ratio = defense / (defense + max(atk, 1))
    reduction = min(0.72, ratio)
    raw = atk * (1.0 - reduction)
    incoming_reduce = defender.get("incoming_reduce", 0) or 0
    if defender.get("incoming_reduce_turns", 0) > 0 and incoming_reduce:
        raw *= (1.0 - incoming_reduce)
    return max(1, round(raw)), skill


def _tick_buffs(stats: CombatStats) -> None:
    if stats.get("buff_atk_turns", 0) > 0:
        stats["buff_atk_turns"] -= 1
        if stats["buff_atk_turns"] <= 0:
            stats["atk_buff"] = 1.0
    if stats.get("buff_def_turns", 0) > 0:
        stats["buff_def_turns"] -= 1
        if stats["buff_def_turns"] <= 0:
            stats["def_buff"] = 1.0
    if stats.get("incoming_reduce_turns", 0) > 0:
        stats["incoming_reduce_turns"] -= 1
        if stats["incoming_reduce_turns"] <= 0:
            stats["incoming_reduce"] = 0.0


def _belt_items(belt: list) -> list[tuple[int, dict]]:
    return [(i, it) for i, it in enumerate(belt or []) if it]


def _try_auto_heal(player: CombatStats, belt: list, rng: random.Random) -> Optional[dict]:
    frac = player["HP"] / player["maxHP"] if player.get("maxHP") else 1
    candidates = []
    for idx, item in _belt_items(belt):
        if item.get("subtype") != "heal":
            continue
        auto = item.get("auto") or {}
        if auto.get("when") == "hp_below" and frac < float(auto.get("threshold", 0.4)):
            candidates.append((int(auto.get("priority", 0)), idx, item))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, idx, item = candidates[0]
    heal = max(int(item.get("heal_hp_flat", 0)),
               round(player["maxHP"] * float(item.get("heal_hp_pct", 0))))
    player["HP"] = min(player["maxHP"], player["HP"] + heal)
    used = equip_mod.consume_belt_charge({"consumables": belt}, idx)
    return {
        "kind": "use_item",
        "item_id": item.get("id"),
        "item_name": item.get("name"),
        "heal": heal,
        "log": f"💊 {item['name']} vỡ tan — hồi {heal} HP!",
    }


def _try_auto_buff(player: CombatStats, belt: list) -> Optional[dict]:
    frac = player["HP"] / player["maxHP"] if player.get("maxHP") else 1
    for idx, item in _belt_items(belt):
        if item.get("subtype") != "buff":
            continue
        auto = item.get("auto") or {}
        if auto.get("when") == "hp_below" and frac >= float(auto.get("threshold", 0.5)):
            continue
        turns = int(item.get("buff_turns", 3))
        if item.get("buff_atk"):
            player["atk_buff"] = float(item["buff_atk"])
            player["buff_atk_turns"] = turns
            used = equip_mod.consume_belt_charge({"consumables": belt}, idx)
            return {
                "kind": "use_item",
                "item_id": item.get("id"),
                "item_name": item.get("name"),
                "log": f"💉 {item['name']}! ATK tăng trong {turns} đòn.",
            }
        if item.get("buff_def"):
            player["def_buff"] = float(item["buff_def"])
            player["buff_def_turns"] = turns
            used = equip_mod.consume_belt_charge({"consumables": belt}, idx)
            return {
                "kind": "use_item",
                "item_id": item.get("id"),
                "item_name": item.get("name"),
                "log": f"🛡️ {item['name']}! DEF tăng trong {turns} đòn.",
            }
    return None


def _try_specials(player: CombatStats, monster: CombatStats, belt: list,
                  rng: random.Random, *, would_die: bool = False,
                  incoming_damage: float = 0) -> list[dict]:
    """Fire special belt items. May end the fight (mutual doom)."""
    events = []
    p_frac = player["HP"] / player["maxHP"] if player.get("maxHP") else 1
    m_frac = monster["HP"] / monster["maxHP"] if monster.get("maxHP") else 1

    # Snapshot indices — consuming shifts None into place
    for idx, item in list(_belt_items(belt)):
        special = item.get("special")
        trigger = item.get("trigger") or {}
        chance = float(trigger.get("chance", 1))
        when = trigger.get("when")
        thr = float(trigger.get("threshold", 0.2))

        fire = False
        if special == "revive" and would_die and when == "would_die":
            fire = rng.random() < chance
        elif special == "mutual_doom" and when == "hp_below" and p_frac < thr:
            fire = rng.random() < chance
        elif special == "mutual_burst" and when == "both_hp_below":
            if p_frac < thr and m_frac < thr:
                fire = rng.random() < chance
        elif special == "escape_chip" and when == "hp_below" and p_frac < thr:
            fire = rng.random() < chance

        if not fire:
            continue

        effect = item.get("effect") or {}
        equip_mod.consume_belt_charge({"consumables": belt}, idx)

        if special == "mutual_doom":
            player["HP"] = 0
            monster["HP"] = 0
            events.append({
                "kind": "special",
                "special": "mutual_doom",
                "item_name": item["name"],
                "log": f"☠️ {item['name']} kích hoạt — ĐỒNG QUY VÔ TẬN! Hai bên cùng gục!",
            })
            break

        if special == "mutual_burst":
            pct = float(effect.get("damage_both_pct_max", 0.3))
            flat = float(effect.get("damage_both_flat", 0))
            dmg_p = round(player["maxHP"] * pct + flat)
            dmg_m = round(monster["maxHP"] * pct + flat)
            player["HP"] = max(0, player["HP"] - dmg_p)
            monster["HP"] = max(0, monster["HP"] - dmg_m)
            events.append({
                "kind": "special",
                "special": "mutual_burst",
                "item_name": item["name"],
                "damage_player": dmg_p,
                "damage_monster": dmg_m,
                "log": (f"💥 {item['name']} — sát thương tức thì! "
                        f"Bạn −{dmg_p}, địch −{dmg_m}!"),
            })
            break

        if special == "revive":
            heal = round(player["maxHP"] * float(effect.get("heal_hp_pct", 0.35)))
            player["HP"] = max(1, heal)
            events.append({
                "kind": "special",
                "special": "revive",
                "item_name": item["name"],
                "heal": heal,
                "log": f"🔥 {item['name']} cháy sáng — bạn sống lại với {heal} HP!",
            })
            break

        if special == "escape_chip":
            player["incoming_reduce"] = float(effect.get("reduce_incoming_pct", 0.7))
            player["incoming_reduce_turns"] = int(effect.get("turns", 1))
            # Also blunt the current incoming hit if any
            if incoming_damage and would_die:
                mitigated = round(incoming_damage * (1 - player["incoming_reduce"]))
                player["HP"] = max(1, player["HP"] + incoming_damage - mitigated)
            events.append({
                "kind": "special",
                "special": "escape_chip",
                "item_name": item["name"],
                "log": f"💨 {item['name']} nổ tung — bạn lẩn vào khói, giảm sát thương!",
            })
            break

    return events


def _tempo_mult(attacker: CombatStats, effect: Optional[str]) -> tuple[float, str]:
    """Hits after the first in a speed chain hit harder when the move is tempo."""
    chain = int(attacker.get("hits_in_chain") or 0)
    attacker["hits_in_chain"] = chain + 1
    if effect != "tempo" or chain <= 0:
        return 1.0, ""
    bonus = min(0.24, 0.08 * chain)
    return 1.0 + bonus, f"Nhịp đòn +{int(round(bonus * 100))}%."


def _apply_weapon_effect(effect: Optional[str], attacker: CombatStats, defender: CombatStats,
                         damage: float, rng: random.Random) -> tuple[float, str]:
    """Category tricks. Returns (extra damage already applied to HP, log line)."""
    if effect == "stagger" and rng.random() < 0.30:
        defender["skip_next"] = True
        return 0, "Đòn nặng làm đối thủ mất lượt kế."
    if effect == "brace":
        attacker["def_buff"] = max(float(attacker.get("def_buff") or 1), 1.2)
        attacker["buff_def_turns"] = max(int(attacker.get("buff_def_turns") or 0), 2)
        return 0, "Thế đỡ nâng lớp phòng thủ."
    if effect == "bleed":
        tick = max(1, round(damage * 0.08))
        defender["bleed_dmg"] = tick
        defender["bleed_left"] = 2
        return 0, f"Vết chém rỉ máu, mỗi lượt −{tick}."
    if effect == "blast":
        extra = max(1, round(float(defender.get("maxHP") or defender["HP"]) * 0.05))
        defender["HP"] -= extra
        return extra, f"Nổ thêm {extra} sát thương."
    if effect == "snipe":
        return 0, "Đòn xuyên, chỉ chịu 70% lớp đỡ."
    return 0, ""


def _apply_monster_effect(effect: Optional[str], player: CombatStats,
                          monster: CombatStats, damage: float) -> Optional[str]:
    if not effect:
        return None
    if effect == "mana_drain":
        player["Mana"] = max(0, player.get("Mana", 0) - 40)
        return "Mana của bạn bị rung chuyển (−40)."
    if effect == "curse":
        player["def_buff"] = min(player.get("def_buff", 1.0), 0.85)
        player["buff_def_turns"] = max(player.get("buff_def_turns", 0), 2)
        return "Lời nguyền làm DEF bạn suy yếu!"
    if effect == "lifesteal":
        heal = round(damage * 0.35)
        monster["HP"] = min(monster["maxHP"], monster["HP"] + heal)
        return f"Quái hút {heal} sinh lực!"
    return None


def _run_battle(a_stats: CombatStats, b_stats: CombatStats, a_label: str, b_label: str,
                *, a_actions: Optional[list] = None, b_actions: Optional[list] = None,
                a_belt: Optional[list] = None, b_belt: Optional[list] = None,
                a_weapon_category: str = "",
                rng: Optional[random.Random] = None) -> dict:
    rng = rng or random.Random()
    log = []
    turn = 0
    a_stats = dict(a_stats)
    b_stats = dict(b_stats)
    a_stats.setdefault("maxHP", a_stats["HP"])
    b_stats.setdefault("maxHP", b_stats["HP"])
    a_stats.setdefault("atk_buff", 1.0)
    b_stats.setdefault("atk_buff", 1.0)
    a_stats.setdefault("def_buff", 1.0)
    b_stats.setdefault("def_buff", 1.0)
    a_belt = list(a_belt) if a_belt is not None else []
    b_belt = list(b_belt) if b_belt is not None else []

    a_start_hp = max(a_stats["HP"], 1)
    b_start_hp = max(b_stats["HP"], 1)
    a_turns = _turns_for(a_stats["SPD"], b_stats["SPD"], rng)
    b_turns = _turns_for(b_stats["SPD"], a_stats["SPD"], rng)
    current = a_label if a_stats["SPD"] >= b_stats["SPD"] else b_label

    while a_stats["HP"] > 0 and b_stats["HP"] > 0 and turn < MAX_TURNS:
        attacker = a_stats if current == a_label else b_stats
        defender = b_stats if current == a_label else a_stats
        atk_actions = a_actions if current == a_label else b_actions
        atk_belt = a_belt if current == a_label else b_belt
        is_player_side = current in ("player", "player1")

        def _end_action() -> None:
            nonlocal current, a_turns, b_turns
            if current == a_label:
                a_turns -= 1
                if a_turns <= 0:
                    current = b_label
                    a_turns = 0
                    a_stats["hits_in_chain"] = 0
                    b_stats["hits_in_chain"] = 0
                    b_turns = _turns_for(b_stats["SPD"], a_stats["SPD"], rng)
            else:
                b_turns -= 1
                if b_turns <= 0:
                    current = a_label
                    b_turns = 0
                    a_stats["hits_in_chain"] = 0
                    b_stats["hits_in_chain"] = 0
                    a_turns = _turns_for(a_stats["SPD"], b_stats["SPD"], rng)

        bleed_left = int(attacker.get("bleed_left") or 0)
        if bleed_left > 0:
            tick = int(attacker.get("bleed_dmg") or 0)
            attacker["HP"] -= tick
            attacker["bleed_left"] = bleed_left - 1
            log.append({
                "turn": turn, "attacker": current, "action": "bleed",
                "action_name": "Chảy máu", "skill": "effect",
                "damage": tick, "defenderDef": 0, "events": [],
                a_label: _snap(a_stats), b_label: _snap(b_stats),
                "flavor": f"vết chém rỉ thêm {tick}",
            })
            turn += 1
            if attacker["HP"] <= 0:
                break

        if attacker.get("skip_next"):
            attacker["skip_next"] = False
            log.append({
                "turn": turn, "attacker": current, "action": "stagger",
                "action_name": "Mất nhịp", "skill": "effect",
                "damage": 0, "defenderDef": 0, "events": [],
                a_label: _snap(a_stats), b_label: _snap(b_stats),
                "flavor": "mất nhịp, không ra đòn",
            })
            turn += 1
            _end_action()
            continue

        # Pre-turn: auto heal / buff for player-like sides
        if is_player_side and atk_belt is not None:
            heal_ev = _try_auto_heal(attacker, atk_belt, rng)
            if heal_ev:
                log.append({
                    "turn": turn, "attacker": current, "action": "use_item",
                    "action_name": heal_ev.get("item_name"),
                    "skill": "item", "damage": 0, "defenderDef": 0,
                    "events": [heal_ev],
                    a_label: _snap(a_stats), b_label: _snap(b_stats),
                    "flavor": heal_ev["log"],
                })
                turn += 1
            buff_ev = _try_auto_buff(attacker, atk_belt)
            if buff_ev:
                log.append({
                    "turn": turn, "attacker": current, "action": "use_item",
                    "action_name": buff_ev.get("item_name"),
                    "skill": "item", "damage": 0, "defenderDef": 0,
                    "events": [buff_ev],
                    a_label: _snap(a_stats), b_label: _snap(b_stats),
                    "flavor": buff_ev["log"],
                })
                turn += 1

        # Choose action
        if atk_actions:
            act = _pick_monster_action(atk_actions, attacker["HP"], attacker["maxHP"], rng)
        else:
            act = {
                "id": "strike",
                "name": "Đòn đánh",
                "mult": 1.0,
                "flavor": "tấn công",
            }

        mult = float(act.get("mult", 1.0))
        effect = act.get("effect")
        tempo, tempo_note = _tempo_mult(attacker, effect)
        def_scale = 0.7 if effect == "snipe" else 1.0
        damage, skill = _calc_damage(attacker, defender, mult * tempo, def_scale=def_scale)
        defender["HP"] -= damage
        extra, weapon_note = _apply_weapon_effect(effect, attacker, defender, damage, rng)
        damage += extra
        if effect in ("stagger", "brace", "bleed", "tempo", "blast", "snipe"):
            effect_note = weapon_note
        else:
            effect_note = _apply_monster_effect(effect, defender, attacker, damage)

        entry = {
            "turn": turn,
            a_label: _snap(a_stats),
            b_label: _snap(b_stats),
            "damage": damage,
            "defenderDef": attacker["ATK"] - damage,
            "attacker": current,
            "skill": "skill" if skill else "normal",
            "action": act.get("id", "strike"),
            "action_name": act.get("name", "Tấn công"),
            "flavor": act.get("flavor") or act.get("name"),
            "events": [],
        }
        if tempo_note:
            entry["events"].append({"kind": "effect", "log": tempo_note})
        if effect_note:
            entry["events"].append({"kind": "effect", "log": effect_note})

        # If defender is player-like and would die / is low — specials
        def_is_player = (defender is a_stats and a_label in ("player", "player1")) or \
                        (defender is b_stats and b_label in ("player", "player2"))
        def_belt = a_belt if defender is a_stats else b_belt
        if def_is_player and def_belt is not None:
            would_die = defender["HP"] <= 0
            # temporarily restore to evaluate revive against the hit
            if would_die:
                defender["HP"] = 0
            specials = _try_specials(
                defender, attacker, def_belt, rng,
                would_die=would_die, incoming_damage=damage,
            )
            entry["events"].extend(specials)

        # Low-HP specials on attacker's own belt (mutual doom / burst)
        if is_player_side and atk_belt is not None and attacker["HP"] > 0:
            specials = _try_specials(attacker, defender, atk_belt, rng)
            entry["events"].extend(specials)

        log.append(entry)
        turn += 1
        _tick_buffs(attacker)

        if a_stats["HP"] <= 0 or b_stats["HP"] <= 0:
            break

        _end_action()

    if a_stats["HP"] <= 0 and b_stats["HP"] <= 0:
        winner = "draw"
    elif a_stats["HP"] <= 0:
        winner = b_label
    elif b_stats["HP"] <= 0:
        winner = a_label
    else:
        winner = a_label if a_stats["HP"] / a_start_hp >= b_stats["HP"] / b_start_hp else b_label

    return {
        "winner": winner,
        "log": log,
        a_label: a_stats,
        b_label: b_stats,
        "a_belt": a_belt,
        "b_belt": b_belt,
    }


def build_combat_stats(character: dict) -> CombatStats:
    """Derive combat stats from character + weapon + equipment."""
    from . import equipment as eq  # local to avoid cycles at import of game

    w = character["weapon"]
    if w is None:
        raise ValueError("character has no equipped weapon")
    eq.ensure_loadout(character)
    gear = eq.equipment_bonuses(character)

    hp = (character["hp"] + w["HP"] + gear["hp"]) * w.get("hpBonus", 1) * gear["hpBonus"]
    atk = (character["atk"] + w["ATK"] + gear["atk"]) * w.get("dmgBonus", 1) * gear["dmgBonus"]
    defense = (character["def"] + w["DEF"] + gear["def"]) * w.get("defBonus", 1) * gear["defBonus"]
    spd = (character["spd"] + w["SPD"] + gear["spd"]) * w.get("spdBonus", 1) * gear["spdBonus"]
    spent = character.get("spent") or {}
    hp *= 1 + 0.01 * int(spent.get("hp") or 0)
    atk *= 1 + 0.01 * int(spent.get("atk") or 0)
    defense *= 1 + 0.01 * int(spent.get("def") or 0)
    # Weapon AP blended with best gear pierce
    ap = min(float(w.get("ArmorPiercing", 1)), float(gear.get("ArmorPiercing", 1)))

    return {
        "HP": hp,
        "ATK": atk,
        "DEF": defense,
        "SPD": spd,
        "AP": ap,
        "Mana": 1,
        "maxHP": hp,
        "mana_gain": DEFAULT_MANA_GAIN + int(gear.get("mana_gain", 0)),
        "atk_buff": 1.0,
        "def_buff": 1.0,
        "buff_atk_turns": 0,
        "buff_def_turns": 0,
        "incoming_reduce": 0.0,
        "incoming_reduce_turns": 0,
    }


def fight_monster(player_stats: CombatStats, monster_stats: CombatStats,
                  *, monster_actions: Optional[list] = None,
                  player_belt: Optional[list] = None,
                  weapon_category: str = "",
                  weapon: Optional[dict] = None,
                  rng: Optional[random.Random] = None) -> dict:
    result = _run_battle(
        dict(player_stats), dict(monster_stats), "player", "monster",
        a_actions=player_attacks(weapon),
        b_actions=monster_actions,
        a_belt=player_belt,
        a_weapon_category=weapon_category or (weapon or {}).get("category") or "",
        rng=rng,
    )
    winner = result["winner"]
    return {
        "winner": winner == "player",
        "draw": winner == "draw",
        "log": result["log"],
        "playerPow": result["player"],
        "monsterPow": result["monster"],
        "belt": result.get("a_belt"),
    }


def fight_pvp(char1: dict, char2: dict, rng: Optional[random.Random] = None) -> dict:
    p1 = build_combat_stats(char1)
    p2 = build_combat_stats(char2)
    from . import equipment as eq
    eq.ensure_loadout(char1)
    eq.ensure_loadout(char2)
    return _run_battle(
        p1, p2, "player1", "player2",
        a_belt=list(char1.get("consumables") or []),
        b_belt=list(char2.get("consumables") or []),
        rng=rng,
    )
