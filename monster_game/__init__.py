"""
monster_game
============
Pure game-logic port of a "Monster Hunter" style JS Messenger-bot plugin.

This package intentionally contains NO messaging/bot-framework code
(no api.sendMessage, no Users/Currencies plugin, no handleReply queues).
It only implements the game rules: characters, weapons, combat math,
leveling, the shop, and PvP rooms. Wire it up to whatever chat platform
or UI you like.

Layout:
    game.py        high-level API (characters, hunting, PvP rooms)
    combat.py      turn-based battle engine
    shop.py        weapon / food / upgrade catalogs and purchase flow
    data_store.py  JSON persistence (data/users.json, items.json, monsters.json)
    demo.py        `python -m monster_game.demo`
"""
from . import combat, data_store, game, shop

__all__ = ["combat", "data_store", "game", "shop"]
