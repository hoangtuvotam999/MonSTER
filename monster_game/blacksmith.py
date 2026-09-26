"""
Blacksmith — enhance weapons & equipment with stones + materials.

Success is RNG. Display level as +N on the item.
On failure, level resets to +1 unless a protection scroll changes that.
"""
from __future__ import annotations

import random
from typing import Optional

from . import data_store

_cfg_cache = None


def get_config() -> dict:
    global _cfg_cache
    if _cfg_cache is None:
        path = data_store.ITEM_DIR / "blacksmith.json"
        _cfg_cache = data_store._load(path) if path.exists() else {}
    return _cfg_cache


def item_tier(item: dict) -> str:
    return str(item.get("tier") or "A").upper()


def enhance_level(item: dict) -> int:
    return int(item.get("enhance_level") or 0)


def display_name(item: dict) -> str:
    lvl = enhance_level(item)
    name = item.get("name", "?")
    return f"{name} +{lvl}" if lvl > 0 else name


def success_rate(target_level: int) -> float:
    cfg = get_config()
    rates = cfg.get("success_rate") or {}
    key = str(min(target_level, int(cfg.get("max_enhance", 15))))
    if key in rates:
        return float(rates[key])
    # beyond table: keep decaying
    return max(0.01, 0.015 * (0.7 ** max(0, target_level - 15)))


def cost_for(item: dict) -> dict:
    """What it takes to attempt +1 from current level."""
    cfg = get_config()
    tier = item_tier(item)
    cur = enhance_level(item)
    nxt = cur + 1
    stone_id = f"enhance_stone_{tier.lower()}"
    stones = int((cfg.get("stone_cost") or {}).get(tier, 1))
    # more stones at higher +
    stones = stones + max(0, cur // 3)
    gold = int((cfg.get("gold_base") or {}).get(tier, 200))
    gold += int((cfg.get("gold_per_level") or {}).get(tier, 100)) * nxt
    mats = list((cfg.get("mat_extra") or {}).get(tier) or [])
    return {
        "next_level": nxt,
        "rate": success_rate(nxt),
        "gold": gold,
        "stones": [{"item_id": stone_id, "qty": stones}],
        "materials": mats,
        "tier": tier,
    }


def _apply_stat_gain(item: dict, levels_gained: int = 1) -> None:
    """Permanently raise base combat stats on the item for each success."""
    if levels_gained <= 0:
        return
    cfg = get_config()
    pct = float((cfg.get("stat_bonus_per_level") or {}).get(item_tier(item), 0.04))
    kind = item.get("type")
    if kind == "weapon":
        for key in ("HP", "ATK", "DEF", "SPD"):
            if key in item:
                gain = max(1, round(item[key] * pct * levels_gained))
                item[key] = int(item[key] + gain)
        if "maxHP" in item:
            item["maxHP"] = max(item["maxHP"], item.get("HP", item["maxHP"]))
    elif kind == "equipment":
        for key in ("hp", "atk", "def", "spd"):
            if key in item and item[key]:
                # flat gear: grow by pct of abs value, at least 1 if non-zero
                base = item[key]
                gain = max(1, round(abs(base) * pct * levels_gained))
                item[key] = int(base + (gain if base >= 0 else -gain))


def _resolve_fail_level(current: int, protect: Optional[dict], default_to: int = 1) -> int:
    if not protect:
        return max(1, int(default_to))
    mode = protect.get("mode")
    if mode == "keep":
        return current
    if mode == "drop_one":
        return max(1, current - 1)
    if mode == "floor":
        # Fail → drop to insured floor, but never rise on failure
        floor = max(1, int(protect.get("floor", 1)))
        if current > floor:
            return floor
        return max(1, current)
    return max(1, int(default_to))


def _find_enhance_target(user: dict, where: str, index: Optional[int]):
    """
    where: 'weapon' | 'equipment:<slot>' | 'equipment:gloves:0' | 'bag'
    index: 0-based bag index when where=='bag'
    """
    if where == "weapon":
        return user.get("weapon"), ("weapon", None)
    if where == "bag":
        bag = user.get("bag") or []
        if index is None or not (0 <= index < len(bag)):
            return None, None
        it = bag[index]
        if it.get("type") not in ("weapon", "equipment"):
            return None, None
        return it, ("bag", index)
    if where.startswith("equipment:"):
        parts = where.split(":")
        # equipment:helmet | equipment:gloves:0
        from . import equipment as eq
        eq.ensure_loadout(user)
        e = user["equipment"]
        if len(parts) == 2:
            slot = parts[1]
            return e.get(slot), ("equipment", slot)
        if len(parts) == 3:
            key, idx_s = parts[1], parts[2]
            idx = int(idx_s)
            slots = e.get(key) or []
            if 0 <= idx < len(slots):
                return slots[idx], ("equipment", f"{key}:{idx}")
    return None, None


def enhance(player_id: str, where: str = "weapon", bag_index_0: Optional[int] = None,
            balance: int = 0, protect_bag_index_0: Optional[int] = None,
            rng: Optional[random.Random] = None) -> dict:
    """
    Attempt to raise enhance_level by 1.
    Returns dict: ok, success, message, level_before/after, rate, cost, used_protect...
    Caller deducts gold when ok (attempt started).
    """
    rng = rng or random.Random()
    cfg = get_config()
    max_e = int(cfg.get("max_enhance", 15))
    default_fail = int(cfg.get("fail_default_to", 1))

    user = data_store.get_user(player_id)
    if user is None:
        return {"ok": False, "reason": "no_character", "message": "Chưa có nhân vật"}

    item, loc = _find_enhance_target(user, where, bag_index_0)
    if item is None:
        return {"ok": False, "reason": "no_item", "message": "Không tìm thấy trang bị để cường hóa"}

    cur = enhance_level(item)
    if cur >= max_e:
        return {"ok": False, "reason": "maxed", "message": f"Đã đạt +{max_e}"}

    quote = cost_for(item)
    if balance < quote["gold"]:
        return {"ok": False, "reason": "not_enough_gold", "message": "Không đủ vàng",
                "cost": quote}

    # verify materials in bag
    need = list(quote["stones"]) + list(quote["materials"])
    for req in need:
        if data_store.count_bag_item(user, req["item_id"]) < int(req["qty"]):
            drop = data_store.get_drop(req["item_id"]) or data_store.get_consumable(req["item_id"])
            return {"ok": False, "reason": "missing_mats",
                    "message": f"Thiếu {(drop or {}).get('name', req['item_id'])} ×{req['qty']}",
                    "cost": quote}

    protect = None
    protect_item_name = None

    def do(u):
        nonlocal protect, protect_item_name
        target, _loc = _find_enhance_target(u, where, bag_index_0)
        if target is None:
            return data_store.NOT_FOUND
        # consume mats
        if not data_store.consume_bag_items(u, need):
            return data_store.FORBIDDEN
        # optional protect scroll from bag
        if protect_bag_index_0 is not None:
            bag = u["bag"]
            # index may have shifted after consume — find by scanning protect items instead if OOB
            idx = protect_bag_index_0
            if not (0 <= idx < len(bag)) or bag[idx].get("subtype") != "enhance_protect":
                # find first protect scroll
                idx = next((i for i, it in enumerate(bag) if it.get("subtype") == "enhance_protect"), None)
            if idx is not None and 0 <= idx < len(bag) and bag[idx].get("subtype") == "enhance_protect":
                protect = dict(bag[idx].get("protect") or {})
                protect_item_name = bag[idx].get("name")
                qty = bag[idx].get("qty", 1)
                if qty > 1:
                    bag[idx]["qty"] = qty - 1
                else:
                    bag.pop(idx)

        before = enhance_level(target)
        rate = success_rate(before + 1)
        rolled = rng.random()
        success = rolled < rate
        if success:
            target["enhance_level"] = before + 1
            _apply_stat_gain(target, 1)
            after = target["enhance_level"]
            msg = f"Đinh! Thành công → {display_name(target)} ({rate*100:.0f}% / roll {rolled:.2f})"
        else:
            after = _resolve_fail_level(before, protect, default_fail)
            target["enhance_level"] = after
            # do not remove previously gained stats on fail (keep power from past successes)
            msg = f"Vỡ! Thất bại → {display_name(target)} (tỉ lệ {rate*100:.0f}%)"
            if protect_item_name:
                msg += f" — đã dùng {protect_item_name}"
        return {
            "ok": True,
            "success": success,
            "level_before": before,
            "level_after": after,
            "rate": rate,
            "roll": rolled,
            "message": msg,
            "item_name": target.get("name"),
            "display": display_name(target),
            "cost": quote,
            "protect_used": protect_item_name,
        }

    out = data_store._mutate_user(player_id, do)
    if out in (data_store.NOT_FOUND, data_store.FORBIDDEN):
        return {"ok": False, "reason": "failed", "message": "Không thể cường hóa", "cost": quote}
    out["gold_cost"] = quote["gold"]
    return out
