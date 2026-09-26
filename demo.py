"""
Runnable demo showing the whole flow end-to-end:
create two characters, equip weapons, roam a location, fight a monster,
then run a PvP match between the two characters.

Run with:  python -m monster_game.demo   (from the parent directory)
"""
from monster_game import game, shop


def main():
    # --- Reset the sample save file for a clean demo run ---
    from monster_game import data_store
    data_store._save(data_store.USERS_FILE, [])

    print("== Creating characters ==")
    alice = game.create_character("alice", "Alice")
    bob = game.create_character("bob", "Bob")
    print(f"{alice['name']} and {bob['name']} created.\n")

    print("== Equipping starting weapons (bag slot #1) ==")
    game.equip_or_consume("alice", 1)
    game.equip_or_consume("bob", 1)
    print("Both equipped their Iron Sword I.\n")

    print("== Alice buys a Great Sword and equips it ==")
    result = shop.purchase_weapon("alice", "Great Sword", 1, balance=999999)
    print(result)
    if result.ok:
        # bag now has [old iron sword removed on prior equip is fine; new weapon appended]
        c = game.get_character("alice")
        idx = next(i for i, it in enumerate(c["bag"]) if it["name"] == result.item["name"]) + 1
        game.equip_or_consume("alice", idx)
    print()

    print("== Alice travels to Ancient Forest and hunts ==")
    game.set_location("alice", 1)
    outcome = game.encounter_and_fight("alice")
    print(outcome)
    print()

    print("== Alice and Bob's stats ==")
    print(game.character_summary("alice"))
    print(game.character_summary("bob"))
    print()

    print("== PvP: Alice creates a room, Bob joins, they fight ==")
    game.create_room("thread1", "alice", "Alice vs Bob")
    game.join_room("thread1", "bob", 1)
    game.set_ready("thread1", "bob")
    match_result = game.start_match("thread1", "alice")
    print(match_result)


if __name__ == "__main__":
    main()
