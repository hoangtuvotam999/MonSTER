"""
Persistence layer — port of the original getData.js / setData.js pair.

Catalog data is split so authors can add a map or item tier without
touching a monolith:

    data/map/*.json
    data/item/weapon/tier_*.json
    data/item/drop/tier_*.json
    data/item/food.json
    data/item/upgrade.json
    data/users.json          (runtime saves)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).parent / "data"
USERS_FILE = DATA_DIR / "users.json"
MAP_DIR = DATA_DIR / "map"
DUNGEON_DIR = DATA_DIR / "dungeon"
ITEM_DIR = DATA_DIR / "item"
WEAPON_DIR = ITEM_DIR / "weapon"
DROP_DIR = ITEM_DIR / "drop"
EQUIP_DIR = ITEM_DIR / "equipment"
CONSUMABLE_DIR = ITEM_DIR / "consumable"
FOOD_FILE = ITEM_DIR / "food.json"
UPGRADE_FILE = ITEM_DIR / "upgrade.json"

# Legacy flat files (still read as fallback if the modular tree is empty)
LEGACY_ITEMS_FILE = DATA_DIR / "items.json"
LEGACY_MONSTERS_FILE = DATA_DIR / "monsters.json"

NOT_FOUND = 404
FORBIDDEN = 403
OK = True

MAX_DURABILITY = 100
MAX_HISTORY = 80

# In-process caches (cleared via reload_catalogs())
_maps_cache: Optional[list[dict]] = None
_dungeons_cache: Optional[list[dict]] = None
_weapons_cache: Optional[list[dict]] = None
_drops_cache: Optional[list[dict]] = None
_drops_by_id: Optional[dict[str, dict]] = None
_food_cache: Optional[list[dict]] = None
_upgrade_cache: Optional[list[dict]] = None
_equipment_cache: Optional[list[dict]] = None
_equipment_sets: Optional[dict] = None
_consumable_cache: Optional[list[dict]] = None
_consumable_by_id: Optional[dict[str, dict]] = None


def exp_needed_for(level: int) -> int:
    return round(500 * 1.2 ** (level - 1))


def weapon_exp_needed_for(usage: int) -> int:
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


def _load_json_dir(directory: Path) -> list[dict]:
    """Load every *.json file in a directory (sorted by name).
    Files may contain a list or a single object."""
    if not directory.exists():
        return []
    items: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        payload = _load(path)
        if isinstance(payload, list):
            items.extend(payload)
        elif isinstance(payload, dict):
            items.append(payload)
    return items


def reload_catalogs() -> None:
    """Drop in-memory catalogs so the next read re-scans the data/ tree."""
    global _maps_cache, _dungeons_cache, _weapons_cache, _drops_cache, _drops_by_id
    global _food_cache, _upgrade_cache
    global _equipment_cache, _equipment_sets, _consumable_cache, _consumable_by_id
    _maps_cache = _dungeons_cache = _weapons_cache = _drops_cache = None
    _drops_by_id = _food_cache = _upgrade_cache = None
    _equipment_cache = _equipment_sets = None
    _consumable_cache = _consumable_by_id = None
    try:
        import monster_game.blacksmith as bs
        bs._cfg_cache = None
    except Exception:
        pass
    try:
        from . import tiers as tier_mod
        tier_mod.reload()
    except Exception:
        pass


# Points granted on level-up (balance: was 500*level — far too high)
LEVEL_UP_POINTS = 40
# Karma: only rise on wins; losses don't feed the spiral
KARMA_ON_WIN = 1
KARMA_ON_LOSS = 0


# --------------------------------------------------------------------------
# Catalog reads
# --------------------------------------------------------------------------

def list_locations() -> list[dict]:
    global _maps_cache
    if _maps_cache is None:
        maps = _load_json_dir(MAP_DIR)
        if not maps and LEGACY_MONSTERS_FILE.exists():
            maps = _load(LEGACY_MONSTERS_FILE)
        _maps_cache = sorted(maps, key=lambda m: m.get("ID", 0))
    return _maps_cache


def list_dungeons() -> list[dict]:
    global _dungeons_cache
    if _dungeons_cache is None:
        _dungeons_cache = _load_json_dir(DUNGEON_DIR)
    return _dungeons_cache


def get_dungeon(dungeon_id: str) -> Optional[dict]:
    return next((d for d in list_dungeons() if d.get("id") == dungeon_id), None)


def find_location(location_id) -> Optional[dict]:
    return next((loc for loc in list_locations() if str(loc["ID"]) == str(location_id)), None)


def get_monsters(location_id) -> Optional[list[dict]]:
    loc = find_location(location_id)
    return loc["creature"] if loc else None


def get_min_level(location_id) -> Optional[int]:
    loc = find_location(location_id)
    return loc["minLevel"] if loc else None


def get_max_level(location_id) -> Optional[int]:
    loc = find_location(location_id)
    return loc["maxLevel"] if loc else None


def get_location_level(location_id) -> Optional[int]:
    loc = find_location(location_id)
    return loc["level"] if loc else None


def get_weapons() -> list[dict]:
    global _weapons_cache
    if _weapons_cache is None:
        weapons = [w for w in _load_json_dir(WEAPON_DIR) if w.get("type") == "weapon"]
        if not weapons and LEGACY_ITEMS_FILE.exists():
            weapons = [i for i in _load(LEGACY_ITEMS_FILE) if i.get("type") == "weapon"]
        _weapons_cache = weapons
    return _weapons_cache


def get_items(item_id: Optional[int] = None):
    """Weapon catalog (compat with old get_items)."""
    items = get_weapons()
    if item_id is not None:
        return next((i for i in items if i.get("id") == item_id), None)
    return items


def get_food_items() -> list[dict]:
    global _food_cache
    if _food_cache is None:
        _food_cache = _load(FOOD_FILE) if FOOD_FILE.exists() else []
    return _food_cache


def get_upgrade_materials() -> list[dict]:
    global _upgrade_cache
    if _upgrade_cache is None:
        _upgrade_cache = _load(UPGRADE_FILE) if UPGRADE_FILE.exists() else []
    return _upgrade_cache


def get_drops() -> list[dict]:
    global _drops_cache, _drops_by_id
    if _drops_cache is None:
        _drops_cache = _load_json_dir(DROP_DIR)
        _drops_by_id = {d["id"]: d for d in _drops_cache if "id" in d}
    return _drops_cache


def get_drop(drop_id: str) -> Optional[dict]:
    get_drops()
    assert _drops_by_id is not None
    return _drops_by_id.get(drop_id)


def get_equipment(slot: Optional[str] = None) -> list[dict]:
    global _equipment_cache
    if _equipment_cache is None:
        items = []
        if EQUIP_DIR.exists():
            for path in sorted(EQUIP_DIR.glob("*.json")):
                if path.name == "sets.json":
                    continue
                payload = _load(path)
                if isinstance(payload, list):
                    items.extend(payload)
        _equipment_cache = items
    if slot is None:
        return _equipment_cache
    return [i for i in _equipment_cache if i.get("slot") == slot]


def get_equipment_sets() -> dict:
    global _equipment_sets
    if _equipment_sets is None:
        path = EQUIP_DIR / "sets.json"
        _equipment_sets = _load(path) if path.exists() else {}
    return _equipment_sets


def get_equipment_by_id(item_id: str) -> Optional[dict]:
    return next((i for i in get_equipment() if i.get("id") == item_id), None)


def get_consumables() -> list[dict]:
    global _consumable_cache, _consumable_by_id
    if _consumable_cache is None:
        _consumable_cache = _load_json_dir(CONSUMABLE_DIR)
        _consumable_by_id = {c["id"]: c for c in _consumable_cache if "id" in c}
    return _consumable_cache


def get_consumable(item_id: str) -> Optional[dict]:
    get_consumables()
    assert _consumable_by_id is not None
    return _consumable_by_id.get(item_id)


def instantiate_drop(drop_id: str, qty: int = 1) -> Optional[dict]:
    """Build a bag-ready item from drop id, equipment id, or consumable id."""
    template = get_drop(drop_id)
    if template is None:
        template = get_equipment_by_id(drop_id)
        if template is not None:
            item = dict(template)
            item.setdefault("type", "equipment")
            item.setdefault("enhance_level", 0)
            return item
        template = get_consumable(drop_id)
        if template is None:
            return None
        item = dict(template)
        item["qty"] = max(1, int(qty))
        return item
    item = dict(template)
    if item.get("type") == "consumable":
        # keep consumable type for protect/luck charms stored in drop tables
        pass
    item["qty"] = max(1, int(qty))
    return item


def get_craft_recipes() -> list[dict]:
    path = ITEM_DIR / "craft" / "recipes.json"
    if not path.exists():
        return []
    data = _load(path)
    return data if isinstance(data, list) else []


def get_craft_recipe(recipe_id: str) -> Optional[dict]:
    return next((r for r in get_craft_recipes() if r.get("id") == recipe_id), None)


def count_bag_item(user: dict, item_id: str) -> int:
    total = 0
    for it in user.get("bag") or []:
        if it.get("id") == item_id:
            total += int(it.get("qty", 1))
    return total


def consume_bag_items(user: dict, requirements: list[dict]) -> bool:
    """Remove qty of items by id from bag. Returns False if not enough."""
    # verify
    for req in requirements:
        if count_bag_item(user, req["item_id"]) < int(req["qty"]):
            return False
    for req in requirements:
        need = int(req["qty"])
        bag = user["bag"]
        i = 0
        while need > 0 and i < len(bag):
            it = bag[i]
            if it.get("id") != req["item_id"]:
                i += 1
                continue
            have = int(it.get("qty", 1))
            if have > need:
                it["qty"] = have - need
                need = 0
            else:
                need -= have
                bag.pop(i)
                continue
            i += 1
    return True


def _stack_into_bag(user: dict, item: dict) -> None:
    """Internal: stack item into an already-loaded user dict (no disk IO)."""
    kind = item.get("type")
    if kind in ("material", "food", "upgrade", "consumable") and item.get("id"):
        for existing in user["bag"]:
            if existing.get("type") == kind and existing.get("id") == item.get("id"):
                existing["qty"] = existing.get("qty", 1) + item.get("qty", 1)
                return
    entry = dict(item)
    entry.setdefault("qty", 1)
    user["bag"].append(entry)


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------

def load_users() -> list[dict]:
    return _load(USERS_FILE)


def get_user(user_id: str) -> Optional[dict]:
    return next((u for u in load_users() if u["id"] == user_id), None)


def _mutate_user(user_id: str, mutator):
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
    if item is None:
        return NOT_FOUND

    def do(user):
        if item.get("type") == "weapon" and _owns_weapon(user, item):
            return FORBIDDEN
        entry = dict(item)
        if entry.get("type") in ("weapon", "equipment"):
            entry.setdefault("enhance_level", 0)
        if entry.get("type") in ("material", "food", "upgrade", "consumable"):
            entry.setdefault("qty", 1)
            _stack_into_bag(user, entry)
        else:
            user["bag"].append(entry)
        return OK

    return _mutate_user(player_id, do)


def add_to_bag(player_id: str, item: dict, stack: bool = True):
    """Add an item to the bag. Materials/food with the same id stack by qty."""

    def do(user):
        if stack:
            _stack_into_bag(user, item)
        else:
            entry = dict(item)
            entry.setdefault("qty", 1)
            user["bag"].append(entry)
        return OK

    return _mutate_user(player_id, do)


def _take_one(bag: list, index: int, data: dict) -> int:
    qty = int(data.get("qty", 1))
    if qty > 1:
        data["qty"] = qty - 1
        return qty - 1
    bag.pop(index)
    return 0


def _drink(user: dict, data: dict, bag: list, index: int) -> dict:
    """Consume one food or stamina item and apply its out-of-combat effects."""
    before = int(user.get("the_luc", 0))
    stamina = int(data.get("heal_stamina") or data.get("heal") or 0)
    notes = []
    if stamina:
        user["the_luc"] = before + stamina
        notes.append(f"⚡ Thể lực {before} → {user['the_luc']} (+{stamina})")
    for key, label in (
        ("boostHP", "HP"), ("boostATK", "ATK"), ("boostDEF", "DEF"), ("boostSPD", "SPD"),
        ("boostEXP", "EXP"), ("boostPoints", "điểm"),
    ):
        amount = int(data.get(key) or 0)
        if not amount:
            continue
        field = {"boostHP": "hp", "boostATK": "atk", "boostDEF": "def", "boostSPD": "spd",
                 "boostEXP": "exp", "boostPoints": "points"}[key]
        user[field] = user.get(field, 0) + amount
        notes.append(f"+{amount} {label}")
    if data.get("boostKarma"):
        user["karma"] = max(0, user.get("karma", 0) + int(data["boostKarma"]))
        notes.append(f"karma {int(data['boostKarma']):+d}")
    left = _take_one(bag, index, data)
    if not notes:
        notes.append("Không có hiệu ứng thể lực.")
    return {
        "ok": True, "action": "consume", "name": data.get("name", "vật phẩm"),
        "stamina": stamina, "before": before, "the_luc": user.get("the_luc", 0),
        "left": left, "notes": notes,
    }


def set_item(player_id: str, bag_index: int):
    """Equip a weapon, drink food/stamina, or stow a combat consumable."""

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
            return {"ok": True, "action": "equip_weapon", "name": data.get("name")}
        if kind == "food" or (kind == "consumable" and data.get("subtype") == "stamina"):
            return _drink(user, data, bag, bag_index)
        if kind == "consumable":
            from . import equipment as eq
            eq.ensure_loadout(user)
            # Heal, buffs and charms wait on the belt. Stamina was handled above.
            if data.get("subtype") == "heal" or data.get("belt") is True:
                if not eq.stow_stack_on_belt(user, data):
                    return FORBIDDEN
                qty = int(data.get("qty", 1))
                bag.pop(bag_index)
                return {"ok": True, "action": "belt", "name": data.get("name"), "qty": qty,
                        "subtype": data.get("subtype")}
            return _drink(user, data, bag, bag_index)
        if kind == "equipment":
            return FORBIDDEN
        if kind == "upgrade":
            w = user.get("weapon")
            if w is None:
                return FORBIDDEN
            w["maxHP"] = weapon_max_hp(w) + data.get("boostHPweapon", 0)
            w["HP"] += data.get("boostHPweapon", 0)
            w["ATK"] += data.get("boostATKweapon", 0)
            w["DEF"] += data.get("boostDEFweapon", 0)
            w["SPD"] += data.get("boostSPDweapon", 0)
            w["usage"] = w.get("usage", 0) + data.get("usage", 0)
            left = _take_one(bag, bag_index, data)
            return {"ok": True, "action": "upgrade", "name": data.get("name"), "left": left}
        if kind == "material":
            return FORBIDDEN
        return FORBIDDEN

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


increase_hp = _increase_stat("hp")
increase_def = _increase_stat("def")
increase_atk = _increase_stat("atk")
increase_spd = _increase_stat("spd")


def spend_points(player_id: str, stat: str, points: int, per_point: int):
    if stat not in ("hp", "atk", "def", "spd") or points <= 0:
        return FORBIDDEN

    def do(user):
        if user["points"] < points:
            return FORBIDDEN
        user["points"] -= int(points)
        spent = dict(user.get("spent") or {})
        spent[stat] = int(spent.get(stat) or 0) + int(points)
        user["spent"] = spent
        if stat == "spd":
            user["spd"] = int(user.get("spd") or 0) + int(points) * int(per_point)
        return spent[stat]

    return _mutate_user(player_id, do)


def set_location(player_id: str, location_id: str):
    def do(user):
        user["locationID"] = location_id
        return OK

    return _mutate_user(player_id, do)


def set_exp(player_id: str, exp: float):
    def do(user):
        user["exp"] += exp
        events = []

        while user["exp"] >= exp_needed_for(user["level"]):
            user["exp"] -= exp_needed_for(user["level"])
            user["level"] += 1
            user["atk"] += 2 * user["level"]
            user["def"] += 2 * user["level"]
            user["hp"] += 5 * user["level"]
            user["spd"] += 1 * user["level"]
            user["points"] += LEVEL_UP_POINTS + 5 * user["level"]
            events.append(("level_up", user["level"]))

        weapon = user.get("weapon")
        if weapon is None:
            return events

        weapon.setdefault("usage", 0)
        weapon["exp"] = weapon.get("exp", 0) + exp

        while weapon["exp"] >= weapon_exp_needed_for(weapon["usage"]):
            weapon["exp"] -= weapon_exp_needed_for(weapon["usage"])
            weapon["usage"] += 1
            weapon["ATK"] += round(weapon["ATK"] * 0.01)
            weapon["DEF"] += round(weapon["DEF"] * 0.01)
            weapon["SPD"] += round(weapon["SPD"] * 0.01)
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
    return weapon.get("maxHP", weapon["HP"])


def decrease_health_weapon(player_id: str, remaining_hp_stat: float):
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
    def do(user):
        w = user.get("weapon")
        if w is None:
            return FORBIDDEN
        w["durability"] = MAX_DURABILITY
        w["HP"] = weapon_max_hp(w)
        w["maxHP"] = w["HP"]
        return dict(w)

    return _mutate_user(player_id, do)


def get_gold(player_id: str) -> int:
    user = get_user(player_id)
    if user is None:
        return 0
    return int(user.get("gold", 0))


def add_gold(player_id: str, delta: int) -> int:
    def do(user):
        user["gold"] = max(0, int(user.get("gold", 0)) + int(delta))
        return user["gold"]

    out = _mutate_user(player_id, do)
    return 0 if out in (NOT_FOUND, FORBIDDEN) else int(out)


def karma_up(player_id: str, amount: int = 1):
    def do(user):
        user["karma"] = max(0, user["karma"] + int(amount))
        return user["karma"]

    return _mutate_user(player_id, do)


def apply_effects(player_id: str, effects: dict):
    """Apply adventure/stat side-effects. Gold is returned to the caller
    (wallet is external); stamina/karma mutate the character."""

    def do(user):
        if "the_luc" in effects:
            user["the_luc"] = max(0, user.get("the_luc", 0) + int(effects["the_luc"]))
        if "karma" in effects:
            user["karma"] = max(0, user.get("karma", 0) + int(effects["karma"]))
        if "exp" in effects:
            user["exp"] = user.get("exp", 0) + float(effects["exp"])
        return {
            "the_luc": user.get("the_luc", 0),
            "karma": user.get("karma", 0),
            "gold_delta": int(effects.get("gold", 0)),
        }

    return _mutate_user(player_id, do)


def set_pending_event(player_id: str, event: Optional[dict]):
    def do(user):
        user["pending_event"] = event
        return OK

    return _mutate_user(player_id, do)


def append_history(player_id: str, entry: dict):
    def do(user):
        history = user.setdefault("history", [])
        history.append(entry)
        if len(history) > MAX_HISTORY:
            del history[:-MAX_HISTORY]
        return OK

    return _mutate_user(player_id, do)


def sell_monsters(player_id: str, indices: Optional[list[int]] = None):
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


def sell_materials(player_id: str, indices_1based: Optional[list[int]] = None):
    """Sell material (and optionally other non-weapon) bag entries.
    indices refer to positions among material items only when filtering,
    OR pass absolute bag indices via sell_bag_slots."""

    def do(user):
        bag = user["bag"]
        material_slots = [i for i, it in enumerate(bag) if it.get("type") == "material"]
        if not material_slots:
            return 0, 0
        if indices_1based is None:
            targets = list(material_slots)
        else:
            targets = []
            for n in indices_1based:
                if 1 <= n <= len(material_slots):
                    targets.append(material_slots[n - 1])
        count, total = 0, 0
        for slot in sorted(set(targets), reverse=True):
            it = bag[slot]
            qty = it.get("qty", 1)
            total += it.get("price", 0) * qty
            count += qty
            bag.pop(slot)
        return count, total

    return _mutate_user(player_id, do)
