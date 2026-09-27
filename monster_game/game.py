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

from . import adventure, combat, data_store, equipment as equip_mod, journey

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
    """Combat power including weapon + equipment."""
    equip_mod.ensure_loadout(character)
    w = character["weapon"] or {"HP": 0, "ATK": 0, "DEF": 0, "SPD": 0}
    gear = equip_mod.equipment_bonuses(character)
    return ((character["hp"] + w.get("HP", 0) + gear["hp"])
            + 4 * (character["atk"] + w.get("ATK", 0) + gear["atk"])
            + 3 * (character["def"] + w.get("DEF", 0) + gear["def"])
            + 5 * (character["spd"] + w.get("SPD", 0) + gear["spd"]))


# --------------------------------------------------------------------------
# Character creation / lookup — port of createCharacter.js
# --------------------------------------------------------------------------

def create_character(player_id: str, name: str):
    """Returns the new character dict, or None if the player already has one."""
    if data_store.get_user(player_id) is not None:
        return None
    starting_weapon = data_store.get_items(STARTING_WEAPON_ID) or DEFAULT_STARTING_WEAPON
    # Starter kit: cloth gear + small potion on belt
    starter_helm = data_store.get_equipment_by_id("helm_leather")
    starter_potion = data_store.get_consumable("potion_s")
    bag = [dict(starting_weapon)]
    if starter_helm:
        bag.append(dict(starter_helm))
    belt = equip_mod.empty_belt()
    if starter_potion:
        belt[0] = {**dict(starter_potion), "qty": 3}
    candy = data_store.get_consumable("candy")
    if candy:
        bag.append({**dict(candy), "qty": 2})
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
        "gold": 2500,
        "weapon": None,
        "equipment": equip_mod.empty_equipment(),
        "consumables": belt,
        "locationID": None,
        "bag": bag,
        "monster": [],
        "history": [],
        "pending_event": None,
        "dungeon_run": None,
        "potion_kit": True,
        "created": int(time.time() * 1000),
    }
    # Starter items start at +0 enhance
    for it in bag:
        it.setdefault("enhance_level", 0)
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


def ensure_potion_kit(player_id: str) -> None:
    """One-time: hunters created before potions existed get a small stack."""
    existing = data_store.get_user(player_id)
    if existing is None or existing.get("potion_kit"):
        return

    def mut(user):
        if user.get("potion_kit"):
            return False
        equip_mod.ensure_loadout(user)

        def heal_qty(item):
            if not item or item.get("subtype") != "heal":
                return 0
            return int(item.get("qty", 1))

        total = sum(heal_qty(it) for it in user["consumables"])
        total += sum(heal_qty(it) for it in user.get("bag") or [])
        if total <= 0:
            potion = data_store.get_consumable("potion_s")
            if potion:
                equip_mod.stow_stack_on_belt(user, {**dict(potion), "qty": 3})
            candy = data_store.get_consumable("candy")
            if candy and not any(it.get("id") == "candy" for it in user.get("bag") or []):
                data_store._stack_into_bag(user, {**dict(candy), "qty": 2})
        user["potion_kit"] = True
        return True

    data_store._mutate_user(player_id, mut)


def character_summary(player_id: str) -> Optional[dict]:
    """A display-ready dict of computed character stats (no message text)."""
    ensure_potion_kit(player_id)
    c = get_character(player_id)
    if c is None:
        return None
    equip_mod.ensure_loadout(c)
    gear = equip_mod.equipment_bonuses(c)
    exp_needed = data_store.exp_needed_for(c["level"])
    location = data_store.find_location(c["locationID"]) if c["locationID"] is not None else None
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
        "gear_bonus": {
            "hp": gear["hp"], "atk": gear["atk"], "def": gear["def"], "spd": gear["spd"],
            "sets": gear["sets"], "tags": sorted(set(gear["tags"])),
        },
        "equipment": c["equipment"],
        "consumables": c["consumables"],
        "points": c["points"],
        "power_basic": power_basic(c),
        "power_total": power_total(c) if c["weapon"] else power_basic(c) + gear["hp"] + 4*gear["atk"] + 3*gear["def"] + 5*gear["spd"],
        "the_luc": c["the_luc"],
        "karma": c["karma"],
        "karma_message": karma_message(c["karma"]),
        "weapon_name": c["weapon"]["name"] if c["weapon"] else None,
        "weapon_category": c["weapon"].get("category") if c["weapon"] else None,
        "weapon_level": c["weapon"].get("usage", 0) if c["weapon"] else None,
        "weapon_enhance": int(c["weapon"].get("enhance_level") or 0) if c["weapon"] else None,
        "weapon_durability": c["weapon"]["durability"] if c["weapon"] else None,
        "weapon_hp": c["weapon"]["HP"] if c["weapon"] else None,
        "weapon_max_hp": data_store.weapon_max_hp(c["weapon"]) if c["weapon"] else None,
        "repair_cost": repair_cost(c["weapon"]) if c["weapon"] else None,
        "bag_count": len(c["bag"]),
        "monster_count": len(c["monster"]),
        "trophy_value": sum(m.get("price", 0) for m in c["monster"]),
        "bag_status_icon": bag_status_icon(len(c["monster"])),
        "location_id": c["locationID"],
        "location_name": location["name"] if location else None,
        "dungeon_run": c.get("dungeon_run"),
        "battle": _battle_stats(c),
    }


def _battle_stats(character: dict) -> Optional[dict]:
    """Stats actually used in a fight: body + weapon + armor, after multipliers."""
    if not character.get("weapon"):
        return None
    built = combat.build_combat_stats(character)
    return {key: round(built[key]) for key in ("HP", "ATK", "DEF", "SPD")}


# --------------------------------------------------------------------------
# Bag / equipment
# --------------------------------------------------------------------------

REST_HEAL = 150
REST_CAP = 500
REST_PER_DAY = 3
TASKS = (
    ("sell", "Bán xác quái một lần", 150),
    ("craft", "Chế một món", 200),
    ("dungeon", "Vào một dungeon", 250),
)


def task_lines(player_id: str) -> list[str]:
    user = get_character(player_id) or {}
    flags = user.get("tasks") or {}
    lines = []
    for task_id, text, gold in TASKS:
        if flags.get(task_id):
            lines.append(f"✓ {text}")
        else:
            lines.append(f"○ {text} · +{gold} vàng")
    return lines


DAILIES = (
    ("hunt", "Săn", 3, 300),
    ("sell", "Bán xác", 1, 150),
    ("rest", "Nghỉ", 1, 120),
)


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def _fresh_daily(today: str) -> dict:
    return {"day": today, "progress": {}, "paid": {}}


def daily_view(player_id: str) -> list[dict]:
    """Today's three jobs. A new date clears yesterday's progress."""
    user = get_character(player_id) or {}
    today = _today()
    bucket = user.get("daily") or {}
    if bucket.get("day") != today:
        bucket = _fresh_daily(today)
    progress = bucket.get("progress") or {}
    paid = bucket.get("paid") or {}
    rows = []
    for quest_id, text, need, gold in DAILIES:
        have = int(progress.get(quest_id) or 0)
        rows.append({
            "id": quest_id,
            "text": text,
            "need": need,
            "have": min(have, need),
            "gold": gold,
            "done": bool(paid.get(quest_id)),
        })
    return rows


def bump_daily(player_id: str, quest_id: str, steps: int = 1) -> str:
    """Advance one daily job. Pays gold once when the count reaches the goal."""
    spec = next((row for row in DAILIES if row[0] == quest_id), None)
    if spec is None or steps <= 0:
        return ""
    today = _today()

    def do(user):
        bucket = dict(user.get("daily") or {})
        if bucket.get("day") != today:
            bucket = _fresh_daily(today)
        progress = dict(bucket.get("progress") or {})
        paid = dict(bucket.get("paid") or {})
        if paid.get(quest_id):
            user["daily"] = bucket
            return ""
        have = int(progress.get(quest_id) or 0) + int(steps)
        progress[quest_id] = have
        bucket["progress"] = progress
        bucket["paid"] = paid
        if have >= spec[2]:
            paid[quest_id] = True
            bucket["paid"] = paid
            user["gold"] = int(user.get("gold") or 0) + spec[3]
            note = f"Việc ngày: {spec[1]} {spec[2]}/{spec[2]}. +{spec[3]} vàng."
        else:
            note = f"Việc ngày: {spec[1]} {have}/{spec[2]}."
        user["daily"] = bucket
        return note

    result = data_store._mutate_user(player_id, do)
    if result in (data_store.NOT_FOUND, data_store.FORBIDDEN, None):
        return ""
    return result or ""


def complete_task(player_id: str, task_id: str) -> str:
    spec = next((row for row in TASKS if row[0] == task_id), None)
    if spec is None:
        return ""

    def do(user):
        flags = dict(user.get("tasks") or {})
        if flags.get(task_id):
            return ""
        flags[task_id] = True
        user["tasks"] = flags
        user["gold"] = int(user.get("gold") or 0) + spec[2]
        return f"Xong việc: {spec[1]}. +{spec[2]} vàng."

    result = data_store._mutate_user(player_id, do)
    if result in (data_store.NOT_FOUND, data_store.FORBIDDEN, None):
        return ""
    return result or ""


def rest_character(player_id: str) -> dict:
    from datetime import date
    today = date.today().isoformat()

    def do(user):
        used = dict(user.get("rest_used") or {})
        if used.get("day") != today:
            used = {"day": today, "n": 0}
        if int(used.get("n") or 0) >= REST_PER_DAY:
            return {"ok": False, "message": f"Hôm nay đã nghỉ {REST_PER_DAY} lần."}
        before = int(user.get("the_luc") or 0)
        if before >= REST_CAP:
            return {"ok": False, "message": f"Thể lực đã {before}, không nghỉ thêm."}
        after = min(REST_CAP, before + REST_HEAL)
        user["the_luc"] = after
        used["n"] = int(used.get("n") or 0) + 1
        user["rest_used"] = used
        left = REST_PER_DAY - used["n"]
        return {
            "ok": True,
            "message": f"Nghỉ ngơi. Thể lực {before} → {after}. Còn {left} lần hôm nay.",
        }

    result = data_store._mutate_user(player_id, do)
    if result in (data_store.NOT_FOUND, data_store.FORBIDDEN, None):
        return {"ok": False, "message": "Chưa có nhân vật."}
    if isinstance(result, dict) and result.get("ok"):
        note = bump_daily(player_id, "rest")
        if note:
            result["message"] += "\n" + note
    return result


def waiting_text(player_id: str, channel_id: str = "") -> str:
    character = get_character(player_id)
    if character is None:
        return "Đang chờ: không"
    bits = []
    pending = character.get("pending_event") or {}
    if pending:
        bits.append(f"sự kiện {pending.get('title') or 'sau trận'}")
    run = character.get("dungeon_run")
    if run:
        bits.append(f"hầm, phòng {int(run.get('room_index') or 0) + 1}")
    if channel_id:
        from . import party as party_mod
        party = party_mod.find_party(str(channel_id), str(player_id))
        if party:
            bits.append(f"đội {party.get('title') or ''}".strip())
        if find_room(str(channel_id), str(player_id)):
            bits.append("phòng đấu")
    if not bits:
        return "Đang chờ: không"
    return "Đang chờ: " + " · ".join(bits)


def equip_or_consume(player_id: str, bag_index_1based: int):
    """Equip a weapon / equipment, or consume food at the given 1-based bag index.
    Equipment items are routed to `equip_gear`."""
    c = get_character(player_id)
    if c is None:
        return None
    if not (1 <= bag_index_1based <= len(c["bag"])):
        return None
    item = c["bag"][bag_index_1based - 1]
    if item.get("type") == "equipment":
        result = equip_gear(player_id, bag_index_1based)
        if not result:
            return None
        name = item.get("name")
        if isinstance(result, dict):
            name = (result.get("item") or {}).get("name", name)
        return {"ok": True, "action": "equip_gear", "name": name}
    result = data_store.set_item(player_id, bag_index_1based - 1)
    if isinstance(result, dict) and result.get("ok"):
        return result
    return None


def drink_belt(player_id: str, slot_1based: int) -> dict:
    """Drink one stamina charge from a belt slot. Combat items stay on the belt."""

    def do(user):
        equip_mod.ensure_loadout(user)
        belt = user["consumables"]
        idx = slot_1based - 1
        if not (0 <= idx < len(belt)) or not belt[idx]:
            return {"ok": False, "message": "Ô đai trống."}
        item = belt[idx]
        amount = int(item.get("heal_stamina") or 0)
        if item.get("subtype") != "stamina" and amount <= 0:
            return {
                "ok": False,
                "message": f"{item.get('name')} nằm trên đai và tự kích hoạt trong trận, không uống ngay.",
            }
        before = int(user.get("the_luc", 0))
        user["the_luc"] = before + amount
        left = int(item.get("qty", 1)) - 1
        if left > 0:
            item["qty"] = left
        else:
            belt[idx] = None
            left = 0
        return {
            "ok": True, "action": "consume", "name": item.get("name"),
            "stamina": amount, "before": before, "the_luc": user["the_luc"],
            "left": left, "notes": [f"⚡ Thể lực {before} → {user['the_luc']} (+{amount})"],
        }

    result = data_store._mutate_user(player_id, do)
    if result in (data_store.NOT_FOUND, data_store.FORBIDDEN, None):
        return {"ok": False, "message": "Không dùng được ô đai."}
    return result


def equip_gear(player_id: str, bag_index_1based: int, multi_slot_index: Optional[int] = None):
    """Equip armor/jewelry from bag. multi_slot_index selects glove/ring/bracelet slot 0|1."""
    result = equip_mod.equip_from_bag(player_id, bag_index_1based - 1, multi_slot_index)
    if result in (data_store.NOT_FOUND, data_store.FORBIDDEN):
        return None
    return result


def unequip_gear(player_id: str, slot_key: str):
    """Unequip by 'helmet' or 'gloves:0' / 'rings:1' / 'bracelets:0'."""
    result = equip_mod.unequip(player_id, slot_key)
    if result in (data_store.NOT_FOUND, data_store.FORBIDDEN):
        return None
    return result


def set_belt(player_id: str, belt_slot_1based: int, bag_index_1based: Optional[int]):
    """Put bag consumable into belt slot 1..5, or clear if bag_index is None."""
    bag_idx = None if bag_index_1based is None else bag_index_1based - 1
    result = equip_mod.set_belt_slot(player_id, belt_slot_1based - 1, bag_idx)
    if result in (data_store.NOT_FOUND, data_store.FORBIDDEN):
        return None
    return result


def craft_item(player_id: str, recipe_id: str, balance: int):
    """Craft from data/item/craft/recipes.json. Returns craft.CraftResult."""
    from . import craft as craft_mod
    return craft_mod.craft(player_id, recipe_id, balance)


def list_crafts(tier: Optional[str] = None):
    from . import craft as craft_mod
    return craft_mod.list_recipes(tier)


def enhance_quote(player_id: str, where: str = "weapon", bag_index_1based: Optional[int] = None) -> dict:
    """Preview cost/rate for the next enhance attempt."""
    from . import blacksmith as bs
    user = data_store.get_user(player_id)
    if user is None:
        return {"ok": False, "reason": "no_character"}
    idx = (bag_index_1based - 1) if bag_index_1based else None
    item, _ = bs._find_enhance_target(user, where, idx)
    if item is None:
        return {"ok": False, "reason": "no_item"}
    quote = bs.cost_for(item)
    quote["ok"] = True
    quote["display"] = bs.display_name(item)
    quote["current"] = bs.enhance_level(item)
    return quote


def enhance_item(player_id: str, where: str = "weapon", bag_index_1based: Optional[int] = None,
                 balance: int = 0, protect_bag_index_1based: Optional[int] = None,
                 luck_bag_indices_1based: Optional[list[int]] = None,
                 rng=None) -> dict:
    """Blacksmith enhance. Caller deducts gold_cost when result['ok'].
    luck_bag_indices_1based: bag slots of luck charms to consume (total luck capped +36%).
    """
    from . import blacksmith as bs
    luck0 = None
    if luck_bag_indices_1based:
        luck0 = [i - 1 for i in luck_bag_indices_1based if i]
    return bs.enhance(
        player_id,
        where=where,
        bag_index_0=(bag_index_1based - 1) if bag_index_1based else None,
        balance=balance,
        protect_bag_index_0=(protect_bag_index_1based - 1) if protect_bag_index_1based else None,
        luck_bag_indices_0=luck0,
        rng=rng,
    )


def list_dungeons() -> list[dict]:
    from . import dungeon as dg
    return dg.list_dungeons()


def start_dungeon(player_id: str, dungeon_id: str) -> dict:
    from . import dungeon as dg
    return dg.start_dungeon(player_id, dungeon_id)


def advance_dungeon(player_id: str, action_id: Optional[str] = None, rng=None) -> dict:
    from . import dungeon as dg
    return dg.advance_dungeon(player_id, action_id=action_id, rng=rng)


def abandon_dungeon(player_id: str) -> dict:
    from . import dungeon as dg
    return dg.abandon_dungeon(player_id)


# --------------------------------------------------------------------------
# Party / tổ đội
# --------------------------------------------------------------------------

def create_party(channel_id: str, player_id: str, title: str = ""):
    from . import party as party_mod
    return party_mod.create_party(channel_id, player_id, title)


def join_party(channel_id: str, player_id: str, stt_1based: int):
    from . import party as party_mod
    return party_mod.join_party(channel_id, player_id, stt_1based)


def leave_party(channel_id: str, player_id: str):
    from . import party as party_mod
    return party_mod.leave_party(channel_id, player_id)


def kick_party_member(channel_id: str, leader_id: str, target_id: str):
    from . import party as party_mod
    return party_mod.kick_member(channel_id, leader_id, target_id)


def disband_party(channel_id: str, leader_id: str):
    from . import party as party_mod
    return party_mod.disband_party(channel_id, leader_id)


def list_parties(channel_id: str):
    from . import party as party_mod
    return party_mod.list_parties(channel_id)


def set_party_location(channel_id: str, leader_id: str, location_index_1based: int):
    from . import party as party_mod
    return party_mod.set_party_location(channel_id, leader_id, location_index_1based)


def party_hunt(channel_id: str, starter_id: str, rng=None):
    from . import party as party_mod
    return party_mod.party_hunt(channel_id, starter_id, rng=rng)


def party_start_dungeon(channel_id: str, leader_id: str, dungeon_id: str):
    from . import party as party_mod
    return party_mod.party_start_dungeon(channel_id, leader_id, dungeon_id)


def party_advance_dungeon(channel_id: str, actor_id: str, action_id: Optional[str] = None, rng=None):
    from . import party as party_mod
    return party_mod.party_advance_dungeon(channel_id, actor_id, action_id=action_id, rng=rng)


def party_abandon_dungeon(channel_id: str, leader_id: str):
    from . import party as party_mod
    return party_mod.party_abandon_dungeon(channel_id, leader_id)


POINT_MULTIPLIERS = {"hp": 5, "def": 2, "atk": 2, "spd": 1}


def spend_points(player_id: str, stat: str, points: int):
    """Spend skill points. HP, ATK and DEF become +1% of the fight stat per point.
    SPD still adds 1 speed on the body. Returns the spent total, or NOT_FOUND / FORBIDDEN."""
    if stat not in POINT_MULTIPLIERS or points <= 0:
        return data_store.FORBIDDEN
    return data_store.spend_points(player_id, stat, points, POINT_MULTIPLIERS[stat])


def next_battle(player_id: str, stat: str, points: int = 1) -> tuple[Optional[dict], Optional[dict]]:
    """Fight stats now, and after `points` more on `stat`. None without a weapon."""
    if stat not in ("hp", "atk", "def", "spd") or int(points) <= 0:
        return None, None
    character = get_character(player_id)
    if character is None or not character.get("weapon"):
        return None, None
    ghost = dict(character)
    spent = dict(character.get("spent") or {})
    spent[stat] = int(spent.get(stat) or 0) + int(points)
    ghost["spent"] = spent
    if stat == "spd":
        ghost["spd"] = int(character.get("spd") or 0) + int(points) * POINT_MULTIPLIERS["spd"]
    return _battle_stats(character), _battle_stats(ghost)


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
    ensure_potion_kit(player_id)
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
    overlevel = bool(location_level is not None and c["level"] < location_level)
    # Vượt cấp được phép: map cao hơn level nhân vật → đánh được nhưng tốn thêm thể lực
    if c["the_luc"] < MIN_STAMINA_TO_FIGHT:
        return {"ok": False, "reason": "no_stamina"}
    if overlevel and c["the_luc"] < MIN_STAMINA_TO_FIGHT + 30:
        return {"ok": False, "reason": "no_stamina", "overlevel": True,
                "required_level": location_level}
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
        "AP": monster_template["ArmorPiercing"],
        "Mana": 1,
        "maxHP": monster_hp,
    }
    equip_mod.ensure_loadout(c)
    belt_snapshot = [dict(x) if x else None for x in c["consumables"]]
    player_start = dict(player_stats)
    monster_start = dict(monster_stats)
    result = combat.fight_monster(
        player_stats, monster_stats,
        monster_actions=monster_template.get("actions") or [],
        player_belt=belt_snapshot,
        weapon_category=c["weapon"].get("category") or "",
        weapon=c["weapon"],
    )

    def _save_belt(u):
        equip_mod.ensure_loadout(u)
        u["consumables"] = result.get("belt") if result.get("belt") is not None else belt_snapshot
        return True
    data_store._mutate_user(player_id, _save_belt)

    durability = data_store.decrease_durability(player_id)
    # Karma only climbs on victories (balance vs. loss-spiral)
    if result.get("winner") or result.get("draw"):
        data_store.karma_up(player_id, data_store.KARMA_ON_WIN)
    weapon_broken = data_store.decrease_health_weapon(player_id, result["playerPow"]["HP"]) is True
    if weapon_broken:
        durability = 0

    dmg_dealt = dmg_taken = 0
    for entry in result["log"]:
        if entry["attacker"] == "player":
            dmg_dealt += entry["damage"]
        else:
            dmg_taken += entry["damage"]

    won = bool(result["winner"])
    draw = bool(result.get("draw"))
    reward_win = won or draw

    location = data_store.find_location(c["locationID"]) or {}
    outcome = {
        "ok": True,
        "won": won,
        "draw": draw,
        "overlevel": overlevel,
        "location_level": location_level,
        "player_name": c["name"],
        "weapon_name": c["weapon"]["name"],
        "weapon_category": c["weapon"].get("category"),
        "location_name": location.get("name", ""),
        "monster_name": monster_template["Name"],
        "monster_tier": tier,
        "monster_level": level,
        "monster_power": base_power,
        "monster_threat": threat_label(base_power),
        "monster_price": monster_template.get("price", 0),
        "player_stats": player_start,
        "monster_stats": monster_start,
        "log": result["log"],
        "turns": len(result["log"]),
        "player_damage_dealt": dmg_dealt,
        "player_damage_taken": dmg_taken,
        "weapon_durability": durability,
        "weapon_broken": weapon_broken,
        "exp_gained": 0,
        "events": [],
        "drops": [],
        "adventure": None,
        "items_used": [
            ev for entry in result["log"] for ev in (entry.get("events") or [])
            if ev.get("kind") in ("use_item", "special")
        ],
    }

    if overlevel:
        def _overlevel_tax(u):
            u["the_luc"] = max(0, u.get("the_luc", 0) - 30)
            return True
        data_store._mutate_user(player_id, _overlevel_tax)

    if reward_win:
        trophy = dict(monster_template)
        trophy["level"] = level
        data_store.add_monster(player_id, trophy)
        exp_final = exp_reward if won else max(1, exp_reward // 2)
        if overlevel:
            exp_final = round(exp_final * 1.25)  # risk bonus
        level_events = data_store.set_exp(player_id, exp_final)
        outcome["exp_gained"] = exp_final
        outcome["events"] = level_events if isinstance(level_events, list) else []
        outcome["drops"] = adventure.roll_monster_drops(player_id, monster_template)

    result_word = "hòa (đồng quy)" if draw else ("thắng" if won else "thua")
    hunt_lines = [
        f"📍 {location.get('name', '')}" + (" ⚡VƯỢT CẤP" if overlevel else ""),
        f"{'☠️' if draw else ('🏆' if won else '💀')} {monster_template['Name']} "
        f"Tier {tier} Lv.{level} — {result_word}",
    ]
    if outcome["exp_gained"]:
        hunt_lines.append(f"✨ +{outcome['exp_gained']} EXP")
    for drop in outcome["drops"]:
        hunt_lines.append(f"🎁 {drop['name']} ×{drop.get('qty', 1)}")
    for ev in outcome["items_used"]:
        if ev.get("log"):
            hunt_lines.append(ev["log"])
    trail = journey.play([player_id], location, mode="solo")
    outcome["journey"] = trail
    hunt_lines.extend(trail.get("lines") or [])
    data_store.append_history(player_id, {
        "ts": int(time.time() * 1000),
        "kind": "hunt",
        "location": location.get("name"),
        "won": won,
        "draw": draw,
        "monster": monster_template["Name"],
        "tier": tier,
        "lines": hunt_lines,
    })

    pending = adventure.maybe_start_event(player_id, location)
    if pending:
        outcome["adventure"] = {
            "id": pending["id"],
            "title": pending["title"],
            "intro": pending["intro"],
            "actions": pending["actions"],
            "location_name": pending.get("location_name"),
        }

    note = bump_daily(player_id, "hunt")
    if note:
        outcome["daily_note"] = note

    after = get_character(player_id)
    outcome["belt"] = [dict(x) if x else None for x in (after.get("consumables") or [])]
    outcome["pocket"] = [
        dict(it) for it in (after.get("bag") or [])
        if it.get("type") in ("consumable", "food")
    ]
    outcome["player_level"] = after["level"]
    outcome["player_exp"] = round(after["exp"])
    outcome["player_exp_needed"] = data_store.exp_needed_for(after["level"])
    outcome["player_the_luc"] = after["the_luc"]
    outcome["repair_cost"] = repair_cost(after["weapon"]) if after["weapon"] else 0
    return outcome


# --------------------------------------------------------------------------
# Adventure helpers (thin wrappers around adventure.py)
# --------------------------------------------------------------------------

def get_pending_adventure(player_id: str):
    return adventure.get_pending_event(player_id)


def resolve_adventure(player_id: str, action_id: str):
    """Choose an action on the pending map event (e.g. 'open' / 'leave')."""
    return adventure.resolve_event(player_id, action_id)


def journey_log(player_id: str, limit: int = 20) -> list[dict]:
    c = get_character(player_id)
    if c is None:
        return []
    history = c.get("history") or []
    return history[-limit:]


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
    p1_start = combat.build_combat_stats(char1)
    p2_start = combat.build_combat_stats(char2)
    result = combat.fight_pvp(char1, char2)

    def _persist(pid, belt_key):
        belt = result.get(belt_key)
        if belt is None:
            return
        def mut(u):
            equip_mod.ensure_loadout(u)
            u["consumables"] = belt
            return True
        data_store._mutate_user(pid, mut)
    _persist(p1_id, "a_belt")
    _persist(p2_id, "b_belt")

    dmg = {"player1": 0, "player2": 0}
    for entry in result["log"]:
        dmg[entry["attacker"]] += entry["damage"]

    draw = result["winner"] == "draw"
    if draw:
        winner_id = None
        winner_name = None
    else:
        winner_id = p1_id if result["winner"] == "player1" else p2_id
        winner_name = char1["name"] if winner_id == p1_id else char2["name"]
    outcome = {
        "winner_id": winner_id,
        "winner_name": winner_name,
        "draw": draw,
        "rounds": len(result["log"]),
        "room_title": room["title"],
        "player1_id": p1_id, "player2_id": p2_id,
        "player1_name": char1["name"], "player2_name": char2["name"],
        "player1_weapon": char1["weapon"]["name"], "player2_weapon": char2["weapon"]["name"],
        "player1_weapon_category": char1["weapon"].get("category"),
        "player2_weapon_category": char2["weapon"].get("category"),
        "player1_stats": p1_start, "player2_stats": p2_start,
        "player1_damage": dmg["player1"], "player2_damage": dmg["player2"],
        "log": result["log"],
    }
    room["status"] = 2
    room["ready"] = False
    return outcome
