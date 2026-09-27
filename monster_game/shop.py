"""
Shop — weapon / food / upgrade catalogs and purchase flow.

Weapon catalogs live in data/item/weapon/tier_*.json.
Food and upgrade materials live in data/item/food.json and upgrade.json.
Drop materials (loot) live in data/item/drop/tier_*.json and are not sold
here — they enter the bag via hunts and adventure events.
"""
from __future__ import annotations

from typing import Optional

from . import data_store, tiers

WEAPON_CATEGORIES = {
    "1": "Great Sword",
    "2": "Lance",
    "3": "Sword",
    "4": "Dual Blades",
    "5": "Heavy Bowgun",
    "6": "Light Bowgun",
}

def weapon_tier_labels() -> dict:
    """Roman label for each tier id and its aliases (A is I)."""
    labels = {}
    for row in tiers.all_tiers():
        labels[str(row["id"])] = row["label"]
        for alias in row.get("aliases") or []:
            labels[str(alias)] = row["label"]
    return labels


WEAPON_TIER_LABELS = weapon_tier_labels()

MAX_WEAPON_LEVEL = 256


def __getattr__(name: str):
    """Lazy access so `shop.FOOD_ITEMS` still looks like a list."""
    if name == "FOOD_ITEMS":
        return data_store.get_food_items()
    if name == "UPGRADE_MATERIALS":
        return data_store.get_upgrade_materials()
    raise AttributeError(name)


def for_sale(items: list[dict]) -> list[dict]:
    """Shop counters only list tiers marked shop in tiers.json (ranks 1–7)."""
    return [item for item in items if tiers.is_shop(item)]


def weapons_by_category(category: str) -> list[dict]:
    """`category` may be a display name ("Great Sword") or its shop key ("1")."""
    category = WEAPON_CATEGORIES.get(str(category), category)
    found = [i for i in data_store.get_weapons() if i.get("category") == category]
    return for_sale(found)


def weapons_by_tier(tier: str) -> list[dict]:
    """tier is A/B/C/D (or tier_A filename suffix)."""
    tier = str(tier).upper().removeprefix("TIER_")
    return [i for i in data_store.get_weapons() if i.get("tier") == tier]


class PurchaseResult:
    def __init__(self, ok: bool, message: str, cost: int = 0, item: Optional[dict] = None):
        self.ok = ok
        self.message = message
        self.cost = cost
        self.item = item

    def __repr__(self):
        return f"PurchaseResult(ok={self.ok}, message={self.message!r}, cost={self.cost})"


def _purchase(player_id: str, catalog: list[dict], index_1based: int, balance: int) -> PurchaseResult:
    if not (1 <= index_1based <= len(catalog)):
        return PurchaseResult(False, "Không tìm thấy vật phẩm")
    item = catalog[index_1based - 1]
    if balance < item["price"]:
        return PurchaseResult(False, "Không đủ tiền")
    result = data_store.buy_item(player_id, item)
    if result == data_store.NOT_FOUND:
        return PurchaseResult(False, "Bạn chưa có nhân vật")
    if result == data_store.FORBIDDEN:
        return PurchaseResult(False, "Bạn đã sở hữu vật phẩm này từ trước")
    return PurchaseResult(True, f"Đã mua {item['name']}", item["price"], item)


def purchase_weapon(player_id: str, category: str, index_1based: int, balance: int) -> PurchaseResult:
    return _purchase(player_id, weapons_by_category(category), index_1based, balance)


def purchase_food(player_id: str, index_1based: int, balance: int) -> PurchaseResult:
    return _purchase(player_id, data_store.get_food_items(), index_1based, balance)


def purchase_upgrade_material(player_id: str, index_1based: int, balance: int) -> PurchaseResult:
    user = data_store.get_user(player_id)
    if user is None:
        return PurchaseResult(False, "Bạn chưa có nhân vật")
    if user.get("weapon") and user["weapon"].get("usage", 0) >= MAX_WEAPON_LEVEL:
        return PurchaseResult(False, "Vũ khí đã đạt cấp tối đa")
    return _purchase(player_id, stone_catalog(), index_1based, balance)


def purchase_equipment(player_id: str, index_1based: int, balance: int,
                       slot: Optional[str] = None) -> PurchaseResult:
    catalog = for_sale(data_store.get_equipment(slot))
    return _purchase(player_id, catalog, index_1based, balance)


def stone_catalog() -> list[dict]:
    """Upgrade materials, plus enhance stones of shop ranks 5–7."""
    items = list(data_store.get_upgrade_materials())
    for drop in data_store.get_drops():
        if "enhance_stone" not in (drop.get("tags") or []):
            continue
        row = tiers.resolve(drop.get("tier"))
        if not row or not row.get("shop") or int(row["rank"]) < 5:
            continue
        if int(drop.get("price") or 0) <= 0:
            continue
        items.append(drop)
    return items


def purchase_consumable(player_id: str, index_1based: int, balance: int) -> PurchaseResult:
    return _purchase(player_id, data_store.get_consumables(), index_1based, balance)


def sell_monsters(player_id: str, indices_1based: Optional[list[int]] = None):
    """Returns (count_sold, total_money). Pass indices_1based=None to sell all."""
    return data_store.sell_monsters(player_id, indices_1based)


def sell_materials(player_id: str, indices_1based: Optional[list[int]] = None):
    """Sell material drops from the bag. Returns (count, gold)."""
    return data_store.sell_materials(player_id, indices_1based)
