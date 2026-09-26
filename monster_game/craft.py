"""
Crafting — turn materials into equipment (and keep materials meaningful).

Recipes live in data/item/craft/recipes.json.
Gold cost is returned to the caller (wallet is external), same as the shop.
"""
from __future__ import annotations

from typing import Optional

from . import data_store


class CraftResult:
    def __init__(self, ok: bool, message: str, cost: int = 0, item: Optional[dict] = None,
                 recipe: Optional[dict] = None):
        self.ok = ok
        self.message = message
        self.cost = cost
        self.item = item
        self.recipe = recipe

    def __repr__(self):
        return f"CraftResult(ok={self.ok}, message={self.message!r}, cost={self.cost})"


def list_recipes(tier: Optional[str] = None) -> list[dict]:
    recipes = data_store.get_craft_recipes()
    if tier:
        recipes = [r for r in recipes if r.get("tier") == tier]
    return recipes


def can_craft(player_id: str, recipe_id: str, balance: int = 0) -> dict:
    user = data_store.get_user(player_id)
    recipe = data_store.get_craft_recipe(recipe_id)
    if user is None:
        return {"ok": False, "reason": "no_character"}
    if recipe is None:
        return {"ok": False, "reason": "no_recipe"}
    missing = []
    for req in recipe.get("ingredients") or []:
        have = data_store.count_bag_item(user, req["item_id"])
        need = int(req["qty"])
        if have < need:
            drop = data_store.get_drop(req["item_id"])
            missing.append({
                "item_id": req["item_id"],
                "name": (drop or {}).get("name", req["item_id"]),
                "have": have,
                "need": need,
            })
    cost = int(recipe.get("gold", 0))
    return {
        "ok": not missing and balance >= cost,
        "missing": missing,
        "cost": cost,
        "can_afford": balance >= cost,
        "recipe": recipe,
    }


def craft(player_id: str, recipe_id: str, balance: int) -> CraftResult:
    """Craft an item. Caller deducts `result.cost` gold when ok."""
    check = can_craft(player_id, recipe_id, balance)
    recipe = check.get("recipe")
    if recipe is None:
        return CraftResult(False, "Không tìm thấy công thức")
    if check.get("missing"):
        names = ", ".join(f"{m['name']} ({m['have']}/{m['need']})" for m in check["missing"])
        return CraftResult(False, f"Thiếu nguyên liệu: {names}", cost=check["cost"], recipe=recipe)
    if not check.get("can_afford"):
        return CraftResult(False, "Không đủ vàng", cost=check["cost"], recipe=recipe)

    result_id = recipe["result_id"]
    result_type = recipe.get("result_type", "equipment")
    if result_type == "equipment":
        item = data_store.get_equipment_by_id(result_id)
    else:
        item = data_store.get_drop(result_id) or data_store.get_consumable(result_id)
    if item is None:
        return CraftResult(False, "Vật phẩm kết quả không tồn tại trong catalog")

    # Don't craft duplicates of unique gear the player already owns
    user = data_store.get_user(player_id)
    if result_type == "equipment" and user is not None:
        from . import equipment as eq
        eq.ensure_loadout(user)
        owned_ids = set()
        if user.get("weapon") and user["weapon"].get("id"):
            owned_ids.add(user["weapon"]["id"])
        for it in user.get("bag") or []:
            if it.get("id"):
                owned_ids.add(it["id"])
        for _, it in eq.iter_equipped(user):
            if it.get("id"):
                owned_ids.add(it["id"])
        if item.get("id") in owned_ids:
            return CraftResult(False, f"Bạn đã có {item['name']}", cost=check["cost"], recipe=recipe)

    def do(user):
        if not data_store.consume_bag_items(user, recipe.get("ingredients") or []):
            return data_store.FORBIDDEN
        crafted = dict(item)
        crafted.setdefault("enhance_level", 0)
        if crafted.get("type") in ("material", "food", "consumable", "upgrade"):
            crafted["qty"] = 1
            data_store._stack_into_bag(user, crafted)
        else:
            user["bag"].append(crafted)
        return {"ok": True, "item": crafted}

    out = data_store._mutate_user(player_id, do)
    if out in (data_store.NOT_FOUND, data_store.FORBIDDEN):
        return CraftResult(False, "Không thể chế tạo", cost=check["cost"], recipe=recipe)
    return CraftResult(True, f"Chế tạo thành công: {out['item']['name']}",
                       cost=check["cost"], item=out["item"], recipe=recipe)
