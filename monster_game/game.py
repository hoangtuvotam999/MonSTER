"""
High-level game API — port of createCharacter.js, math.js, and the
character/location/encounter/PvP-room logic that used to live in index.js
(minus every bit of Messenger-specific code: no attachments, no GIFs,
no api.sendMessage/handleReply).

Typical usage:

    from monster_game import game

    game.create_character("uid123", "Alice")
    game.equip_or_consume("uid123", 1)   # equip the starting sword (bag slot #1)
    game.set_location("uid123", 1)       # travel to the first location
    outcome = game.encounter_and_fight("uid123")
    print(outcome["won"], outcome.get("exp_gained"))
"""
from __future__ import annotations

import random
import time
from typing import Optional

from . import combat, data_store

STARTING_WEAPON_ID = 10

# Fallback used only if the item catalog has no entry for STARTING_WEAPON_ID.
DEFAULT_STARTING_WEAPON = {
    "type": "weapon",
    "id": STARTING_WEAPON_ID,
    "category": "Sword",
    "name": "Iron Sword I",
    "usage": 0,
    "exp": 0,
    "HP": 4000,
    "ATK": 210,
    "DEF": 210,
    "SPD": 2000,
    "durability": 100,
    "dmgBonus": 1,
    "defBonus": 1,
    "hpBonus": 1,
    "spdBonus": 1,
    "ArmorPiercing": 1,
    "price": 1000,
    "image": "https://i.imgur.com/JB2JAEm.png",
}


# --------------------------------------------------------------------------
# math.js — power/"lực chiến" formulas
# --------------------------------------------------------------------------

def power_basic(character: dict) -> float:
    """Character's own combat power, ignoring equipment."""
    return (character["hp"] + 4 * character["atk"]
            + 3 * character["def"] + 5 * character["spd"])


def power_total(character: dict) -> float:
    """Combat power including the equipped weapon's stats."""
    w = character["weapon"]
    return ((character["hp"] + w["HP"]) + 4 * (character["atk"] + w["ATK"])
             + 3 * (character["def"] + w["DEF"]) + 5 * (character["spd"] + w["SPD"]))


# --------------------------------------------------------------------------
# Character creation / lookup — port of createCharacter.js
# --------------------------------------------------------------------------

def create_character(player_id: str, name: str):
    """Returns the new character dict, or None if the player already has one."""
    if data_store.get_user(player_id) is not None:
        return None
    starting_weapon = data_store.get_items(STARTING_WEAPON_ID) or DEFAULT_STARTING_WEAPON
    data = {
        "id": player_id,
        "name": name,
        "level": 1,
        "exp": 0,
        "hp": 1000,
        "atk": 250,
        "def": 200,
        "spd": 100,
        "the_luc": 500,
        "karma": 0,
        "points": 0,
        "weapon": None,
        "locationID": None,
        "bag": [dict(starting_weapon)],
        "monster": [],
        "history": [],
        "created": int(time.time() * 1000),
    }
    return data_store.create_character(data)


def get_character(player_id: str) -> Optional[dict]:
    return data_store.get_user(player_id)


# --------------------------------------------------------------------------
# Status display helpers — port of getCharacter() in index.js
# --------------------------------------------------------------------------

_KARMA_MESSAGES = [
    (100, "Vãi lồn, game chưa đủ khó à, level quái +100"),
    (90, "Nghe lời tao, bú nhanh một chai nước thánh đi, level quái +90"),
    (80, "Hết cứu, level quái +80"),
    (70, "Vẫn đang giết thêm quái đấy à, level quái +70"),
    (60, "Mày có chắc là không bú nước thánh không đấy, level quái +60"),
    (50, "Á đù nguyên một quân đoàn ác quỷ sau lưng, level quái +50"),
    (40, "Mày còn không bú ngay một chai nước thánh là mày ăn cứt nhé em, level quái +40"),
    (30, "Những oan hồn đang gào rú, level quái +30"),
    (20, "Những vong hồn vất vưởng, level quái +20"),
    (10, "Những Linh hồn đang than khóc, level quái +10"),
]

_BAG_STATUS_THRESHOLDS = [(30, "🔴"), (20, "🟠"), (10, "🟡"), (1, "🟢")]


def karma_message(karma: int) -> str:
    for threshold, msg in _KARMA_MESSAGES:
        if karma >= threshold:
            return msg
    return ""


def karma_level_bonus(karma: int) -> int:
    """The karma-derived level bonus applied to spawned monsters."""
    for threshold in (100, 90, 80, 70, 60, 50, 40, 30, 20, 10):
        if karma >= threshold:
            return threshold
    return 0


def bag_status_icon(monster_count: int) -> str:
    for threshold, icon in _BAG_STATUS_THRESHOLDS:
        if monster_count >= threshold:
            return icon
    return ""


def character_summary(player_id: str) -> Optional[dict]:
    """A display-ready dict of computed character stats (no message text)."""
    c = get_character(player_id)
    if c is None:
        return None
    exp_needed = data_store.exp_needed_for(c["level"])
    return {
        "name": c["name"],
        "id": c["id"],
        "level": c["level"],
        "exp": round(c["exp"]),
        "exp_needed": exp_needed,
        "hp": c["hp"], "atk": c["atk"], "def": c["def"], "spd": c["spd"],
        "weapon_bonus": {
            "hp": c["weapon"]["HP"], "atk": c["weapon"]["ATK"],
            "def": c["weapon"]["DEF"], "spd": c["weapon"]["SPD"],
        } if c["weapon"] else None,
        "points": c["points"],
        "power_basic": power_basic(c),
        "power_total": power_total(c) if c["weapon"] else 0,
        "the_luc": c["the_luc"],
        "karma": c["karma"],
        "karma_message": karma_message(c["karma"]),
        "weapon_name": c["weapon"]["name"] if c["weapon"] else None,
        "weapon_durability": c["weapon"]["durability"] if c["weapon"] else None,
        "weapon_max_hp": data_store.weapon_max_hp(c["weapon"]) if c["weapon"] else None,
        "repair_cost": repair_cost(c["weapon"]) if c["weapon"] else None,
        "bag_count": len(c["bag"]),
        "monster_count": len(c["monster"]),
        "bag_status_icon": bag_status_icon(len(c["monster"])),
        "location_id": c["locationID"],
    }


# --------------------------------------------------------------------------
# Bag / equipment
# --------------------------------------------------------------------------

def equip_or_consume(player_id: str, bag_index_1based: int):
    """Port of setItem(): equip a weapon, or consume food/upgrade material
    at the given 1-based bag index. Returns the item consumed, or None."""
    c = get_character(player_id)
    if c is None:
        return None
    if not (1 <= bag_index_1based <= len(c["bag"])):
        return None
    item = c["bag"][bag_index_1based - 1]
    result = data_store.set_item(player_id, bag_index_1based - 1)
    if result is not data_store.OK:
        return None
    return item


POINT_MULTIPLIERS = {"hp": 5, "def": 2, "atk": 2, "spd": 1}


def spend_points(player_id: str, stat: str, points: int):
    """Port of increaseHp/Def/Atk/Spd. `stat` is one of 'hp','def','atk','spd'.
    Point costs mirror the original: 1pt = 5HP, 1pt = 2DEF, 1pt = 2ATK, 1pt = 1SPD.
    Returns the new stat value, or NOT_FOUND / FORBIDDEN."""
    if stat not in POINT_MULTIPLIERS or points <= 0:
        return data_store.FORBIDDEN
    return data_store.spend_points(player_id, stat, points, POINT_MULTIPLIERS[stat])


REPAIR_COST_RATIO = 0.5  # a from-zero repair costs half the weapon's price


def repair_cost(weapon: dict) -> int:
    """Cost to bring the weapon back to full durability *and* full HP,
    proportional to whichever of the two is more depleted."""
    durability_missing = 1 - weapon["durability"] / data_store.MAX_DURABILITY
    max_hp = data_store.weapon_max_hp(weapon)
    hp_missing = 1 - weapon["HP"] / max_hp if max_hp > 0 else 0
    wear = max(0.0, min(1.0, max(durability_missing, hp_missing)))
    if wear == 0:
        return 0
    return max(1, round(weapon.get("price", 0) * REPAIR_COST_RATIO * wear))


def repair_weapon(player_id: str, balance: int) -> dict:
    """Restore the equipped weapon's durability and HP to full.
    Returns {'ok', 'reason'?, 'cost', 'weapon'?}. The caller is responsible
    for actually deducting `cost` from the player's wallet.

    Added to make the game completable: durability drops by 10 per hunt and
    weapon HP never regenerates, and the original had no way to restore
    either — every weapon was scrap after at most 10 fights."""
    c = get_character(player_id)
    if c is None:
        return {"ok": False, "reason": "no_character", "cost": 0}
    w = c["weapon"]
    if w is None:
        return {"ok": False, "reason": "no_weapon", "cost": 0}
    cost = repair_cost(w)
    if cost == 0:
        return {"ok": False, "reason": "already_full", "cost": 0}
    if balance < cost:
        return {"ok": False, "reason": "not_enough_money", "cost": cost}
    weapon = data_store.repair_weapon(player_id)
    return {"ok": True, "cost": cost, "weapon": weapon}


# --------------------------------------------------------------------------
# Locations — port of listLocation()/setLocationID()
# --------------------------------------------------------------------------

def list_locations() -> list[dict]:
    return data_store.list_locations()


def set_location(player_id: str, location_index_1based: int):
    """Travel to the location at the given 1-based index of `list_locations()`.
    Returns the location dict, or None if the index or player is invalid."""
    locations = data_store.list_locations()
    idx = location_index_1based - 1
    if not (0 <= idx < len(locations)):
        return None
    location = locations[idx]
    if data_store.set_location(player_id, str(location["ID"])) is not data_store.OK:
        return None
    return location


# --------------------------------------------------------------------------
# Encounters — port of match() in index.js
# --------------------------------------------------------------------------

_TIER_TABLE = [  # (roll_upper_bound_exclusive, tier)
    (340, "I"), (540, "II"), (690, "III"), (790, "IV"), (840, "V"), (860, "X"), (861, "XX"),
]

_THREAT_TABLE = [  # (min_power, label) — checked from lowest to highest, last match wins
    (1, "1💀"), (4400, "2💀"), (8300, "3💀"), (28800, "4💀"), (80000, "5💀"),
    (140000, "6💀"), (275000, "7💀"), (400000, "8💀"), (590000, "9💀"), (800000, "10💀"),
    (1000000, "11💀"), (1200000, "12💀"), (1500000, "13💀"), (2000000, "14💀"),
    (2600000, "15💀"), (3920000, "16💀"), (4300000, "17💀"), (4900000, "18💀"),
    (5600000, "19💀"), (6000000, "20💀"), (7000000, "21💀"), (9000000, "23💀"),
    (11000000, "24💀"), (12500000, "25💀"), (25000000, "26💀"), (50000000, "27💀"),
    (60000000, "28💀"), (70000000, "29💀"), (85000000, "30💀"), (90000000, "30+💀"),
]

MIN_STAMINA_TO_FIGHT = 50
MAX_TROPHY_BAG_SIZE = 30


def threat_label(power: float) -> str:
    label = ""
    for min_power, lbl in _THREAT_TABLE:
        if power > min_power:
            label = lbl
    return label


def roll_tier() -> Optional[str]:
    roll = random.randint(0, 999)
    for upper, tier in _TIER_TABLE:
        if roll < upper:
            return tier
    return None  # no encounter this time (matches the original's ~13.9% miss chance)


def encounter_and_fight(player_id: str) -> dict:
    """Port of match(): pick a location monster, roll a level for it, fight,
    and apply all the resulting state changes (durability, karma, weapon
    breakage, EXP/level-up). Returns a dict describing the outcome instead
    of sending chat messages — render it however you like.
    """
    c = get_character(player_id)
    if c is None:
        return {"ok": False, "reason": "no_character"}
    if c["locationID"] is None:
        return {"ok": False, "reason": "no_location"}

    monsters = data_store.get_monsters(c["locationID"])
    if not monsters:
        return {"ok": False, "reason": "invalid_location"}
    if c["weapon"] is None:
        return {"ok": False, "reason": "no_weapon"}
    if c["weapon"]["durability"] <= 0:
        return {"ok": False, "reason": "weapon_broken"}
    location_level = data_store.get_location_level(c["locationID"])
    if c["level"] < location_level:
        return {"ok": False, "reason": "level_too_low", "required_level": location_level}
    if c["the_luc"] < MIN_STAMINA_TO_FIGHT:
        return {"ok": False, "reason": "no_stamina"}
    # FIXED vs. the original `>`: the bag could hold MAX + 1 trophies.
    if len(c["monster"]) >= MAX_TROPHY_BAG_SIZE:
        return {"ok": False, "reason": "bag_full"}

    tier = roll_tier()
    if tier is None:
        return {"ok": False, "reason": "no_encounter"}

    candidates = [m for m in monsters if m.get("Tier") == tier]
    if not candidates:
        return {"ok": False, "reason": "no_encounter"}
    monster_template = random.choice(candidates)

    min_level = data_store.get_min_level(c["locationID"])
    max_level = data_store.get_max_level(c["locationID"])
    karma_bonus = karma_level_bonus(c["karma"])
    # FIXED vs. the original `floor(random() * maxLevel + minLevel)`, which
    # rolled in [minLevel, minLevel + maxLevel) — i.e. a location declared
    # as levels 4–10 actually spawned levels 4–13. Now rolls [min, max].
    level = random.randint(min_level, max(min_level, max_level)) + karma_bonus

    growth = 1 + 0.2 * (level - 1)
    monster_hp = round(monster_template["HP"] * growth)
    monster_atk = round(monster_template["ATK"] * growth)
    monster_def = round(monster_template["DEF"] * growth)
    monster_spd = round(monster_template["SPD"] * growth)
    exp_reward = round(monster_template["exp"] * (1 + 0.15 * (level - 1)))

    base_power = (monster_template["HP"] + 4 * monster_template["ATK"]
                  + 3 * monster_template["DEF"] + 5 * monster_template["SPD"])

    player_stats = combat.build_combat_stats(c)
    monster_stats = {
        "HP": monster_hp,
        "ATK": monster_atk * monster_template["ATKbonus"],
        "DEF": monster_def * monster_template["DEFbonus"],
        "SPD": monster_spd * monster_template["SPDbonus"],
        # FIXED vs. the original: it did `Math.round(monster.ArmorPiercing)`,
        # which collapses any fractional armor-piercing value (e.g. 0.7,
        # meaning "30% mitigated") down to a bare 0 or 1 (meaning "fully
        # mitigated" or "fully ignored"). That made a monster's DEF either
        # matter 100% or 0%, discarding any nuance the catalog data intended.
        # The player's own weapon AP is used unrounded elsewhere
        # (combat.build_combat_stats), so monsters now match that for
        # consistency.
        "AP": monster_template["ArmorPiercing"],
        "Mana": 1,
    }
    result = combat.fight_monster(player_stats, monster_stats)

    durability = data_store.decrease_durability(player_id)
    data_store.karma_up(player_id)
    weapon_broken = data_store.decrease_health_weapon(player_id, result["playerPow"]["HP"]) is True
    if weapon_broken:
        durability = 0

    dmg_dealt = dmg_taken = 0
    for entry in result["log"]:
        if entry["attacker"] == "player":
            dmg_dealt += entry["damage"]
        else:
            dmg_taken += entry["damage"]

    outcome = {
        "ok": True,
        "won": result["winner"],
        "monster_name": monster_template["Name"],
        "monster_tier": tier,
        "monster_level": level,
        "monster_power": base_power,
        "monster_threat": threat_label(base_power),
        "turns": len(result["log"]),
        "player_damage_dealt": dmg_dealt,
        "player_damage_taken": dmg_taken,
        "weapon_durability": durability,
        "weapon_broken": weapon_broken,
        "exp_gained": 0,
        "events": [],
    }

    if result["winner"]:
        trophy = dict(monster_template)
        trophy["level"] = level
        data_store.add_monster(player_id, trophy)
        level_events = data_store.set_exp(player_id, exp_reward)
        outcome["exp_gained"] = exp_reward
        outcome["events"] = level_events if isinstance(level_events, list) else []
    return outcome


# --------------------------------------------------------------------------
# PvP rooms — port of the pvp()/pvp.room() logic in index.js
#
# Original kept per-thread room lists in a module-level `pvp_rooms` object
# keyed by Messenger threadID. We generalize "threadID" to a plain
# `channel_id` string so it works with any chat platform (or none at all).
# --------------------------------------------------------------------------

STATUS_LABELS = {
    1: "⚠️ Phòng đang chờ người chơi thứ 2",
    2: "🕹️ Phòng đã đủ người, chờ sẵn sàng để bắt đầu",
    3: "🔄 Trận đấu đang diễn ra",
}
# Original config.json's plain-text equivalents (status_room), kept for
# reference if you want to match the original bot's wording exactly:
# {"1": "thieu nguoi", "2": "du nguoi", "3": "dang danh nhau"}

_pvp_rooms: dict[str, list[dict]] = {}


def _rooms(channel_id: str) -> list[dict]:
    return _pvp_rooms.setdefault(channel_id, [])


def list_rooms(channel_id: str) -> list[dict]:
    return _rooms(channel_id)


def find_room(channel_id: str, player_id: str) -> Optional[dict]:
    return next((r for r in _rooms(channel_id) if player_id in r["players"]), None)


def _has_usable_weapon(c: Optional[dict]) -> bool:
    return c is not None and c["weapon"] is not None and c["weapon"]["durability"] > 0


def create_room(channel_id: str, player_id: str, title: str = "") -> Optional[dict]:
    """Returns the new room, or None if the player is already in one, or
    doesn't have a character/usable weapon (mirrors the original's guards)."""
    if not _has_usable_weapon(get_character(player_id)):
        return None
    if find_room(channel_id, player_id) is not None:
        return None
    rooms = _rooms(channel_id)
    room = {
        "stt": len(rooms) + 1,
        "title": title or f"Phòng {len(rooms) + 1}",
        "players": [player_id],
        "status": 1,
        "ready": False,
    }
    rooms.append(room)
    return room


def join_room(channel_id: str, player_id: str, room_number_1based: int) -> Optional[dict]:
    if not _has_usable_weapon(get_character(player_id)):
        return None
    rooms = _rooms(channel_id)
    if not (1 <= room_number_1based <= len(rooms)):
        return None
    room = rooms[room_number_1based - 1]
    if (player_id in room["players"] or room["status"] != 1
            or len(room["players"]) >= 2 or find_room(channel_id, player_id) is not None):
        return None
    room["players"].append(player_id)
    room["status"] = 2
    room["ready"] = False
    return room


def _renumber(rooms: list[dict]) -> None:
    for i, room in enumerate(rooms, start=1):
        room["stt"] = i


def leave_room(channel_id: str, player_id: str) -> bool:
    rooms = _rooms(channel_id)
    room = find_room(channel_id, player_id)
    if room is None or room["status"] == 3:
        return False
    if player_id == room["players"][0]:
        rooms.remove(room)
        _renumber(rooms)
    else:
        room["players"].remove(player_id)
        room["status"] = 1
        room["ready"] = False
    return True


def set_ready(channel_id: str, player_id: str) -> Optional[bool]:
    """Only the challenger (players[1]) can toggle ready. Returns new ready
    state, or None if not applicable."""
    room = find_room(channel_id, player_id)
    if room is None or room["status"] == 3 or len(room["players"]) < 2:
        return None
    if player_id != room["players"][1]:
        return None
    room["ready"] = not room["ready"]
    return room["ready"]


def start_match(channel_id: str, player_id: str) -> Optional[dict]:
    """Only the room owner (players[0]) can start, and only once the
    opponent is ready. Runs the PvP fight and returns a result summary."""
    room = find_room(channel_id, player_id)
    if room is None or room["status"] == 3:
        return None
    if player_id != room["players"][0]:
        return None
    if room["status"] == 1 or not room.get("ready"):
        return None

    p1_id, p2_id = room["players"]
    char1, char2 = get_character(p1_id), get_character(p2_id)
    # A player's weapon may have broken in a hunt since they joined.
    if not (_has_usable_weapon(char1) and _has_usable_weapon(char2)):
        room["ready"] = False
        return None

    room["status"] = 3
    result = combat.fight_pvp(char1, char2)

    dmg = {"player1": 0, "player2": 0}
    for entry in result["log"]:
        dmg[entry["attacker"]] += entry["damage"]

    winner_id = p1_id if result["winner"] == "player1" else p2_id
    outcome = {
        "winner_id": winner_id,
        "rounds": len(result["log"]),
        "player1_id": p1_id, "player2_id": p2_id,
        "player1_damage": dmg["player1"], "player2_damage": dmg["player2"],
    }
    room["status"] = 2
    room["ready"] = False
    return outcome
