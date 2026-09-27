"""
Party / tổ đội — up to 4 hunters share hunts & dungeons.

State is per-channel (same pattern as PvP rooms). A player may only be in
one party at a time. Leader sets destination; party hunt uses a shared
monster HP pool (members attack in join order until the monster falls or
everyone is down).
"""
from __future__ import annotations

import random
import time
from typing import Optional

from . import adventure, combat, data_store, dungeon as dungeon_mod, equipment as equip_mod, journey
from . import game as game_mod

MAX_PARTY_SIZE = 4


def _even_shares(total: int, n: int) -> list[int]:
    """Split `total` into n integer parts that sum back to total."""
    if n <= 0 or total <= 0:
        return []
    base = total // n
    shares = [base] * n
    shares[-1] += total - base * n
    return shares

_parties: dict[str, list[dict]] = {}


def _channel_parties(channel_id: str) -> list[dict]:
    return _parties.setdefault(channel_id, [])


def clear_all() -> None:
    _parties.clear()


def list_parties(channel_id: str) -> list[dict]:
    return list(_channel_parties(channel_id))


def find_party(channel_id: str, player_id: str) -> Optional[dict]:
    return next((p for p in _channel_parties(channel_id) if player_id in p["members"]), None)


def find_party_by_stt(channel_id: str, stt_1based: int) -> Optional[dict]:
    parties = _channel_parties(channel_id)
    if not (1 <= stt_1based <= len(parties)):
        return None
    return parties[stt_1based - 1]


def _renumber(channel_id: str) -> None:
    for i, p in enumerate(_channel_parties(channel_id), start=1):
        p["stt"] = i


def _usable(player_id: str) -> bool:
    c = game_mod.get_character(player_id)
    return c is not None and c.get("weapon") is not None and c["weapon"].get("durability", 0) > 0


def create_party(channel_id: str, leader_id: str, title: str = "") -> dict:
    if not _usable(leader_id):
        return {"ok": False, "reason": "no_weapon"}
    if find_party(channel_id, leader_id):
        return {"ok": False, "reason": "already_in_party"}
    parties = _channel_parties(channel_id)
    party = {
        "stt": len(parties) + 1,
        "title": title or f"Tổ đội {len(parties) + 1}",
        "leader": leader_id,
        "members": [leader_id],
        "max_size": MAX_PARTY_SIZE,
        "location_index": None,
        "dungeon_run": None,
        "created": int(time.time() * 1000),
    }
    parties.append(party)
    return {"ok": True, "party": party}


def join_party(channel_id: str, player_id: str, stt_1based: int) -> dict:
    if not _usable(player_id):
        return {"ok": False, "reason": "no_weapon"}
    if find_party(channel_id, player_id):
        return {"ok": False, "reason": "already_in_party"}
    party = find_party_by_stt(channel_id, stt_1based)
    if party is None:
        return {"ok": False, "reason": "no_party"}
    if party.get("dungeon_run"):
        return {"ok": False, "reason": "busy_dungeon"}
    if len(party["members"]) >= party.get("max_size", MAX_PARTY_SIZE):
        return {"ok": False, "reason": "full"}
    party["members"].append(player_id)
    return {"ok": True, "party": party}


def leave_party(channel_id: str, player_id: str) -> dict:
    parties = _channel_parties(channel_id)
    party = find_party(channel_id, player_id)
    if party is None:
        return {"ok": False, "reason": "not_in_party"}
    if party.get("dungeon_run"):
        return {"ok": False, "reason": "busy_dungeon"}
    if player_id == party["leader"]:
        # promote next member or disband
        party["members"].remove(player_id)
        if not party["members"]:
            parties.remove(party)
            _renumber(channel_id)
            return {"ok": True, "disbanded": True, "message": "Tổ đội giải tán."}
        party["leader"] = party["members"][0]
        _renumber(channel_id)
        return {"ok": True, "promoted": party["leader"], "party": party}
    party["members"].remove(player_id)
    return {"ok": True, "party": party}


def kick_member(channel_id: str, leader_id: str, target_id: str) -> dict:
    party = find_party(channel_id, leader_id)
    if party is None or party["leader"] != leader_id:
        return {"ok": False, "reason": "not_leader"}
    if target_id == leader_id or target_id not in party["members"]:
        return {"ok": False, "reason": "invalid_target"}
    if party.get("dungeon_run"):
        return {"ok": False, "reason": "busy_dungeon"}
    party["members"].remove(target_id)
    return {"ok": True, "party": party}


def disband_party(channel_id: str, leader_id: str) -> dict:
    parties = _channel_parties(channel_id)
    party = find_party(channel_id, leader_id)
    if party is None or party["leader"] != leader_id:
        return {"ok": False, "reason": "not_leader"}
    if party.get("dungeon_run"):
        return {"ok": False, "reason": "busy_dungeon"}
    parties.remove(party)
    _renumber(channel_id)
    return {"ok": True, "disbanded": True}


def set_party_location(channel_id: str, leader_id: str, location_index_1based: int) -> dict:
    party = find_party(channel_id, leader_id)
    if party is None or party["leader"] != leader_id:
        return {"ok": False, "reason": "not_leader"}
    locs = data_store.list_locations()
    idx = location_index_1based - 1
    if not (0 <= idx < len(locs)):
        return {"ok": False, "reason": "bad_location"}
    party["location_index"] = location_index_1based
    loc = locs[idx]
    # sync all members' locationID
    for mid in party["members"]:
        data_store.set_location(mid, str(loc["ID"]))
    return {"ok": True, "location": loc, "party": party}


def _top_up_light(player_id: str) -> None:
    def mut(u):
        if u.get("the_luc", 0) < 80:
            u["the_luc"] = 80
        return True
    data_store._mutate_user(player_id, mut)


def party_hunt(channel_id: str, starter_id: str, rng: Optional[random.Random] = None) -> dict:
    """
    Cooperative hunt: one monster, shared HP, members attack in join order.
    Rewards (EXP/drops/trophy) split — each living contributor gets full drop
    roll chance and shared exp based on contribution turns.
    """
    rng = rng or random.Random()
    party = find_party(channel_id, starter_id)
    if party is None:
        return {"ok": False, "reason": "not_in_party"}
    if party.get("dungeon_run"):
        return {"ok": False, "reason": "busy_dungeon"}
    if starter_id != party["leader"] and starter_id not in party["members"]:
        return {"ok": False, "reason": "not_in_party"}

    if party.get("location_index") is None:
        # inherit leader location if set
        leader = game_mod.get_character(party["leader"])
        if leader and leader.get("locationID") is not None:
            locs = data_store.list_locations()
            for i, loc in enumerate(locs, 1):
                if str(loc["ID"]) == str(leader["locationID"]):
                    party["location_index"] = i
                    break
    if party.get("location_index") is None:
        return {"ok": False, "reason": "no_location"}

    # ensure everyone is on the party map
    locs = data_store.list_locations()
    loc = locs[party["location_index"] - 1]
    for mid in party["members"]:
        data_store.set_location(mid, str(loc["ID"]))

    members = []
    for mid in party["members"]:
        game_mod.ensure_potion_kit(mid)
        c = game_mod.get_character(mid)
        if c is None or not c.get("weapon") or c["weapon"].get("durability", 0) <= 0:
            continue
        if c.get("the_luc", 0) < game_mod.MIN_STAMINA_TO_FIGHT:
            continue
        members.append(mid)
    if not members:
        return {"ok": False, "reason": "no_ready_members"}

    # encounter roll from leader perspective
    tier = game_mod.roll_tier()
    if tier is None:
        return {"ok": False, "reason": "no_encounter"}
    monsters = data_store.get_monsters(loc["ID"]) or []
    candidates = [m for m in monsters if m.get("Tier") == tier]
    if not candidates:
        return {"ok": False, "reason": "no_encounter"}
    template = rng.choice(candidates)

    # scale by average party level + karma of leader
    avg_lv = max(1, round(sum(game_mod.get_character(m)["level"] for m in members) / len(members)))
    leader_c = game_mod.get_character(party["leader"])
    karma_bonus = game_mod.karma_level_bonus(leader_c.get("karma", 0) if leader_c else 0)
    min_l = data_store.get_min_level(loc["ID"]) or 1
    max_l = data_store.get_max_level(loc["ID"]) or min_l
    mlevel = rng.randint(min_l, max(min_l, max_l)) + karma_bonus
    # party size scales monster HP slightly
    growth = 1 + 0.2 * (mlevel - 1)
    size_factor = 1 + 0.25 * (len(members) - 1)
    mhp = round(template["HP"] * growth * size_factor)
    monster_stats = {
        "HP": mhp,
        "ATK": round(template["ATK"] * growth) * template.get("ATKbonus", 1),
        "DEF": round(template["DEF"] * growth) * template.get("DEFbonus", 1),
        "SPD": round(template["SPD"] * growth) * template.get("SPDbonus", 1),
        "AP": template.get("ArmorPiercing", 1),
        "Mana": 1,
        "maxHP": mhp,
    }
    monster_live = dict(monster_stats)

    segments = []
    contributors = []
    won = False
    for mid in members:
        if monster_live["HP"] <= 0:
            break
        c = game_mod.get_character(mid)
        equip_mod.ensure_loadout(c)
        belt = [dict(x) if x else None for x in c.get("consumables") or []]
        pstats = combat.build_combat_stats(c)
        # fight against remaining monster HP
        result = combat.fight_monster(
            pstats, monster_live,
            monster_actions=template.get("actions") or [],
            player_belt=belt,
            weapon_category=c["weapon"].get("category") or "",
            weapon=c["weapon"],
            rng=rng,
        )
        # carry remaining monster HP/stats to next member
        if result.get("monsterPow"):
            for k in ("HP", "ATK", "DEF", "SPD", "AP", "Mana", "maxHP"):
                if k in result["monsterPow"]:
                    monster_live[k] = result["monsterPow"][k]

        def after(u, belt_out=result.get("belt")):
            equip_mod.ensure_loadout(u)
            if belt_out is not None:
                u["consumables"] = belt_out
            if u.get("weapon"):
                u["weapon"]["durability"] = max(0, u["weapon"]["durability"] - 5)
            u["the_luc"] = max(0, u.get("the_luc", 0) - 40)
            return True
        data_store._mutate_user(mid, after)

        dealt = sum(e["damage"] for e in result["log"] if e["attacker"] == "player")
        taken = sum(e["damage"] for e in result["log"] if e["attacker"] != "player")
        segments.append({
            "player_id": mid,
            "player_name": c["name"],
            "weapon_name": c["weapon"]["name"],
            "dealt": dealt,
            "taken": taken,
            "survived": result["playerPow"]["HP"] > 0,
            "monster_hp_left": max(0, monster_live["HP"]),
            "log": result["log"],
            "player_stats": dict(result["playerPow"]),
        })
        contributors.append(mid)
        if monster_live["HP"] <= 0:
            won = True
            break

    overlevel = avg_lv < int(loc.get("level") or 1)
    exp_base = round(template.get("exp", 50) * (1 + 0.15 * (mlevel - 1)))
    if overlevel:
        exp_base = round(exp_base * 1.25)
    # Equal split across everyone who was ready — total stays 100% of the reward
    payout = members if won else []
    shares = _even_shares(exp_base, len(payout))
    rewards = []
    if won:
        for mid, exp_gain in zip(payout, shares):
            events = data_store.set_exp(mid, exp_gain)
            trophy = dict(template)
            trophy["level"] = mlevel
            data_store.add_monster(mid, trophy)
            drops = adventure.roll_monster_drops(mid, template, rng=rng)
            if not isinstance(events, list):
                events = []
            data_store.karma_up(mid, data_store.KARMA_ON_WIN)
            rewards.append({
                "player_id": mid,
                "player_name": game_mod.get_character(mid)["name"],
                "exp": exp_gain,
                "events": events,
                "drops": drops,
            })

    daily_notes = []
    for mid in contributors:
        note = game_mod.bump_daily(mid, "hunt")
        if note:
            who = (game_mod.get_character(mid) or {}).get("name") or mid
            daily_notes.append(f"{who}: {note}" if len(contributors) > 1 else note)

    trail = journey.play(members, loc, mode="party", rng=rng)
    word = "thắng" if won else "thua"
    for mid in members:
        mine = next((r for r in rewards if r["player_id"] == mid), None)
        lines = [
            f"👥 {party['title']}",
            f"📍 {loc.get('name', '')}",
            f"{template['Name']} Tier {tier} Lv.{mlevel} — {word}",
        ]
        if mine:
            lines.append(f"✨ +{mine['exp']} EXP")
            for drop in mine.get("drops") or []:
                lines.append(f"🎁 {drop['name']} ×{drop.get('qty', 1)}")
        lines.extend(trail.get("lines") or [])
        data_store.append_history(mid, {
            "ts": int(time.time() * 1000),
            "kind": "party_hunt",
            "location": loc.get("name"),
            "won": won,
            "monster": template["Name"],
            "tier": tier,
            "lines": lines,
        })

    return {
        "ok": True,
        "won": won,
        "party_title": party["title"],
        "location_name": loc.get("name"),
        "overlevel": overlevel,
        "monster_name": template["Name"],
        "monster_tier": tier,
        "monster_level": mlevel,
        "monster_max_hp": mhp,
        "monster_hp_left": max(0, int(monster_live["HP"])),
        "members": members,
        "segments": segments,
        "rewards": rewards,
        "journey": trail,
        "size_factor": size_factor,
        "daily_notes": daily_notes,
    }


def party_start_dungeon(channel_id: str, leader_id: str, dungeon_id: str) -> dict:
    party = find_party(channel_id, leader_id)
    if party is None or party["leader"] != leader_id:
        return {"ok": False, "reason": "not_leader"}
    if party.get("dungeon_run"):
        return {"ok": False, "reason": "already_in_dungeon"}
    # use leader's character to start; store shared run on party
    # temporarily clear personal runs
    for mid in party["members"]:
        def clear(u):
            u["dungeon_run"] = None
            return True
        data_store._mutate_user(mid, clear)
    dungeon = dungeon_mod.get_dungeon(dungeon_id)
    cost = int((dungeon or {}).get("stamina_cost", 50))
    for mid in party["members"]:
        if mid == leader_id:
            continue
        c = game_mod.get_character(mid)
        if c is None or c.get("the_luc", 0) < cost:
            return {"ok": False, "reason": "no_stamina", "player_id": mid}
        if c["level"] < int((dungeon or {}).get("min_level", 1)):
            return {"ok": False, "reason": "level_too_low", "required_level": dungeon["min_level"],
                    "player_id": mid}

    start = dungeon_mod.start_dungeon(leader_id, dungeon_id)
    if not start.get("ok"):
        return start
    for mid in party["members"]:
        if mid == leader_id:
            continue

        def pay(u, amount=cost):
            u["the_luc"] = max(0, u.get("the_luc", 0) - amount)
            return True
        data_store._mutate_user(mid, pay)
    # move run onto party and clear leader personal (keep progress on party)
    leader = game_mod.get_character(leader_id)

    def steal(u):
        run = u.get("dungeon_run")
        u["dungeon_run"] = None
        return run

    run = data_store._mutate_user(leader_id, steal)
    party["dungeon_run"] = run
    party["dungeon_id"] = dungeon_id
    # stamp members so get_character can show party dungeon
    for mid in party["members"]:
        def stamp(u, r=dict(run)):
            u["dungeon_run"] = {**r, "party": True, "party_title": party["title"]}
            return True
        data_store._mutate_user(mid, stamp)
    return {"ok": True, "dungeon": start.get("dungeon"), "party": party["title"],
            "stamina_cost": start.get("stamina_cost"), "room": start.get("room")}


def _ready_members(party: dict) -> list[str]:
    ready = []
    for mid in party["members"]:
        c = game_mod.get_character(mid)
        if c and c.get("weapon") and c["weapon"].get("durability", 0) > 0 and c.get("the_luc", 0) >= 40:
            ready.append(mid)
    return ready


def _party_room_combat(party: dict, player_id: str, dungeon: dict, room: dict, rng: random.Random) -> dict:
    """Shared-HP room fight. EXP is split evenly; each ready member rolls loot."""
    leader = game_mod.get_character(party["leader"]) or game_mod.get_character(player_id)
    template = dungeon_mod._pick_monster(dungeon, room, leader["level"], leader.get("karma", 0))
    if template is None:
        return {"ok": False, "reason": "no_monster"}
    members = _ready_members(party) or [party["leader"]]
    level = max(leader["level"], data_store.get_min_level(dungeon.get("map_ref", 0)) or 1)
    growth = 1 + 0.15 * (level - 1)
    size_factor = 1 + 0.25 * (len(members) - 1)
    mhp = round(template["HP"] * growth * size_factor)
    monster_live = {
        "HP": mhp,
        "ATK": round(template["ATK"] * growth) * template.get("ATKbonus", 1),
        "DEF": round(template["DEF"] * growth) * template.get("DEFbonus", 1),
        "SPD": round(template["SPD"] * growth) * template.get("SPDbonus", 1),
        "AP": template.get("ArmorPiercing", 1),
        "Mana": 1,
        "maxHP": mhp,
    }
    segments = []
    won = False
    for mid in members:
        if monster_live["HP"] <= 0:
            won = True
            break
        c = game_mod.get_character(mid)
        equip_mod.ensure_loadout(c)
        belt = [dict(x) if x else None for x in c.get("consumables") or []]
        pstats = combat.build_combat_stats(c)
        result = combat.fight_monster(
            pstats, monster_live,
            monster_actions=template.get("actions") or [],
            player_belt=belt,
            weapon_category=c["weapon"].get("category") or "",
            weapon=c["weapon"],
            rng=rng,
        )
        if result.get("monsterPow"):
            for k in ("HP", "ATK", "DEF", "SPD", "AP", "Mana", "maxHP"):
                if k in result["monsterPow"]:
                    monster_live[k] = result["monsterPow"][k]

        def after(u, belt_out=result.get("belt")):
            equip_mod.ensure_loadout(u)
            if belt_out is not None:
                u["consumables"] = belt_out
            if u.get("weapon"):
                u["weapon"]["durability"] = max(0, u["weapon"]["durability"] - 5)
            u["the_luc"] = max(0, u.get("the_luc", 0) - 40)
            return True
        data_store._mutate_user(mid, after)
        segments.append({
            "player_name": c["name"],
            "dealt": sum(e["damage"] for e in result["log"] if e["attacker"] == "player"),
            "monster_hp_left": max(0, monster_live["HP"]),
        })
        if monster_live["HP"] <= 0:
            won = True
            break

    drops = []
    exp_each = 0
    rewards = []
    if won:
        exp_total = round(template.get("exp", 50) * (1.2 if room.get("type") == "boss" else 1.0))
        shares = _even_shares(exp_total, len(members))
        for mid, share in zip(members, shares):
            data_store.set_exp(mid, share)
            trophy = dict(template)
            trophy["level"] = level
            data_store.add_monster(mid, trophy)
            mine = adventure.roll_monster_drops(mid, template, rng=rng)
            for spec in room.get("bonus_drops") or []:
                mine.extend(adventure.grant_drops(mid, [spec], rng=rng))
            data_store.karma_up(mid, data_store.KARMA_ON_WIN)
            rewards.append({"player_id": mid, "player_name": game_mod.get_character(mid)["name"],
                            "exp": share, "drops": mine})
            if mid == party["leader"]:
                drops = mine
                exp_each = share
        if not drops and rewards:
            drops = rewards[0]["drops"]
            exp_each = rewards[0]["exp"]

    leader_c = game_mod.get_character(party["leader"])
    return {
        "ok": True,
        "kind": "combat",
        "won": won,
        "draw": False,
        "monster_name": template["Name"],
        "monster_tier": template.get("Tier"),
        "log": f"👥 {len(segments)} người giao tranh · quái còn {max(0, int(monster_live['HP']))} HP",
        "player_stats": {},
        "monster_stats": monster_live,
        "drops": drops,
        "exp_gained": exp_each,
        "flavor": room.get("flavor"),
        "title": room.get("title"),
        "weapon_name": leader_c["weapon"]["name"] if leader_c and leader_c.get("weapon") else "",
        "weapon_category": (leader_c or {}).get("weapon", {}).get("category") if leader_c else "",
        "player_name": leader_c["name"] if leader_c else party["leader"],
        "party_segments": segments,
        "party_rewards": rewards,
    }


def _copy_drops(party: dict, leader_id: str, drops: list) -> None:
    for mid in party["members"]:
        if mid == leader_id:
            continue
        for drop in drops or []:
            data_store.add_to_bag(mid, dict(drop))


def party_advance_dungeon(channel_id: str, actor_id: str, action_id: Optional[str] = None,
                          rng: Optional[random.Random] = None) -> dict:
    party = find_party(channel_id, actor_id)
    if party is None or not party.get("dungeon_run"):
        return {"ok": False, "reason": "not_in_dungeon"}
    if actor_id != party["leader"]:
        return {"ok": False, "reason": "not_leader"}
    run = party["dungeon_run"]

    def put(u, r=dict(run)):
        u["dungeon_run"] = r
        return True
    data_store._mutate_user(party["leader"], put)

    def combat_fn(pid, dungeon, room, fight_rng, party_ref=party):
        return _party_room_combat(party_ref, pid, dungeon, room, fight_rng)

    result = dungeon_mod.advance_dungeon(
        party["leader"], action_id=action_id, rng=rng, combat_fn=combat_fn,
    )
    leader = game_mod.get_character(party["leader"])
    new_run = leader.get("dungeon_run") if leader else None
    party["dungeon_run"] = new_run
    for mid in party["members"]:
        def sync(u, r=dict(new_run) if new_run else None):
            u["dungeon_run"] = ({**r, "party": True, "party_title": party["title"]} if r else None)
            return True
        data_store._mutate_user(mid, sync)
    # Non-combat loot was granted only to the leader — copy it to the rest
    if result.get("ok") and not result.get("party_rewards"):
        _copy_drops(party, party["leader"], result.get("drops") or [])
        gold = int(result.get("gold_delta") or 0)
        if gold:
            share = _even_shares(gold, len(party["members"]))
            result["gold_shares"] = {
                mid: amt for mid, amt in zip(party["members"], share)
            }
            result["gold_delta"] = share[0] if share else 0
    result["party_title"] = party["title"]
    result["party_members"] = list(party["members"])
    if result.get("dungeon_failed"):
        for mid in party["members"]:
            def clear(u):
                u["dungeon_run"] = None
                return True
            data_store._mutate_user(mid, clear)
        party["dungeon_run"] = None
        party.pop("dungeon_id", None)
    if result.get("dungeon_complete") or result.get("kind") == "abort":
        party["dungeon_run"] = None
        party.pop("dungeon_id", None)
    return result


def party_abandon_dungeon(channel_id: str, leader_id: str) -> dict:
    party = find_party(channel_id, leader_id)
    if party is None or party["leader"] != leader_id:
        return {"ok": False, "reason": "not_leader"}
    if not party.get("dungeon_run"):
        return {"ok": False, "reason": "not_in_dungeon"}
    for mid in party["members"]:
        def clear(u):
            u["dungeon_run"] = None
            return True
        data_store._mutate_user(mid, clear)
    party["dungeon_run"] = None
    party.pop("dungeon_id", None)
    return {"ok": True, "message": "Tổ đội rút khỏi dungeon."}
