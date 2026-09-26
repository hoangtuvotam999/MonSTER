"""
Equipment & consumable-belt helpers.

Slots (MMORPG-style):
  helmet, chest, pants, boots, cloak          — 1 each
  gloves[2], rings[2], bracelets[2]           — 2 each
Consumable belt: 5 quick-use slots for mid-fight / session items.
"""
from __future__ import annotations

from typing import Optional

from . import data_store

SINGLE_SLOTS = ("helmet", "chest", "pants", "boots", "cloak")
MULTI_SLOTS = {
    "glove": "gloves",
    "ring": "rings",
    "bracelet": "bracelets",
}
MULTI_CAPACITY = {"gloves": 2, "rings": 2, "bracelets": 2}
BELT_SIZE = 5

SLOT_LABELS = {
    "helmet": "Mũ",
    "chest": "Áo giáp",
    "pants": "Quần",
    "boots": "Giày",
    "cloak": "Áo choàng",
    "gloves": "Găng tay",
    "rings": "Nhẫn",
    "bracelets": "Vòng tay",
}


def empty_equipment() -> dict:
    return {
        "helmet": None,
        "chest": None,
        "pants": None,
        "boots": None,
        "cloak": None,
        "gloves": [None, None],
        "rings": [None, None],
        "bracelets": [None, None],
    }


def empty_belt() -> list:
    return [None] * BELT_SIZE


def ensure_loadout(character: dict) -> None:
    """Migrate older saves that lack equipment / belt fields."""
    if "equipment" not in character or not isinstance(character["equipment"], dict):
        character["equipment"] = empty_equipment()
    else:
        base = empty_equipment()
        base.update({k: character["equipment"].get(k, base[k]) for k in base})
        for key, cap in MULTI_CAPACITY.items():
            slots = base.get(key) or [None] * cap
            if not isinstance(slots, list):
                slots = [None] * cap
            while len(slots) < cap:
                slots.append(None)
            base[key] = slots[:cap]
        character["equipment"] = base
    if "consumables" not in character or not isinstance(character["consumables"], list):
        character["consumables"] = empty_belt()
    else:
        belt = list(character["consumables"])[:BELT_SIZE]
        while len(belt) < BELT_SIZE:
            belt.append(None)
        character["consumables"] = belt


def iter_equipped(character: dict):
    ensure_loadout(character)
    eq = character["equipment"]
    for slot in SINGLE_SLOTS:
        item = eq.get(slot)
        if item:
            yield slot, item
    for key in ("gloves", "rings", "bracelets"):
        for i, item in enumerate(eq.get(key) or []):
            if item:
                yield f"{key}:{i}", item


def equipment_bonuses(character: dict) -> dict:
    """Aggregate flat/multiplier bonuses from all worn gear + set bonuses."""
    ensure_loadout(character)
    total = {
        "hp": 0, "atk": 0, "def": 0, "spd": 0,
        "dmgBonus": 1.0, "defBonus": 1.0, "hpBonus": 1.0, "spdBonus": 1.0,
        "ArmorPiercing": 1.0,
        "mana_gain": 0,  # extra mana per attack from bracelets etc.
        "tags": [],
        "sets": [],
    }
    set_counts: dict[str, int] = {}
    ap_values = []

    for _, item in iter_equipped(character):
        total["hp"] += int(item.get("hp", 0))
        total["atk"] += int(item.get("atk", 0))
        total["def"] += int(item.get("def", 0))
        total["spd"] += int(item.get("spd", 0))
        for key in ("dmgBonus", "defBonus", "hpBonus", "spdBonus"):
            total[key] *= float(item.get(key, 1) or 1)
        ap_values.append(float(item.get("ArmorPiercing", 1)))
        total["tags"].extend(item.get("tags") or [])
        if item.get("id") == "brac_mana" or "mage" in (item.get("tags") or []):
            total["mana_gain"] += 5
        sid = item.get("set")
        if sid:
            set_counts[sid] = set_counts.get(sid, 0) + 1

    if ap_values:
        # Best pierce wins (lowest multiplier)
        total["ArmorPiercing"] = min(ap_values)

    sets_catalog = data_store.get_equipment_sets()
    for sid, count in set_counts.items():
        info = sets_catalog.get(sid)
        if not info:
            continue
        need = int(info.get("pieces", 99))
        if count >= need:
            bonus = info.get("bonus") or {}
            total["hp"] += int(bonus.get("hp", 0))
            total["atk"] += int(bonus.get("atk", 0))
            total["def"] += int(bonus.get("def", 0))
            total["spd"] += int(bonus.get("spd", 0))
            total["sets"].append({
                "id": sid,
                "name": info.get("name", sid),
                "desc": bonus.get("desc", ""),
            })
    return total


def equip_from_bag(player_id: str, bag_index_0: int, multi_slot_index: Optional[int] = None):
    """Equip an equipment item from the bag into its slot.
    For glove/ring/bracelet, multi_slot_index is 0 or 1 (default: first empty)."""

    def do(user):
        ensure_loadout(user)
        bag = user["bag"]
        if not (0 <= bag_index_0 < len(bag)):
            return data_store.NOT_FOUND
        item = bag[bag_index_0]
        if item.get("type") != "equipment":
            return data_store.FORBIDDEN
        slot = item.get("slot")
        eq = user["equipment"]

        if slot in SINGLE_SLOTS:
            old = eq.get(slot)
            eq[slot] = dict(item)
            bag.pop(bag_index_0)
            if old:
                bag.append(old)
            return {"ok": True, "slot": slot, "item": eq[slot], "replaced": old}
        if slot in MULTI_SLOTS:
            key = MULTI_SLOTS[slot]
            slots = eq[key]
            idx = multi_slot_index
            if idx is None:
                idx = next((i for i, s in enumerate(slots) if s is None), None)
                if idx is None:
                    idx = 0  # replace first
            if not (0 <= idx < len(slots)):
                return data_store.FORBIDDEN
            old = slots[idx]
            slots[idx] = dict(item)
            bag.pop(bag_index_0)
            if old:
                bag.append(old)
            return {"ok": True, "slot": f"{key}:{idx}", "item": slots[idx], "replaced": old}
        return data_store.FORBIDDEN

    return data_store._mutate_user(player_id, do)


def unequip(player_id: str, slot_key: str):
    """Unequip by key: 'helmet' or 'gloves:0' / 'rings:1'."""

    def do(user):
        ensure_loadout(user)
        eq = user["equipment"]
        if ":" in slot_key:
            key, idx_s = slot_key.split(":", 1)
            idx = int(idx_s)
            slots = eq.get(key)
            if not slots or not (0 <= idx < len(slots)) or slots[idx] is None:
                return data_store.NOT_FOUND
            item = slots[idx]
            slots[idx] = None
            user["bag"].append(item)
            return {"ok": True, "item": item}
        if slot_key not in SINGLE_SLOTS or eq.get(slot_key) is None:
            return data_store.NOT_FOUND
        item = eq[slot_key]
        eq[slot_key] = None
        user["bag"].append(item)
        return {"ok": True, "item": item}

    return data_store._mutate_user(player_id, do)


def set_belt_slot(player_id: str, belt_index_0: int, bag_index_0: Optional[int]):
    """Move a consumable from bag → belt slot, or clear belt slot (bag_index None)."""

    def do(user):
        ensure_loadout(user)
        belt = user["consumables"]
        if not (0 <= belt_index_0 < BELT_SIZE):
            return data_store.FORBIDDEN
        if bag_index_0 is None:
            old = belt[belt_index_0]
            belt[belt_index_0] = None
            if old:
                # return remaining qty to bag
                data_store._stack_into_bag(user, old)
            return {"ok": True, "cleared": old}
        bag = user["bag"]
        if not (0 <= bag_index_0 < len(bag)):
            return data_store.NOT_FOUND
        item = bag[bag_index_0]
        if item.get("type") not in ("consumable", "food") or item.get("belt") is False:
            # allow food/consumable; prefer catalog belt flag when present
            if item.get("type") not in ("consumable", "food"):
                return data_store.FORBIDDEN
        old = belt[belt_index_0]
        # take 1 qty into belt (stack stays in bag if qty>1)
        entry = dict(item)
        entry["qty"] = 1
        qty = item.get("qty", 1)
        if qty > 1:
            item["qty"] = qty - 1
        else:
            bag.pop(bag_index_0)
        belt[belt_index_0] = entry
        if old:
            data_store._stack_into_bag(user, old)
        return {"ok": True, "item": entry, "replaced": old}

    return data_store._mutate_user(player_id, do)


def consume_belt_charge(character: dict, belt_index: int) -> Optional[dict]:
    """Remove one use from a belt slot (mutates character in-memory)."""
    ensure_loadout(character)
    belt = character["consumables"]
    if not (0 <= belt_index < len(belt)) or belt[belt_index] is None:
        return None
    item = belt[belt_index]
    qty = item.get("qty", 1)
    used = dict(item)
    if qty > 1:
        item["qty"] = qty - 1
    else:
        belt[belt_index] = None
    return used
