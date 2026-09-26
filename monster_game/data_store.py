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


def buy_item(player_id: str, item: Optional[dict]):
    """Port of setData.buyItem. NOTE: preserves the original's slightly odd
    duplicate check, which only blocks buying a weapon whose *name* matches
    the currently equipped weapon (not other items in the bag)."""
    if item is None:
        return NOT_FOUND

    def do(user):
        if user.get("weapon") and item.get("name") == user["weapon"].get("name"):
            return FORBIDDEN
        user["bag"].append(item)
        return OK

    return _mutate_user(player_id, do)


def set_item(player_id: str, data: dict):
    """Port of setData.setItem — equip a weapon/buff, or consume food/upgrade."""

    def do(user):
        kind = data.get("type")
        bag = user["bag"]
        idx = next((i for i, it in enumerate(bag) if it.get("name") == data.get("name")), None)

        if kind == "weapon":
            user["weapon"] = data
        elif kind == "buff":
            user["buffs"] = data
        elif kind == "food":
            user["the_luc"] = user.get("the_luc", 0) + data.get("heal", 0)
            user["hp"] += data.get("boostHP", 0)
            user["atk"] += data.get("boostATK", 0)
            user["def"] += data.get("boostDEF", 0)
            user["spd"] += data.get("boostSPD", 0)
            user["exp"] += data.get("boostEXP", 0)
            user["karma"] += data.get("boostKarma", 0)
            user["points"] += data.get("boostPoints", 0)
        elif kind == "upgrade":
            if user.get("weapon") is None:
                return FORBIDDEN
            user["weapon"]["HP"] += data.get("boostHPweapon", 0)
            user["weapon"]["ATK"] += data.get("boostATKweapon", 0)
            user["weapon"]["DEF"] += data.get("boostDEFweapon", 0)
            user["weapon"]["SPD"] += data.get("boostSPDweapon", 0)
            user["weapon"]["usage"] += data.get("usage", 0)
        else:
            return FORBIDDEN

        if idx is not None:
            bag.pop(idx)
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
        user["weapon"]["durability"] = min(10000, user["weapon"]["durability"] + int(amount))
        return user["weapon"]["durability"]

    return _mutate_user(player_id, do)


def decrease_points(player_id: str, points: int):
    def do(user):
        if user["points"] == 0:
            return FORBIDDEN
        user["points"] = max(0, user["points"] - int(points))
        return user["points"]

    return _mutate_user(player_id, do)


def increase_hp(player_id: str, amount: int):
    def do(user):
        if user["hp"] == 0:
            return FORBIDDEN
        user["hp"] += int(amount)
        return user["hp"]

    return _mutate_user(player_id, do)


def increase_def(player_id: str, amount: int):
    def do(user):
        if user["def"] == 0:
            return FORBIDDEN
        user["def"] += int(amount)
        return user["def"]

    return _mutate_user(player_id, do)


def increase_atk(player_id: str, amount: int):
    def do(user):
        if user["atk"] == 0:
            return FORBIDDEN
        user["atk"] += int(amount)
        return user["atk"]

    return _mutate_user(player_id, do)


def increase_spd(player_id: str, amount: int):
    def do(user):
        if user["spd"] == 0:
            return FORBIDDEN
        user["spd"] += int(amount)
        return user["spd"]

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
    """

    def do(user):
        if user.get("weapon") is None:
            return NOT_FOUND
        user["exp"] += exp
        user["weapon"].setdefault("usage", 0)
        user["weapon"]["exp"] = user["weapon"].get("exp", 0) + exp

        events = []

        if user["exp"] <= 0:
            user["the_luc"] = 0

        # Character leveling: loop so a big EXP reward can grant several
        # levels at once, each time recomputing the threshold at the new level.
        while True:
            exp_needed = 500 * (1.2 ** (user["level"] - 1))
            if user["exp"] < exp_needed:
                break
            user["exp"] -= exp_needed
            user["level"] += 1
            user["atk"] += 2 * user["level"]
            user["def"] += 2 * user["level"]
            user["hp"] += 5 * user["level"]
            user["spd"] += 1 * user["level"]
            user["points"] += 500 * user["level"]
            events.append(("level_up", user["level"]))

        # Weapon leveling: same loop pattern, using the weapon's own
        # (usage-dependent) EXP requirement instead of the character's.
        while True:
            weapon_exp_needed = 500 * (1.2 ** user["weapon"]["usage"])
            if user["weapon"]["exp"] < weapon_exp_needed:
                break
            user["weapon"]["exp"] -= weapon_exp_needed
            user["weapon"]["usage"] += 1
            user["weapon"]["ATK"] += round(user["weapon"]["ATK"] * 0.01)
            user["weapon"]["DEF"] += round(user["weapon"]["DEF"] * 0.01)
            user["weapon"]["HP"] += round(user["weapon"]["HP"] * 0.01)
            user["weapon"]["SPD"] += round(user["weapon"]["SPD"] * 0.01)
            events.append(("weapon_level_up", user["weapon"]["usage"]))

        return events

    return _mutate_user(player_id, do)


def add_monster(player_id: str, monster: dict):
    def do(user):
        user["monster"].append(monster)
        return OK

    return _mutate_user(player_id, do)


def decrease_health_weapon(player_id: str, remaining_hp_stat: float):
    """Port of setData.decreaseHealthWeapon — derives the weapon's new HP
    bonus from the player's HP left over after a fight (this is how combat
    damage "hits" the weapon instead of a separate HP pool).

    FIXED vs. the original: the JS version computed
    `weapon.HP = remaining_hp - user.hp`, which silently ignored the
    weapon's `hpBonus` multiplier. Since the actual HP stat used in combat
    is `(user.hp + weapon.HP) * hpBonus` (see combat.build_combat_stats),
    reversing that correctly requires dividing out `hpBonus` first:
    `weapon.HP = remaining_hp_stat / hpBonus - user.hp`. For any weapon
    with hpBonus == 1 this is identical to the original; it only differs
    (and now behaves correctly) for weapons that boost/reduce HP.
    """

    def do(user):
        if user.get("weapon") is None:
            return FORBIDDEN
        user["the_luc"] = max(0, user["the_luc"] - 50)
        if remaining_hp_stat < 0:
            # Player's HP stat went negative during the fight (a loss) —
            # the weapon is destroyed outright, same as the original intent.
            user["weapon"] = None
            return OK
        hp_bonus = user["weapon"].get("hpBonus") or 1
        new_weapon_hp = remaining_hp_stat / hp_bonus - user["hp"]
        if new_weapon_hp <= 0:
            user["weapon"] = None
        else:
            user["weapon"]["HP"] = round(new_weapon_hp)
        return OK

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
