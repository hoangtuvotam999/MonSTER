"""
Persistence layer — port of the original getData.js / setData.js pair.

The original JS code kept everything in flat JSON files and rewrote the
whole file on every mutation (`fs.writeFileSync`). We keep that same
simple (if not very scalable) approach here for fidelity, wrapped behind
a small API so it's easy to swap out for a real database later.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).parent / "data"
USERS_FILE = DATA_DIR / "users.json"
ITEMS_FILE = DATA_DIR / "items.json"
MONSTERS_FILE = DATA_DIR / "monsters.json"

NOT_FOUND = 404
FORBIDDEN = 403
OK = True

MAX_DURABILITY = 100


def exp_needed_for(level: int) -> int:
    """EXP a character needs to go from `level` to `level + 1`.

    Single source of truth: the original computed this in two places with
    two different roundings (`500 * round(1.2 ** n)` for display vs.
    `500 * 1.2 ** n` for the actual level-up check), so the status screen
    could show a threshold the player had already passed."""
    return round(500 * 1.2 ** (level - 1))


def weapon_exp_needed_for(usage: int) -> int:
    """EXP a weapon needs to go from usage-level `usage` to `usage + 1`."""
    return round(500 * 1.2 ** usage)


def _load(path: Path) -> Any:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# --------------------------------------------------------------------------
# Reads (port of getData.js)
# --------------------------------------------------------------------------

def load_users() -> list[dict]:
    return _load(USERS_FILE)


def get_user(user_id: str) -> Optional[dict]:
    """Port of getData.getDataUser."""
    return next((u for u in load_users() if u["id"] == user_id), None)


def get_items(item_id: Optional[int] = None):
    """Port of getData.getItems. Returns the whole catalog, or one item."""
    items = _load(ITEMS_FILE)
    if item_id is not None:
        return next((i for i in items if i["id"] == item_id), None)
    return items


def _find_location(location_id) -> Optional[dict]:
    return next((loc for loc in _load(MONSTERS_FILE) if str(loc["ID"]) == str(location_id)), None)


def get_monsters(location_id) -> Optional[list[dict]]:
    """Port of getData.getMonster (renamed: it returns a *list* of monsters)."""
    loc = _find_location(location_id)
    return loc["creature"] if loc else None


def get_min_level(location_id) -> Optional[int]:
    loc = _find_location(location_id)
    return loc["minLevel"] if loc else None


def get_max_level(location_id) -> Optional[int]:
    loc = _find_location(location_id)
    return loc["maxLevel"] if loc else None


def get_location_level(location_id) -> Optional[int]:
    loc = _find_location(location_id)
    return loc["level"] if loc else None


def list_locations() -> list[dict]:
    return _load(MONSTERS_FILE)


# --------------------------------------------------------------------------
# Writes (port of setData.js). Every function loads the full user list,
# mutates the matching entry in place, and persists — exactly like the
# original fs.writeFileSync-per-call approach.
# --------------------------------------------------------------------------

def _mutate_user(user_id: str, mutator):
    """Load users, find the one with `user_id`, call mutator(user) on it,
    persist, and return whatever mutator returned (or NOT_FOUND)."""
    users = load_users()
    user = next((u for u in users if u["id"] == user_id), None)
    if user is None:
        return NOT_FOUND
    result = mutator(user)
    _save(USERS_FILE, users)
    return result


def create_character(data: dict) -> dict:
    users = load_users()
    users.append(data)
    _save(USERS_FILE, users)
    return data


def _owns_weapon(user: dict, item: dict) -> bool:
    name = item.get("name")
    if user.get("weapon") and user["weapon"].get("name") == name:
        return True
    return any(it.get("type") == "weapon" and it.get("name") == name for it in user["bag"])


def buy_item(player_id: str, item: Optional[dict]):
    """Port of setData.buyItem.

    FIXED vs. the original: the duplicate check only compared against the
    *equipped* weapon, so a player could buy the same weapon over and over
    as long as it sat unequipped in the bag. Weapons are now unique across
    the equipped slot and the bag; consumables (food/upgrades) can always
    be stacked."""
    if item is None:
        return NOT_FOUND

    def do(user):
        if item.get("type") == "weapon" and _owns_weapon(user, item):
            return FORBIDDEN
        user["bag"].append(dict(item))
        return OK

    return _mutate_user(player_id, do)


def set_item(player_id: str, bag_index: int):
    """Port of setData.setItem — equip the weapon, or consume the food /
    upgrade material, sitting at 0-based `bag_index` in the player's bag.

    FIXED vs. the original, which took the item *object* and then removed
    the first bag entry with the same *name*: with two identical items in
    the bag that could delete the wrong copy, and when equipping a new
    weapon the previously equipped one simply vanished. Now the exact slot
    is consumed, and the old weapon is returned to the bag on swap."""

    def do(user):
        bag = user["bag"]
        if not (0 <= bag_index < len(bag)):
            return NOT_FOUND
        data = bag[bag_index]
        kind = data.get("type")

        if kind == "weapon":
            old_weapon = user.get("weapon")
            data.setdefault("maxHP", data["HP"])
            user["weapon"] = data
            bag.pop(bag_index)
            if old_weapon is not None:
                bag.append(old_weapon)
            return OK
        elif kind == "buff":
            user["buffs"] = data
        elif kind == "food":
            user["the_luc"] = user.get("the_luc", 0) + data.get("heal", 0)
            user["hp"] += data.get("boostHP", 0)
            user["atk"] += data.get("boostATK", 0)
            user["def"] += data.get("boostDEF", 0)
            user["spd"] += data.get("boostSPD", 0)
            user["exp"] += data.get("boostEXP", 0)
            user["karma"] = max(0, user["karma"] + data.get("boostKarma", 0))
            user["points"] += data.get("boostPoints", 0)
        elif kind == "upgrade":
            w = user.get("weapon")
            if w is None:
                return FORBIDDEN
            w["maxHP"] = weapon_max_hp(w) + data.get("boostHPweapon", 0)
            w["HP"] += data.get("boostHPweapon", 0)
            w["ATK"] += data.get("boostATKweapon", 0)
            w["DEF"] += data.get("boostDEFweapon", 0)
            w["SPD"] += data.get("boostSPDweapon", 0)
            w["usage"] = w.get("usage", 0) + data.get("usage", 0)
        else:
            return FORBIDDEN

        bag.pop(bag_index)
        return OK

    return _mutate_user(player_id, do)


def decrease_durability(player_id: str, amount: int = 10):
    def do(user):
        if user.get("weapon") is None:
            return FORBIDDEN
        user["weapon"]["durability"] = max(0, user["weapon"]["durability"] - amount)
        return user["weapon"]["durability"]

    return _mutate_user(player_id, do)


def increase_durability(player_id: str, amount: int):
    def do(user):
        if user.get("weapon") is None:
            return FORBIDDEN
        user["weapon"]["durability"] = min(MAX_DURABILITY, user["weapon"]["durability"] + int(amount))
        return user["weapon"]["durability"]

    return _mutate_user(player_id, do)


def decrease_points(player_id: str, points: int):
    def do(user):
        if user["points"] < points:
            return FORBIDDEN
        user["points"] -= int(points)
        return user["points"]

    return _mutate_user(player_id, do)


def _increase_stat(stat: str):
    def increase(player_id: str, amount: int):
        def do(user):
            user[stat] += int(amount)
            return user[stat]

        return _mutate_user(player_id, do)

    increase.__name__ = f"increase_{stat}"
    return increase


# FIXED vs. the original: these refused to add to a stat that was exactly 0
# (`if (user.hp == 0) return 403`), which made no sense for a stat *increase*.
increase_hp = _increase_stat("hp")
increase_def = _increase_stat("def")
increase_atk = _increase_stat("atk")
increase_spd = _increase_stat("spd")


def spend_points(player_id: str, stat: str, points: int, per_point: int):
    """Atomically convert `points` skill points into `points * per_point` of
    `stat`. The original did this as two separate writes (increase stat,
    then decrease points), so a failure in between could hand out free
    stats. Returns the new stat value, or FORBIDDEN."""
    if stat not in ("hp", "atk", "def", "spd") or points <= 0:
        return FORBIDDEN

    def do(user):
        if user["points"] < points:
            return FORBIDDEN
        user["points"] -= int(points)
        user[stat] += int(points) * per_point
        return user[stat]

    return _mutate_user(player_id, do)


def set_location(player_id: str, location_id: str):
    def do(user):
        user["locationID"] = location_id
        return OK

    return _mutate_user(player_id, do)


def set_exp(player_id: str, exp: float):
    """Port of setData.setExp — grants EXP to the character and its equipped
    weapon, handling level-ups for both. Returns a list of events describing
    what happened so the caller can decide how to notify the player.

    FIXED vs. the original two bugs:
    1. The original's "levels gained" formula `floor(x/N + 1 - x/N)` always
       evaluates to exactly 1, so a huge EXP reward (e.g. from a very strong
       monster) could only ever advance one level per call, silently
       discarding the rest of the overshoot as if it were leftover EXP.
       Fixed here with a loop that keeps leveling up — recomputing the
       (level-dependent) threshold each time — until the remaining EXP is
       no longer enough for the next level, exactly like a standard RPG
       leveling curve.
    2. The weapon's level-up formula reused the *character's* EXP
       requirement (`expNeeded`) instead of the weapon's own
       (`expWeaponNeed`) when computing how many usage-levels to grant.
       Fixed here by using `weapon_exp_needed` consistently, in its own
       loop, independent of the character's level curve.
    3. It bailed out with 404 when the player had no weapon, so a hunter
       whose weapon was destroyed by the very fight they just *won* got no
       EXP at all. Character EXP is now always granted; weapon EXP only
       when there is a weapon to receive it.
    4. `if (exp <= 0) the_luc = 0` zeroed the player's stamina whenever
       their total EXP happened to be 0 — dropped.
    """

    def do(user):
        user["exp"] += exp
        events = []

        # Character leveling: loop so a big EXP reward can grant several
        # levels at once, each time recomputing the threshold at the new level.
        while user["exp"] >= exp_needed_for(user["level"]):
            user["exp"] -= exp_needed_for(user["level"])
            user["level"] += 1
            user["atk"] += 2 * user["level"]
            user["def"] += 2 * user["level"]
            user["hp"] += 5 * user["level"]
            user["spd"] += 1 * user["level"]
            user["points"] += 500 * user["level"]
            events.append(("level_up", user["level"]))

        weapon = user.get("weapon")
        if weapon is None:
            return events

        weapon.setdefault("usage", 0)
        weapon["exp"] = weapon.get("exp", 0) + exp

        # Weapon leveling: same loop pattern, using the weapon's own
        # (usage-dependent) EXP requirement instead of the character's.
        while weapon["exp"] >= weapon_exp_needed_for(weapon["usage"]):
            weapon["exp"] -= weapon_exp_needed_for(weapon["usage"])
            weapon["usage"] += 1
            weapon["ATK"] += round(weapon["ATK"] * 0.01)
            weapon["DEF"] += round(weapon["DEF"] * 0.01)
            weapon["SPD"] += round(weapon["SPD"] * 0.01)
            # Grow the *max* HP (the current HP is the depleted health pool).
            hp_gain = round(weapon_max_hp(weapon) * 0.01)
            weapon["maxHP"] = weapon_max_hp(weapon) + hp_gain
            weapon["HP"] += hp_gain
            events.append(("weapon_level_up", weapon["usage"]))

        return events

    return _mutate_user(player_id, do)


def add_monster(player_id: str, monster: dict):
    def do(user):
        user["monster"].append(monster)
        return OK

    return _mutate_user(player_id, do)


def weapon_max_hp(weapon: dict) -> int:
    """The HP the weapon is repaired back to. Older saves have no `maxHP`,
    so fall back to the current HP (they'll pick the field up on the next
    equip/upgrade/repair)."""
    return weapon.get("maxHP", weapon["HP"])


def decrease_health_weapon(player_id: str, remaining_hp_stat: float):
    """Port of setData.decreaseHealthWeapon — derives the weapon's new HP
    bonus from the player's HP left over after a fight. HP does not
    regenerate between hunts: the weapon's HP *is* the hunter's persistent
    health pool, refilled by repairing (see repair_weapon) or upgrading.

    FIXED vs. the original:
    - The JS version computed `weapon.HP = remaining_hp - user.hp`, which
      silently ignored the weapon's `hpBonus` multiplier. Since the actual
      HP stat used in combat is `(user.hp + weapon.HP) * hpBonus`
      (see combat.build_combat_stats), reversing that correctly requires
      dividing out `hpBonus` first. Identical for hpBonus == 1.
    - Losing a fight (or dropping to 0 weapon HP) used to *delete* the
      weapon — for a fresh character that meant a ~17% chance per hunt of
      being left with nothing to fight with. Now the weapon is only
      *broken* (HP and durability zeroed) and can be repaired.

    Returns True if the weapon broke, False if it is still usable.
    """

    def do(user):
        w = user.get("weapon")
        if w is None:
            return FORBIDDEN
        user["the_luc"] = max(0, user["the_luc"] - 50)
        w.setdefault("maxHP", w["HP"])
        if remaining_hp_stat <= 0:
            w["HP"] = 0
            w["durability"] = 0
            return True
        hp_bonus = w.get("hpBonus") or 1
        w["HP"] = max(0, round(remaining_hp_stat / hp_bonus - user["hp"]))
        return w["durability"] <= 0

    return _mutate_user(player_id, do)


def repair_weapon(player_id: str):
    """Restore the equipped weapon to full durability and full (max) HP.
    Returns the repaired weapon dict, or FORBIDDEN if none is equipped."""

    def do(user):
        w = user.get("weapon")
        if w is None:
            return FORBIDDEN
        w["durability"] = MAX_DURABILITY
        w["HP"] = weapon_max_hp(w)
        w["maxHP"] = w["HP"]
        return dict(w)

    return _mutate_user(player_id, do)


def karma_up(player_id: str):
    def do(user):
        user["karma"] = max(0, user["karma"] + 1)
        return user["karma"]

    return _mutate_user(player_id, do)


def sell_monsters(player_id: str, indices: Optional[list[int]] = None):
    """Sell monsters from the trophy bag. `indices` is 1-based, matching the
    original's user-facing numbering; pass None to sell everything.
    Returns (count_sold, total_money)."""

    def do(user):
        monsters = user["monster"]
        if indices is None:
            total = sum(m["price"] for m in monsters)
            count = len(monsters)
            user["monster"] = []
            return count, total
        count, total = 0, 0
        for i in sorted(set(indices), reverse=True):
            if 1 <= i <= len(monsters):
                total += monsters[i - 1]["price"]
                monsters.pop(i - 1)
                count += 1
        return count, total

    return _mutate_user(player_id, do)
