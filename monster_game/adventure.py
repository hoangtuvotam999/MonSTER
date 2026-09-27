"""
Adventure events — text-based encounters that fire after a hunt.

Maps declare weighted `events` with player `actions` and weighted
`outcomes`. The core keeps a `pending_event` on the character until the
caller resolves a choice via `resolve_event`.
"""
from __future__ import annotations

import random
import time
from typing import Optional

from . import data_store


def _weighted_choice(items: list[dict], weight_key: str = "weight") -> Optional[dict]:
    if not items:
        return None
    weights = [max(0, float(i.get(weight_key, 1))) for i in items]
    if sum(weights) <= 0:
        return random.choice(items)
    return random.choices(items, weights=weights, k=1)[0]


def _chance_choice(outcomes: list[dict]) -> Optional[dict]:
    """Pick one outcome using `chance` weights (need not sum to 1)."""
    if not outcomes:
        return None
    weights = [max(0.0, float(o.get("chance", 1))) for o in outcomes]
    if sum(weights) <= 0:
        return random.choice(outcomes)
    return random.choices(outcomes, weights=weights, k=1)[0]


def grant_drops(player_id: str, drop_specs: list[dict], rng: Optional[random.Random] = None) -> list[dict]:
    """Roll qty for each drop spec `{item_id, chance?, min, max}` and put in bag.
    Specs without `chance` always grant. Returns list of granted item dicts."""
    rng = rng or random.Random()
    granted = []
    for spec in drop_specs or []:
        chance = spec.get("chance")
        if chance is not None and rng.random() > float(chance):
            continue
        lo = int(spec.get("min", 1))
        hi = int(spec.get("max", lo))
        qty = rng.randint(lo, max(lo, hi))
        item = data_store.instantiate_drop(spec["item_id"], qty)
        if item is None:
            continue
        data_store.add_to_bag(player_id, item)
        granted.append(item)
    return granted


def _owns_gear(user: dict, item: dict) -> bool:
    iid = item.get("id")
    name = item.get("name")

    def same(other: Optional[dict]) -> bool:
        if not other:
            return False
        if iid is not None and other.get("id") == iid:
            return True
        return bool(name) and other.get("name") == name

    if same(user.get("weapon")):
        return True
    if any(same(it) for it in user.get("bag") or []):
        return True
    from . import equipment as eq
    eq.ensure_loadout(user)
    return any(same(it) for _slot, it in eq.iter_equipped(user))


def _roll_ranked_drop(player_id: str, monster_template: dict, kind: str,
                      rng: random.Random) -> list[dict]:
    """One weapon or one armor piece. Higher ranks are rarer, and never above the monster."""
    from . import tiers as tier_mod

    cap = tier_mod.monster_item_cap(monster_template.get("Tier"))
    if cap is None:
        return []
    eligible = [row for row in tier_mod.drop_tiers() if int(row["rank"]) <= cap]
    if not eligible:
        return []
    chosen = rng.choices(eligible, weights=[float(row["drop_chance"]) for row in eligible], k=1)[0]
    if rng.random() > float(chosen["drop_chance"]):
        return []
    user = data_store.get_user(player_id) or {}
    if kind == "weapon":
        pool = [
            weapon for weapon in data_store.get_weapons()
            if tier_mod.same_tier(weapon, chosen)
            and int(weapon.get("id") or 0) != 90
            and not _owns_gear(user, weapon)
        ]
    else:
        pool = [
            piece for piece in data_store.get_equipment()
            if tier_mod.same_tier(piece, chosen) and not _owns_gear(user, piece)
        ]
    if not pool:
        return []
    template = rng.choice(pool)
    item = dict(template)
    item["qty"] = 1
    item["enhance_level"] = 0
    if kind == "weapon":
        item["type"] = "weapon"
        item["durability"] = 100
        item["usage"] = 0
        item["exp"] = 0
    else:
        item.setdefault("type", "equipment")
    if data_store.add_to_bag(player_id, item, stack=False) in (data_store.NOT_FOUND, data_store.FORBIDDEN):
        return []
    return [item]


def roll_weapon_drop(player_id: str, monster_template: dict,
                     rng: Optional[random.Random] = None) -> list[dict]:
    """Rare weapon on a winning fight. Skips Kiếm Lời Thoại and any copy already owned."""
    rng = rng or random.Random()
    return _roll_ranked_drop(player_id, monster_template, "weapon", rng)


def roll_armor_drop(player_id: str, monster_template: dict,
                    rng: Optional[random.Random] = None) -> list[dict]:
    """Rare armor on a winning fight. Skips a piece the player already has."""
    rng = rng or random.Random()
    return _roll_ranked_drop(player_id, monster_template, "armor", rng)


def roll_monster_drops(player_id: str, monster_template: dict,
                       rng: Optional[random.Random] = None) -> list[dict]:
    """Grant the monster's own materials, then one weapon roll and one armor roll."""
    rng = rng or random.Random()
    granted = grant_drops(player_id, monster_template.get("drops") or [], rng=rng)
    granted.extend(roll_weapon_drop(player_id, monster_template, rng))
    granted.extend(roll_armor_drop(player_id, monster_template, rng))
    return granted


def maybe_start_event(player_id: str, location: dict,
                      rng: Optional[random.Random] = None) -> Optional[dict]:
    """After a hunt: chance to start a map event. Returns pending event
    payload (also stored on the character), or None."""
    rng = rng or random.Random()
    user = data_store.get_user(player_id)
    if user is None:
        return None
    if user.get("pending_event"):
        return None  # finish the current event before starting another
    events = location.get("events") or []
    if not events:
        return None
    chance = float(location.get("event_chance", 0.4))
    if rng.random() > chance:
        return None
    chosen = _weighted_choice(events, "weight")
    if chosen is None:
        return None

    pending = {
        "id": chosen["id"],
        "title": chosen["title"],
        "intro": chosen["intro"],
        "actions": list(chosen.get("actions") or []),
        "outcomes": chosen.get("outcomes") or {},
        "location_id": location.get("ID"),
        "location_name": location.get("name"),
        "started_at": int(time.time() * 1000),
    }
    data_store.set_pending_event(player_id, pending)

    data_store.append_history(player_id, {
        "ts": pending["started_at"],
        "kind": "adventure_start",
        "location": pending["location_name"],
        "event_id": pending["id"],
        "title": pending["title"],
        "lines": [
            f"📍 {pending['location_name']}",
            f"✨ {pending['title']}",
            pending["intro"],
            "Hành động: " + " · ".join(
                f"[{a['id']}] {a['label']}" for a in pending["actions"]
            ),
        ],
    })
    return pending


def get_pending_event(player_id: str) -> Optional[dict]:
    user = data_store.get_user(player_id)
    if user is None:
        return None
    return user.get("pending_event")


def resolve_event(player_id: str, action_id: str,
                  rng: Optional[random.Random] = None) -> dict:
    """Resolve the character's pending adventure event with `action_id`.
    Returns a result dict for rendering; clears pending_event."""
    rng = rng or random.Random()
    user = data_store.get_user(player_id)
    if user is None:
        return {"ok": False, "reason": "no_character"}
    pending = user.get("pending_event")
    if not pending:
        return {"ok": False, "reason": "no_event"}

    actions = {a["id"]: a for a in pending.get("actions") or []}
    if action_id not in actions:
        return {
            "ok": False,
            "reason": "invalid_action",
            "actions": list(actions.keys()),
        }

    outcome_table = (pending.get("outcomes") or {}).get(action_id) or []
    outcome = _chance_choice(outcome_table)
    if outcome is None:
        outcome = {"kind": "nothing", "log": "Chẳng có gì xảy ra."}

    effects = outcome.get("effects") or {}
    effect_result = data_store.apply_effects(player_id, effects)
    if effect_result in (data_store.NOT_FOUND, data_store.FORBIDDEN):
        effect_result = {"the_luc": 0, "karma": 0, "gold_delta": 0}

    granted = grant_drops(player_id, outcome.get("drops") or [], rng=rng)

    action_label = actions[action_id]["label"]
    lines = [
        f"📍 {pending.get('location_name', '')}",
        f"✨ {pending['title']}",
        f"▶ Bạn chọn: {action_label}",
        outcome.get("log") or "",
    ]
    if outcome.get("combat_hint"):
        lines.append(outcome["combat_hint"])
    if effects.get("the_luc"):
        delta = effects["the_luc"]
        lines.append(f"⚡ Thể lực {'+' if delta > 0 else ''}{delta}")
    if effects.get("karma"):
        delta = effects["karma"]
        lines.append(f"😈 Karma {'+' if delta > 0 else ''}{delta}")
    gold_delta = effect_result.get("gold_delta", 0) if isinstance(effect_result, dict) else 0
    if gold_delta:
        lines.append(f"💰 {'+' if gold_delta > 0 else ''}{gold_delta} vàng")
    for item in granted:
        qty = item.get("qty", 1)
        lines.append(f"🎁 Nhận {item['name']} ×{qty}")

    result = {
        "ok": True,
        "event_id": pending["id"],
        "title": pending["title"],
        "action_id": action_id,
        "action_label": action_label,
        "kind": outcome.get("kind"),
        "log": outcome.get("log"),
        "combat_hint": outcome.get("combat_hint"),
        "effects": effects,
        "gold_delta": gold_delta,
        "drops": granted,
        "location_name": pending.get("location_name"),
        "lines": [ln for ln in lines if ln],
        "the_luc": effect_result.get("the_luc") if isinstance(effect_result, dict) else None,
        "karma": effect_result.get("karma") if isinstance(effect_result, dict) else None,
    }

    data_store.set_pending_event(player_id, None)
    data_store.append_history(player_id, {
        "ts": int(time.time() * 1000),
        "kind": "adventure",
        "location": pending.get("location_name"),
        "event_id": pending["id"],
        "title": pending["title"],
        "action": action_id,
        "outcome": outcome.get("kind"),
        "lines": result["lines"],
    })
    return result
