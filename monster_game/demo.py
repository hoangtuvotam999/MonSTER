"""
Demo: equipment, belt, blacksmith enhance, dungeon rooms, hunt.

Run:  python -m monster_game.demo
"""
import random

from monster_game import adventure, data_store, game, render, shop


def _top_up(player_id: str) -> None:
    def mut(u):
        u["the_luc"] = max(u.get("the_luc", 0), 500)
        if u.get("weapon"):
            u["weapon"]["durability"] = 100
            u["weapon"]["HP"] = data_store.weapon_max_hp(u["weapon"])
        return True
    data_store._mutate_user(player_id, mut)


def _grant(player_id: str, item_id: str, qty: int = 1) -> None:
    item = data_store.instantiate_drop(item_id, qty) or (
        dict(data_store.get_consumable(item_id) or {}) | {"qty": qty}
        if data_store.get_consumable(item_id) else None
    )
    if not item:
        return

    def mut(u):
        data_store._stack_into_bag(u, dict(item))
        return True
    data_store._mutate_user(player_id, mut)


def main():
    data_store.reload_catalogs()
    data_store._save(data_store.USERS_FILE, [])

    print("== Create ==")
    game.create_character("alice", "Alice")
    game.create_character("bob", "Bob")
    game.equip_or_consume("alice", 1)  # weapon
    game.equip_or_consume("bob", 1)

    c = game.get_character("alice")
    for i, it in enumerate(c["bag"], start=1):
        if it.get("type") == "equipment":
            print("Equip", it["name"], "->", game.equip_gear("alice", i))
            break

    print("\n== Buy gear + special consumables ==")
    shop.purchase_equipment("alice", 1, 999999, slot="chest")
    c = game.get_character("alice")
    for i, it in enumerate(c["bag"], start=1):
        if it.get("slot") == "chest":
            game.equip_gear("alice", i)
            break
    shop.purchase_consumable("alice", 7, 999999)  # dong_quy
    shop.purchase_consumable("alice", 8, 999999)  # void_slash
    c = game.get_character("alice")
    for i, it in enumerate(c["bag"], start=1):
        if it.get("id") == "dong_quy":
            game.set_belt("alice", 2, i)
            break
    c = game.get_character("alice")
    for i, it in enumerate(c["bag"], start=1):
        if it.get("id") == "void_slash":
            game.set_belt("alice", 3, i)
            break

    print(render.render_equipment(game.get_character("alice")))
    print()
    print(render.render_belt(game.get_character("alice")))
    print()

    print("== Blacksmith ==")
    _grant("alice", "enhance_stone_a", 5)
    _grant("alice", "monster_bone_s", 5)
    _grant("alice", "scroll_soft", 1)
    print(render.render_enhance_quote(game.enhance_quote("alice", "weapon")))
    # Forced success then failure with protect
    r1 = game.enhance_item("alice", "weapon", balance=999999, rng=random.Random(0))
    print(render.render_enhance_result(r1))
    # Find soft scroll index
    c = game.get_character("alice")
    prot_idx = next((i for i, it in enumerate(c["bag"], 1)
                     if it.get("subtype") == "enhance_protect"), None)
    r2 = game.enhance_item(
        "alice", "weapon", balance=999999,
        protect_bag_index_1based=prot_idx,
        rng=random.Random(99),  # likely fail at higher rates later; force with seeded
    )
    print(render.render_enhance_result(r2))
    print(render.render_character(game.character_summary("alice")))
    print()

    print("== Dungeons ==")
    print(render.render_dungeon_list())
    _top_up("alice")
    start = game.start_dungeon("alice", "forest_ruin")
    print(start)
    # resolve rooms until complete / fail / abort (cap steps)
    for step in range(12):
        c = game.get_character("alice")
        if not c.get("dungeon_run"):
            break
        run = c["dungeon_run"]
        action = None
        if run.get("pending_event"):
            acts = [a["id"] for a in run["pending_event"].get("actions") or []]
            action = "enter" if "enter" in acts else (acts[0] if acts else None)
        result = game.advance_dungeon("alice", action_id=action, rng=random.Random(step + 1))
        print(render.render_dungeon_result(result))
        print("-" * 40)
        if result.get("dungeon_complete") or result.get("dungeon_failed") or result.get("kind") == "abort":
            break

    print("== Hunt ==")
    game.set_location("alice", 1)
    for _ in range(4):
        _top_up("alice")
        data_store.set_pending_event("alice", None)
        outcome = game.encounter_and_fight("alice")
        if not outcome.get("ok"):
            print(render.render_hunt(outcome))
            continue
        print(render.render_hunt(outcome))
        print("-" * 50)
        if outcome.get("adventure"):
            choice = outcome["adventure"]["actions"][0]["id"]
            print(render.render_adventure_result(game.resolve_adventure("alice", choice)))
            break

    print("\n== Journey ==")
    print(render.render_journey(game.journey_log("alice", 12)))
    print()
    print("== Belt after fights ==")
    print(render.render_belt(game.get_character("alice")))


if __name__ == "__main__":
    main()
