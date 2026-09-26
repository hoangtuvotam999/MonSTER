"""
Runnable demo showing the whole flow end-to-end:
create two characters, equip weapons, roam a location, fight a monster,
then run a PvP match between the two characters.

Run with:  python -m monster_game.demo   (from the repository root)
"""
from monster_game import data_store, game, render, shop


def main():
    # --- Reset the sample save file for a clean demo run ---
    data_store._save(data_store.USERS_FILE, [])

    print("== Creating characters ==")
    alice = game.create_character("alice", "Alice")
    bob = game.create_character("bob", "Bob")
    print(f"{alice['name']} and {bob['name']} created.\n")

    print("== Equipping starting weapons (bag slot #1) ==")
    game.equip_or_consume("alice", 1)
    game.equip_or_consume("bob", 1)
    print("Both equipped their Iron Sword I.\n")

    print("== Shop ==")
    print(render.render_shop_menu())
    print()
    print(render.render_weapon_list("Great Sword", game.get_character("alice"), balance=999999))
    print()

    print("== Alice buys a Great Sword and equips it ==")
    result = shop.purchase_weapon("alice", "Great Sword", 1, balance=999999)
    print(render.render_purchase(result))
    if result.ok:
        c = game.get_character("alice")
        idx = next(i for i, it in enumerate(c["bag"]) if it["name"] == result.item["name"]) + 1
        game.equip_or_consume("alice", idx)
    print()
    print(render.render_bag(game.get_character("alice")))
    print()

    print("== Locations ==")
    print(render.render_locations(game.list_locations(), game.get_character("alice")))
    print()

    print("== Alice travels to Ancient Forest and hunts ==")
    game.set_location("alice", 1)
    for _ in range(3):
        outcome = game.encounter_and_fight("alice")
        print(render.render_hunt(outcome))
        print("-" * 50)
    print()

    print("== Alice repairs her weapon ==")
    print(render.render_repair(game.repair_weapon("alice", balance=999999)))
    print()

    print("== Alice's trophies ==")
    print(render.render_trophies(game.get_character("alice")))
    print()

    print("== Alice and Bob's stats ==")
    print(render.render_character(game.character_summary("alice")))
    print()
    print(render.render_character(game.character_summary("bob")))
    print()

    print("== PvP: Alice creates a room, Bob joins, they fight ==")
    game.create_room("thread1", "alice", "Alice vs Bob")
    game.join_room("thread1", "bob", 1)
    game.set_ready("thread1", "bob")
    names = {"alice": "Alice", "bob": "Bob"}
    print(render.render_rooms(game.list_rooms("thread1"), names.get))
    print()
    match_result = game.start_match("thread1", "alice")
    print(render.render_pvp(match_result) if match_result else "Không thể bắt đầu trận PvP.")


if __name__ == "__main__":
    main()
