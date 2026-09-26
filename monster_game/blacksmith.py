"""
Blacksmith — enhance weapons & equipment with stones + materials.

Success is RNG (base rate by target +N, plus luck charms capped at +36%).
Display level as +N on the item.
Cost scales with current enhance level and item tier.
On failure, level resets to +1 unless a % protect scroll keeps a fraction
of the original level (25% / 50% / 60%).
"""
from __future__ import annotations

import random
from typing import Optional

from . import data_store

_cfg_cache = None

MAX_LUCK_BONUS = 0.36  # absolute +36% success, hard cap


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
    return max(0.01, 0.015 * (0.7 ** max(0, target_level - 15)))


def effective_rate(base: float, luck_bonus: float = 0.0) -> float:
    """Base enhance rate + luck charms, luck capped at MAX_LUCK_BONUS."""
    luck = max(0.0, min(float(luck_bonus), MAX_LUCK_BONUS))
    return max(0.0, min(1.0, float(base) + luck))


def cost_for(item: dict) -> dict:
    """Cost rises with enhance level; base amounts follow item tier."""
    cfg = get_config()
    tier = item_tier(item)
    cur = enhance_level(item)
    nxt = cur + 1
    stone_id = f"enhance_stone_{tier.lower()}"
    stones = int((cfg.get("stone_cost") or {}).get(tier, 1))
    stones += int((cfg.get("stone_per_level") or {}).get(tier, 0)) * cur
    gold = int((cfg.get("gold_cost") or cfg.get("gold_base") or {}).get(tier, 200))
    gold += int((cfg.get("gold_per_level") or {}).get(tier, 100)) * nxt
    mats = []
    for req in (cfg.get("mat_extra") or {}).get(tier) or []:
        qty = int(req.get("qty", 1))
        qty += int((cfg.get("mat_per_level") or {}).get(tier, 0)) * cur
        mats.append({"item_id": req["item_id"], "qty": max(1, qty)})
    base = success_rate(nxt)
    return {
        "next_level": nxt,
        "rate": base,
        "rate_with_max_luck": effective_rate(base, MAX_LUCK_BONUS),
        "gold": gold,
        "stones": [{"item_id": stone_id, "qty": max(1, stones)}],
        "materials": mats,
        "tier": tier,
        "max_luck": MAX_LUCK_BONUS,
    }


def _apply_stat_gain(item: dict, levels_gained: int = 1) -> None:
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
                base = item[key]
                gain = max(1, round(abs(base) * pct * levels_gained))
                item[key] = int(base + (gain if base >= 0 else -gain))


def _resolve_fail_level(current: int, protect: Optional[dict], default_to: int = 1) -> int:
    """
    Protect scrolls keep a % of the original (pre-fail) level.
    keep_pct: 0.25 / 0.50 / 0.60 → after = max(1, round(current * keep_pct))
    """
    if not protect:
        return max(1, int(default_to))
    if "keep_pct" in protect:
        ratio = float(protect["keep_pct"])
        kept = max(1, int(round(current * ratio)))
        return max(1, min(current, kept))
    mode = protect.get("mode")
    if mode == "keep":
        return current
    if mode == "drop_one":
        return max(1, current - 1)
    if mode == "floor":
        floor = max(1, int(protect.get("floor", 1)))
        if current > floor:
            return floor
        return max(1, current)
    return max(1, int(default_to))


def _find_enhance_target(user: dict, where: str, index: Optional[int]):
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


def _consume_bag_index(bag: list, idx: int) -> Optional[dict]:
    if not (0 <= idx < len(bag)):
        return None
    it = bag[idx]
    qty = it.get("qty", 1)
    taken = dict(it)
    if qty > 1:
        bag[idx]["qty"] = qty - 1
    else:
        bag.pop(idx)
    return taken


def _consume_luck_by_ids(bag: list, item_ids: list[str]) -> tuple[float, list[str]]:
    """Consume luck charms matching ids (in order), cap bonus at MAX_LUCK_BONUS."""
    bonus = 0.0
    names: list[str] = []
    for want_id in item_ids:
        if bonus >= MAX_LUCK_BONUS:
            break
        idx = next((i for i, it in enumerate(bag)
                    if it.get("id") == want_id and it.get("subtype") == "enhance_luck"), None)
        if idx is None:
            continue
        it = bag[idx]
        add = float(it.get("luck_bonus") or 0)
        if add <= 0:
            continue
        _consume_bag_index(bag, idx)
        bonus += add
        names.append(it.get("name", "charm"))
    return min(bonus, MAX_LUCK_BONUS), names


def enhance(player_id: str, where: str = "weapon", bag_index_0: Optional[int] = None,
            balance: int = 0, protect_bag_index_0: Optional[int] = None,
            luck_bag_indices_0: Optional[list[int]] = None,
            rng: Optional[random.Random] = None) -> dict:
    """
    Attempt to raise enhance_level by 1.
    Luck charms add success rate up to +36%. Protect keeps keep_pct of level on fail.
    Caller deducts gold when ok.
    """
    rng = rng or random.Random()
    cfg = get_config()
    max_e = int(cfg.get("max_enhance", 15))
    default_fail = int(cfg.get("fail_default_to", 1))

    user = data_store.get_user(player_id)
    if user is None:
        return {"ok": False, "reason": "no_character", "message": "Chưa có nhân vật"}

    item, _loc = _find_enhance_target(user, where, bag_index_0)
    if item is None:
        return {"ok": False, "reason": "no_item", "message": "Không tìm thấy trang bị để cường hóa"}

    cur = enhance_level(item)
    if cur >= max_e:
        return {"ok": False, "reason": "maxed", "message": f"Đã đạt +{max_e}"}

    quote = cost_for(item)
    if balance < quote["gold"]:
        return {"ok": False, "reason": "not_enough_gold", "message": "Không đủ vàng",
                "cost": quote}

    need = list(quote["stones"]) + list(quote["materials"])
    for req in need:
        if data_store.count_bag_item(user, req["item_id"]) < int(req["qty"]):
            drop = data_store.get_drop(req["item_id"]) or data_store.get_consumable(req["item_id"])
            return {"ok": False, "reason": "missing_mats",
                    "message": f"Thiếu {(drop or {}).get('name', req['item_id'])} ×{req['qty']}",
                    "cost": quote}

    # Snapshot luck / protect ids before bag shifts from mat consume
    bag0 = user.get("bag") or []
    luck_ids: list[str] = []
    for idx in luck_bag_indices_0 or []:
        if 0 <= idx < len(bag0) and bag0[idx].get("subtype") == "enhance_luck":
            it = bag0[idx]
            # expand stacks so qty>1 can fill the +36% cap
            for _ in range(max(1, int(it.get("qty", 1)))):
                luck_ids.append(it["id"])
    protect_id = None
    if protect_bag_index_0 is not None and 0 <= protect_bag_index_0 < len(bag0):
        if bag0[protect_bag_index_0].get("subtype") == "enhance_protect":
            protect_id = bag0[protect_bag_index_0].get("id")

    protect = None
    protect_item_name = None
    luck_bonus = 0.0
    luck_names: list[str] = []

    def do(u):
        nonlocal protect, protect_item_name, luck_bonus, luck_names
        target, _ = _find_enhance_target(u, where, bag_index_0)
        if target is None:
            return data_store.NOT_FOUND
        if not data_store.consume_bag_items(u, need):
            return data_store.FORBIDDEN

        bag = u["bag"]
        luck_bonus, luck_names = _consume_luck_by_ids(bag, luck_ids)

        if protect_id:
            idx = next((i for i, it in enumerate(bag)
                        if it.get("id") == protect_id and it.get("subtype") == "enhance_protect"), None)
            if idx is not None:
                taken = _consume_bag_index(bag, idx)
                if taken:
                    protect = dict(taken.get("protect") or {})
                    protect_item_name = taken.get("name")
        elif protect_bag_index_0 is not None:
            idx = next((i for i, it in enumerate(bag) if it.get("subtype") == "enhance_protect"), None)
            if idx is not None:
                taken = _consume_bag_index(bag, idx)
                if taken:
                    protect = dict(taken.get("protect") or {})
                    protect_item_name = taken.get("name")

        before = enhance_level(target)
        base = success_rate(before + 1)
        rate = effective_rate(base, luck_bonus)
        rolled = rng.random()
        success = rolled < rate
        if success:
            target["enhance_level"] = before + 1
            _apply_stat_gain(target, 1)
            after = target["enhance_level"]
            msg = (f"Đinh! Thành công → {display_name(target)} "
                   f"(base {base*100:.0f}% + luck {luck_bonus*100:.0f}% = {rate*100:.0f}% / roll {rolled:.2f})")
        else:
            after = _resolve_fail_level(before, protect, default_fail)
            target["enhance_level"] = after
            msg = f"Vỡ! Thất bại → {display_name(target)} (tỉ lệ {rate*100:.0f}%)"
            if protect_item_name and protect:
                pct = int(float(protect.get("keep_pct", 0)) * 100)
                msg += f" — {protect_item_name} giữ ~{pct}% cấp gốc"
            if luck_names:
                msg += f" · đã ép may: {', '.join(luck_names)}"
        return {
            "ok": True,
            "success": success,
            "level_before": before,
            "level_after": after,
            "rate_base": base,
            "luck_bonus": luck_bonus,
            "rate": rate,
            "roll": rolled,
            "message": msg,
            "item_name": target.get("name"),
            "display": display_name(target),
            "cost": quote,
            "protect_used": protect_item_name,
            "luck_used": luck_names,
        }

    out = data_store._mutate_user(player_id, do)
    if out in (data_store.NOT_FOUND, data_store.FORBIDDEN):
        return {"ok": False, "reason": "failed", "message": "Không thể cường hóa", "cost": quote}
    out["gold_cost"] = quote["gold"]
    return out
