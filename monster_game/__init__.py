"""
monster_game
============
Pure game-logic port of a "Monster Hunter" style chat-bot plugin.

This package intentionally contains NO messaging/bot-framework code.
It only implements the game rules: characters, weapons, combat math,
leveling, the shop, drops, map adventure events, blacksmith enhance,
dungeon rooms, party, and PvP rooms.

Chat commands live in the separate `monster_commands` library.
The Discord process lives in `discord_bot` and only calls that library.

Layout:
    game.py        high-level API (characters, hunting, PvP, adventure)
    combat.py      turn-based battle engine
    adventure.py   post-hunt text events + drop grants
    blacksmith.py  enhance +N with stones / protect scrolls
    dungeon.py     multi-room expeditions
    shop.py        weapon / food / upgrade purchase flow
    craft.py       crafting recipes
    equipment.py   gear slots + set bonuses
    data_store.py  JSON persistence + modular catalog loader
    render.py      chat-ready text (hunt / adventure / journey log)
    demo.py        `python -m monster_game.demo`

Data (author new content here):
    data/map/mapN_*.json
    data/dungeon/*.json
    data/item/weapon/tier_{A,B,C,D}.json
    data/item/drop/tier_{A,B,C,D}.json
    data/item/food.json
    data/item/upgrade.json
    data/item/blacksmith.json
    data/item/consumable/*.json
"""
from . import (
    adventure, blacksmith, combat, craft, data_store, dungeon,
    equipment, game, party, render, shop,
)

__all__ = [
    "adventure", "blacksmith", "combat", "craft", "data_store", "dungeon",
    "equipment", "game", "party", "render", "shop",
]
