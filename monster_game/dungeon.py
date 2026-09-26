"""
Dungeon expeditions — multi-room runs (combat / event / treasure / rest / boss).

State is stored on the character as `dungeon_run`. Each call advances one room
or resolves a pending room event choice.
"""
from __future__ import annotations

import random
from typing import Optional

from . import adventure, combat, data_store, equipment as equip_mod


def list_dungeons() -> list[dict]:
    return data_store.list_dungeons()


def get_dungeon(dungeon_id: str) -> Optional[dict]:
    return data_store.get_dungeon(dungeon_id)


def _pick_monster(dungeon: dict, room: dict, player_level: int, karma: int):
    loc_id = dungeon.get("map_ref", 0)
    monsters = data_store.get_monsters(loc_id) or []
    if room.get("monster_name"):
        for m in monsters:
            if m.get("Name") == room["monster_name"]:
                return m
    tier = room.get("monster_tier")
    pool = [m for m in monsters if m.get("Tier") == tier] if tier else list(monsters)
    if not pool:
        pool = monsters
    return random.choice(pool) if pool else None


def start_dungeon(player_id: str, dungeon_id: str) -> dict:
    user = data_store.get_user(player_id)
    dungeon = get_dungeon(dungeon_id)
    if user is None:
        return {"ok": False, "reason": "no_character"}
    if dungeon is None:
        return {"ok": False, "reason": "no_dungeon"}
    if user.get("dungeon_run"):
        return {"ok": False, "reason": "already_in_dungeon",
                "message": "Đang trong dungeon — hoàn thành hoặc bỏ cuộc trước."}
    if user["level"] < int(dungeon.get("min_level", 1)):
        return {"ok": False, "reason": "level_too_low",
                "required_level": dungeon["min_level"]}
    cost = int(dungeon.get("stamina_cost", 50))
    if user.get("the_luc", 0) < cost:
        return {"ok": False, "reason": "no_stamina"}
    if user.get("weapon") is None or user["weapon"].get("durability", 0) <= 0:
        return {"ok": False, "reason": "no_weapon"}

    def do(u):
        u["the_luc"] = max(0, u.get("the_luc", 0) - cost)
        u["dungeon_run"] = {
            "dungeon_id": dungeon_id,
            "room_index": 0,
            "pending_event": None,
            "log": [f"🏰 Bắt đầu {dungeon['name']}"],
            "rooms_cleared": 0,
        }
        return {"ok": True, "dungeon": dungeon["name"], "stamina_cost": cost,
                "room": dungeon["rooms"][0]}

    return data_store._mutate_user(player_id, do)


def abandon_dungeon(player_id: str) -> dict:
    def do(u):
        run = u.get("dungeon_run")
        if not run:
            return {"ok": False, "reason": "not_in_dungeon"}
        u["dungeon_run"] = None
        return {"ok": True, "message": "Bạn rút khỏi dungeon.", "rooms_cleared": run.get("rooms_cleared", 0)}
    return data_store._mutate_user(player_id, do)


def _fight_room(player_id: str, dungeon: dict, room: dict, rng: random.Random) -> dict:
    user = data_store.get_user(player_id)
    template = _pick_monster(dungeon, room, user["level"], user.get("karma", 0))
    if template is None:
        return {"ok": False, "reason": "no_monster"}

    # light scaling
    level = max(user["level"], data_store.get_min_level(dungeon.get("map_ref", 0)) or 1)
    growth = 1 + 0.15 * (level - 1)
    mhp = round(template["HP"] * growth)
    monster_stats = {
        "HP": mhp,
        "ATK": round(template["ATK"] * growth) * template.get("ATKbonus", 1),
        "DEF": round(template["DEF"] * growth) * template.get("DEFbonus", 1),
        "SPD": round(template["SPD"] * growth) * template.get("SPDbonus", 1),
        "AP": template.get("ArmorPiercing", 1),
        "Mana": 1,
        "maxHP": mhp,
    }
    equip_mod.ensure_loadout(user)
    belt = [dict(x) if x else None for x in user.get("consumables") or []]
    pstats = combat.build_combat_stats(user)
    result = combat.fight_monster(
        pstats, monster_stats,
        monster_actions=template.get("actions") or [],
        player_belt=belt,
        rng=rng,
    )

    def after(u):
        equip_mod.ensure_loadout(u)
        if result.get("belt") is not None:
            u["consumables"] = result["belt"]
        # durability tick
        if u.get("weapon"):
            u["weapon"]["durability"] = max(0, u["weapon"]["durability"] - 5)
        return True
    data_store._mutate_user(player_id, after)

    won = bool(result.get("winner")) or bool(result.get("draw"))
    drops = []
    exp = 0
    if won:
        drops = adventure.roll_monster_drops(player_id, template, rng=rng)
        for spec in room.get("bonus_drops") or []:
            drops.extend(adventure.grant_drops(player_id, [spec], rng=rng))
        exp = round(template.get("exp", 50) * (1.2 if room.get("type") == "boss" else 1.0))
        data_store.set_exp(player_id, exp)
        trophy = dict(template)
        trophy["level"] = level
        data_store.add_monster(player_id, trophy)

    return {
        "ok": True,
        "kind": "combat",
        "won": bool(result.get("winner")),
        "draw": bool(result.get("draw")),
        "monster_name": template["Name"],
        "monster_tier": template.get("Tier"),
        "log": result["log"],
        "player_stats": pstats,
        "monster_stats": monster_stats,
        "drops": drops,
        "exp_gained": exp,
        "flavor": room.get("flavor"),
        "title": room.get("title"),
        "weapon_name": user["weapon"]["name"],
        "weapon_category": user["weapon"].get("category"),
        "player_name": user["name"],
    }


def _treasure_room(player_id: str, room: dict, rng: random.Random) -> dict:
    drops = adventure.grant_drops(player_id, room.get("drops") or [], rng=rng)
    gold = 0
    if room.get("gold"):
        lo, hi = room["gold"]
        gold = rng.randint(int(lo), int(hi))
    return {"ok": True, "kind": "treasure", "title": room.get("title"),
            "drops": drops, "gold_delta": gold,
            "log": f"💎 {room.get('title', 'Kho')} — bạn lục được chiến lợi phẩm."}


def _rest_room(player_id: str, room: dict) -> dict:
    heal = int(room.get("heal_stamina", 80))

    def do(u):
        u["the_luc"] = u.get("the_luc", 0) + heal
        return True
    data_store._mutate_user(player_id, do)
    return {"ok": True, "kind": "rest", "title": room.get("title"),
            "log": room.get("log") or "Bạn nghỉ ngơi.", "heal_stamina": heal}


def advance_dungeon(player_id: str, action_id: Optional[str] = None,
                    rng: Optional[random.Random] = None) -> dict:
    """Enter/resolve current room. For event rooms, pass action_id when pending."""
    rng = rng or random.Random()
    user = data_store.get_user(player_id)
    if user is None:
        return {"ok": False, "reason": "no_character"}
    run = user.get("dungeon_run")
    if not run:
        return {"ok": False, "reason": "not_in_dungeon"}
    dungeon = get_dungeon(run["dungeon_id"])
    if dungeon is None:
        return {"ok": False, "reason": "no_dungeon"}

    rooms = dungeon["rooms"]
    idx = int(run["room_index"])
    if idx >= len(rooms):
        return _finish(player_id, cleared=True)

    room = rooms[idx]

    # Pending event choice
    if run.get("pending_event"):
        if not action_id:
            return {"ok": True, "kind": "await_choice", "event": run["pending_event"],
                    "room_index": idx, "dungeon": dungeon["name"]}
        return _resolve_dungeon_event(player_id, dungeon, room, action_id, rng)

    rtype = room.get("type")
    if rtype == "event":
        pending = {
            "id": room["id"],
            "title": room.get("title"),
            "intro": room.get("intro"),
            "actions": room.get("actions") or [],
            "outcomes": room.get("outcomes") or {},
        }

        def set_pending(u):
            u["dungeon_run"]["pending_event"] = pending
            u["dungeon_run"]["log"].append(f"✨ {pending['title']}")
            return {"ok": True, "kind": "await_choice", "event": pending,
                    "room_index": idx, "dungeon": dungeon["name"]}
        return data_store._mutate_user(player_id, set_pending)

    if rtype in ("combat", "boss"):
        result = _fight_room(player_id, dungeon, room, rng)
        if not result.get("ok"):
            return result
        cleared = result.get("won") or result.get("draw")
        if not cleared:
            # failed combat — kick out
            def fail(u):
                u["dungeon_run"]["log"].append(f"💀 Thua tại {room.get('title')}")
                u["dungeon_run"] = None
                return True
            data_store._mutate_user(player_id, fail)
            result["dungeon_failed"] = True
            result["message"] = "Bạn bị đánh bật khỏi dungeon."
            return result
        return _clear_room(player_id, dungeon, result)

    if rtype == "treasure":
        result = _treasure_room(player_id, room, rng)
        return _clear_room(player_id, dungeon, result)

    if rtype == "rest":
        result = _rest_room(player_id, room)
        return _clear_room(player_id, dungeon, result)

    return {"ok": False, "reason": "unknown_room"}


def _resolve_dungeon_event(player_id, dungeon, room, action_id, rng) -> dict:
    user = data_store.get_user(player_id)
    pending = user["dungeon_run"]["pending_event"]
    outcomes = (pending.get("outcomes") or {}).get(action_id) or []
    if not outcomes:
        return {"ok": False, "reason": "invalid_action"}

    weights = [max(0.0, float(o.get("chance", 1))) for o in outcomes]
    outcome = rng.choices(outcomes, weights=weights, k=1)[0]
    kind = outcome.get("kind")

    if kind == "abort":
        def abort(u):
            u["dungeon_run"] = None
            return {"ok": True, "kind": "abort", "log": outcome.get("log"),
                    "message": "Rời dungeon."}
        return data_store._mutate_user(player_id, abort)

    drops = adventure.grant_drops(player_id, outcome.get("drops") or [], rng=rng)
    effects = outcome.get("effects") or {}
    if effects:
        if "weapon_durability" in effects and user.get("weapon"):
            def wear(u):
                if u.get("weapon"):
                    u["weapon"]["durability"] = max(
                        0, u["weapon"]["durability"] + int(effects["weapon_durability"]))
                return True
            data_store._mutate_user(player_id, wear)
        data_store.apply_effects(player_id, {k: v for k, v in effects.items()
                                             if k in ("the_luc", "karma", "gold", "exp")})

    result = {
        "ok": True,
        "kind": "event_result",
        "title": pending.get("title"),
        "action_id": action_id,
        "log": outcome.get("log"),
        "drops": drops,
        "gold_delta": int(effects.get("gold", 0)),
        "outcome_kind": kind,
    }

    # continue to next room unless abort
    def clear_pending(u):
        u["dungeon_run"]["pending_event"] = None
        u["dungeon_run"]["log"].append(outcome.get("log") or "")
        return True
    data_store._mutate_user(player_id, clear_pending)

    if kind == "trap" and not outcome.get("continue", True):
        return result
    return _clear_room(player_id, dungeon, result)


def _clear_room(player_id: str, dungeon: dict, result: dict) -> dict:
    rooms = dungeon["rooms"]

    def do(u):
        run = u["dungeon_run"]
        run["rooms_cleared"] = run.get("rooms_cleared", 0) + 1
        run["room_index"] = run.get("room_index", 0) + 1
        run["pending_event"] = None
        run["log"].append(result.get("log") or result.get("title") or "Phòng hoàn thành")
        done = run["room_index"] >= len(rooms)
        return done

    done = data_store._mutate_user(player_id, do)
    result["room_cleared"] = True
    result["dungeon"] = dungeon["name"]
    if done:
        fin = _finish(player_id, cleared=True)
        result["dungeon_complete"] = True
        result["completion"] = fin
    else:
        user = data_store.get_user(player_id)
        idx = user["dungeon_run"]["room_index"]
        result["next_room"] = rooms[idx]
        result["progress"] = f"{idx}/{len(rooms)}"
    return result


def _finish(player_id: str, cleared: bool) -> dict:
    def do(u):
        run = u.get("dungeon_run") or {}
        cleared_n = run.get("rooms_cleared", 0)
        dungeon_id = run.get("dungeon_id")
        u["dungeon_run"] = None
        bonus = []
        if cleared:
            # completion stone
            stone = "enhance_stone_a"
            d = get_dungeon(dungeon_id) if dungeon_id else None
            if d and d.get("min_level", 1) >= 5:
                stone = "enhance_stone_b"
            item = data_store.instantiate_drop(stone, 1)
            if item:
                data_store._stack_into_bag(u, item)
                bonus.append(item)
        return {"ok": True, "cleared": cleared, "rooms_cleared": cleared_n,
                "bonus_drops": bonus,
                "message": "🏰 Hoàn thành dungeon!" if cleared else "Dungeon kết thúc."}
    return data_store._mutate_user(player_id, do)
