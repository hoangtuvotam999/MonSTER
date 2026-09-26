"""
Shop — port of the hard-coded catalogs and buy-flow in index.js
(cases "1"-"9" of getItems()/buyItem()).

Weapon catalogs (Great Sword, Lance, Sword'n Shield, Dual Blades, HBG, LBG)
come from the item data file data/items.json (three tiers per category;
extend or replace it freely — every entry must carry `"category"` matching
one of WEAPON_CATEGORIES' values).

Food and upgrade-material catalogs were hard-coded directly in index.js,
so they're reproduced verbatim below.

Currency/economy (the original `Currencies` plugin) is intentionally NOT
included — these functions take/return a plain `balance` int so you can
wire them into whatever wallet system you have.

IMPORTANT: every entry in data/items.json (weapons) MUST include
`"type": "weapon"` — data_store.set_item() dispatches on that field to
know whether to equip, consume, or apply an item, exactly like the
original setData.js's `switch(data.type)`.
"""
from __future__ import annotations

from typing import Optional

from . import data_store

WEAPON_CATEGORIES = {
    "1": "Great Sword",
    "2": "Lance",
    "3": "Sword",
    "4": "Dual Blades",
    "5": "Heavy Bowgun",
    "6": "Light Bowgun",
}

# Verbatim port of the `foods` array in index.js (case "7")
FOOD_ITEMS = [
    {"type": "food", "name": "A Platter Mini (+5 mọi chỉ số)", "price": 5000, "heal": 100,
     "boostHP": 5, "boostATK": 5, "boostDEF": 5, "boostSPD": 5, "boostEXP": 0,
     "boostKarma": 0, "boostPoints": 0, "image": "https://i.imgur.com/a4sWP0L.png"},
    {"type": "food", "name": "B Platter Medium (+10 mọi chỉ số)", "price": 12500, "heal": 250,
     "boostHP": 10, "boostATK": 10, "boostDEF": 10, "boostSPD": 10, "boostEXP": 0,
     "boostKarma": 0, "boostPoints": 0, "image": "https://i.imgur.com/Zzjdj65.png"},
    {"type": "food", "name": "C Platter XL (+15 mọi chỉ số)", "price": 25000, "heal": 500,
     "boostHP": 15, "boostATK": 15, "boostDEF": 15, "boostSPD": 15, "boostEXP": 0,
     "boostKarma": 0, "boostPoints": 0, "image": "https://i.imgur.com/6LTkApY.png"},
    {"type": "food", "name": "Trà Sữa TocoToco Full Topping (+20 mọi chỉ số)", "price": 50000,
     "heal": 1000, "boostHP": 20, "boostATK": 20, "boostDEF": 20, "boostSPD": 20,
     "boostEXP": 0, "boostKarma": 0, "boostPoints": 0, "image": "https://i.imgur.com/JoyQr1y.png"},
    {"type": "food", "name": "Upgrade Pill+ (đột phá mọi chỉ số)", "price": 2000000, "heal": 0,
     "boostHP": 2000, "boostATK": 1000, "boostDEF": 1000, "boostSPD": 100,
     "boostEXP": 0, "boostKarma": 0, "boostPoints": 0, "image": "https://i.imgur.com/C8cunxL.png"},
    {"type": "food", "name": "10x Upgrade Pill+ (đột phá mọi chỉ số)", "price": 20000000, "heal": 0,
     "boostHP": 20000, "boostATK": 10000, "boostDEF": 10000, "boostSPD": 1000,
     "boostEXP": 0, "boostKarma": 0, "boostPoints": 0, "image": "https://i.imgur.com/Lbe9fdO.png"},
    {"type": "food", "name": "Nước Thánh (-10 Karma)", "price": 5000, "heal": 0,
     "boostHP": 0, "boostATK": 0, "boostDEF": 0, "boostSPD": 0, "boostEXP": 0,
     "boostKarma": -10, "boostPoints": 0, "image": "https://i.imgur.com/xhLi9dU.png"},
    {"type": "food", "name": "Nước Thánh Tối Thượng (-100 Karma)", "price": 500000, "heal": 0,
     "boostHP": 0, "boostATK": 0, "boostDEF": 0, "boostSPD": 0, "boostEXP": 0,
     "boostKarma": -100, "boostPoints": 0, "image": "https://i.imgur.com/eTSNtJF.png"},
    {"type": "food", "name": "Cách để tăng độ khó cho game", "price": 100000, "heal": 0,
     "boostHP": 0, "boostATK": 0, "boostDEF": 0, "boostSPD": 0, "boostEXP": 0,
     "boostKarma": 100, "boostPoints": 0, "image": "https://i.imgur.com/jws0SLF.png"},
]

# Verbatim port of the `upgrades` array in index.js (case "9")
UPGRADE_MATERIALS = [
    {"type": "upgrade", "name": "Mithril", "usage": 0, "price": 20000,
     "boostHPweapon": 2000, "boostATKweapon": 200, "boostDEFweapon": 200, "boostSPDweapon": 10,
     "image": "https://i.imgur.com/Cvg8eHC.png"},
    {"type": "upgrade", "name": "Orichalcum", "usage": 0, "price": 50000,
     "boostHPweapon": 4000, "boostATKweapon": 400, "boostDEFweapon": 400, "boostSPDweapon": 20,
     "image": "https://i.imgur.com/Sz0A2hp.png"},
    {"type": "upgrade", "name": "Adamantium", "usage": 0, "price": 120000,
     "boostHPweapon": 8000, "boostATKweapon": 800, "boostDEFweapon": 800, "boostSPDweapon": 40,
     "image": "https://i.imgur.com/SnObhnz.png"},
    {"type": "upgrade", "name": "Scarite", "usage": 0, "price": 260000,
     "boostHPweapon": 16000, "boostATKweapon": 1600, "boostDEFweapon": 1600, "boostSPDweapon": 80,
     "image": "https://i.imgur.com/iIMwZEy.jpg"},
    {"type": "upgrade", "name": "Dragonite", "usage": 0, "price": 420000,
     "boostHPweapon": 32000, "boostATKweapon": 3200, "boostDEFweapon": 3200, "boostSPDweapon": 160,
     "image": "https://i.imgur.com/mKzBHAK.jpg"},
    {"type": "upgrade", "name": "Lunarite", "usage": 0, "price": 840000,
     "boostHPweapon": 64000, "boostATKweapon": 6400, "boostDEFweapon": 6400, "boostSPDweapon": 320,
     "image": "https://i.imgur.com/40qcjeG.jpg"},
    {"type": "upgrade", "name": "Kriztonite", "usage": 0, "price": 1580000,
     "boostHPweapon": 128000, "boostATKweapon": 12800, "boostDEFweapon": 12800, "boostSPDweapon": 640,
     "image": "https://i.imgur.com/awGbMAP.jpg"},
    {"type": "upgrade", "name": "Damascusium Crytalite", "usage": 0, "price": 4560000,
     "boostHPweapon": 256000, "boostATKweapon": 25600, "boostDEFweapon": 25600, "boostSPDweapon": 1280,
     "image": "https://i.imgur.com/a0T8AZf.jpg"},
]

MAX_WEAPON_LEVEL = 256  # port of `if (dataUser.weapon.usage >= 256)` guard


def weapons_by_category(category: str) -> list[dict]:
    """`category` may be a display name ("Great Sword") or its shop key ("1")."""
    category = WEAPON_CATEGORIES.get(str(category), category)
    items = data_store.get_items() or []
    return [i for i in items if i.get("category") == category]


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
    return _purchase(player_id, FOOD_ITEMS, index_1based, balance)


def purchase_upgrade_material(player_id: str, index_1based: int, balance: int) -> PurchaseResult:
    user = data_store.get_user(player_id)
    if user is None:
        return PurchaseResult(False, "Bạn chưa có nhân vật")
    if user.get("weapon") and user["weapon"].get("usage", 0) >= MAX_WEAPON_LEVEL:
        return PurchaseResult(False, "Vũ khí đã đạt cấp tối đa")
    return _purchase(player_id, UPGRADE_MATERIALS, index_1based, balance)


def sell_monsters(player_id: str, indices_1based: Optional[list[int]] = None):
    """Returns (count_sold, total_money). Pass indices_1based=None to sell all."""
    return data_store.sell_monsters(player_id, indices_1based)
