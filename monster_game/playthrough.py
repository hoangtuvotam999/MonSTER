"""
Full playthrough demo: Level 1 → 10.

Simulates a hunter session with wallet, crafting, gearing, hunting,
adventure events, and sells — then prints a short session report.

Run:  python -m monster_game.playthrough
"""
from __future__ import annotations

import random
from monster_game import craft, data_store, game, render, shop


def _top_up(uid: str) -> None:
    def mut(u):
        u["the_luc"] = max(500, u.get("the_luc", 0))
        w = u.get("weapon")
        if w:
            w["durability"] = 100
            w["HP"] = data_store.weapon_max_hp(w)
        # clear pending so hunts keep flowing
        u["pending_event"] = None
        # keep trophy bag from blocking
        if len(u.get("monster") or []) >= 28:
            u["monster"] = u["monster"][-10:]
        return True
    data_store._mutate_user(uid, mut)


def _sell_all(uid: str, wallet: int, keep_craft_mats: bool = True) -> int:
    sold = shop.sell_monsters(uid, None)
    if isinstance(sold, tuple):
        wallet += int(sold[1] or 0)
    if keep_craft_mats:
        # only sell materials not used by any recipe
        needed = set()
        for r in craft.list_recipes():
            for ing in r.get("ingredients") or []:
                needed.add(ing["item_id"])
        c = game.get_character(uid)
        # sell by absolute bag indices for materials NOT needed (and excess qty>5 of needed)
        to_sell_idx = []  # 1-based among materials only for sell_materials API
        mats = [(i, it) for i, it in enumerate(c["bag"]) if it.get("type") == "material"]
        mat_order = []
        for slot, it in mats:
            mat_order.append(it)
        # sell_materials uses 1-based index among materials
        for n, it in enumerate(mat_order, start=1):
            mid = it.get("id")
            qty = it.get("qty", 1)
            if mid not in needed:
                to_sell_idx.append(n)
            elif qty > 6:
                # trim excess by selling whole stack then... skip complex; keep
                pass
        if to_sell_idx:
            sold = shop.sell_materials(uid, to_sell_idx)
            if isinstance(sold, tuple):
                wallet += int(sold[1] or 0)
    else:
        sold = shop.sell_materials(uid, None)
        if isinstance(sold, tuple):
            wallet += int(sold[1] or 0)
    return wallet


def _try_crafts(uid: str, wallet: int, log: list) -> int:
    for recipe in craft.list_recipes():
        check = craft.can_craft(uid, recipe["id"], wallet)
        if not check.get("ok"):
            continue
        result = game.craft_item(uid, recipe["id"], wallet)
        if result.ok:
            wallet -= result.cost
            log.append(f"🔨 Craft: {result.item['name']} (−{result.cost}g)")
            # auto-equip new gear
            c = game.get_character(uid)
            for i, it in enumerate(c["bag"], start=1):
                if it.get("id") == result.item.get("id") and it.get("type") == "equipment":
                    game.equip_gear(uid, i)
                    log.append(f"   ↳ mặc {it['name']}")
                    break
    return wallet


def _equip_starter(uid: str, log: list) -> None:
    game.equip_or_consume(uid, 1)  # weapon
    c = game.get_character(uid)
    for i, it in enumerate(list(c["bag"]), start=1):
        if it.get("type") == "equipment":
            # re-find index each time
            c = game.get_character(uid)
            for j, it2 in enumerate(c["bag"], start=1):
                if it2.get("id") == it.get("id"):
                    game.equip_gear(uid, j)
                    log.append(f"🛡️ Equip starter: {it2['name']}")
                    break
            break


def _buy_essentials(uid: str, wallet: int, log: list) -> int:
    # potions for belt
    for _ in range(2):
        r = shop.purchase_consumable(uid, 1, wallet)  # potion_s
        if r.ok:
            wallet -= r.cost
    # fill belt empties from bag
    c = game.get_character(uid)
    for slot in range(1, 6):
        if c["consumables"][slot - 1] is not None:
            continue
        c = game.get_character(uid)
        for i, it in enumerate(c["bag"], start=1):
            if it.get("type") in ("consumable", "food") and it.get("id") in (
                "potion_s", "potion_m", "stamina_drink", "dong_quy", "void_slash"
            ):
                game.set_belt(uid, slot, i)
                break
        c = game.get_character(uid)
    # buy cheap chest if affordable and not owned
    r = shop.purchase_equipment(uid, 1, wallet, slot="chest")
    if r.ok:
        wallet -= r.cost
        log.append(f"🛒 Mua {r.item['name']}")
        c = game.get_character(uid)
        for i, it in enumerate(c["bag"], start=1):
            if it.get("id") == r.item.get("id"):
                game.equip_gear(uid, i)
                break
    return wallet


def _manage_power(uid: str, wallet: int, log: list) -> int:
    """Spend points, curb karma, upgrade weapon when possible."""
    c = game.get_character(uid)
    # Dump skill points into ATK/HP
    while c and c.get("points", 0) >= 50:
        game.spend_points(uid, "atk", 25)
        game.spend_points(uid, "hp", 25)
        c = game.get_character(uid)
    # Karma brake
    c = game.get_character(uid)
    if c and c.get("karma", 0) >= 20:
        # buy + use holy water from shop food list index (holy_water is item)
        foods = data_store.get_food_items()
        idx = next((i for i, f in enumerate(foods, 1) if f.get("id") == "holy_water"), None)
        if idx and wallet >= foods[idx - 1]["price"]:
            r = shop.purchase_food(uid, idx, wallet)
            if r.ok:
                wallet -= r.cost
                # consume from bag
                c = game.get_character(uid)
                for i, it in enumerate(c["bag"], start=1):
                    if it.get("id") == "holy_water" or "Nước Thánh" in it.get("name", ""):
                        game.equip_or_consume(uid, i)
                        log.append("🕊️ Uống Nước Thánh (−karma)")
                        break
        # hard reset if still insane (demo mercy)
        c = game.get_character(uid)
        if c and c.get("karma", 0) >= 40:
            def mut(u):
                u["karma"] = max(0, u["karma"] - 30)
                return True
            data_store._mutate_user(uid, mut)
            log.append("🕊️ Karma xả bớt (rest)")
    # Buy better sword tier B if level>=4 and affordable
    c = game.get_character(uid)
    if c and c["level"] >= 4:
        swords = shop.weapons_by_category("Sword")
        # try tier B / index 2 (Pukei Sword II)
        if len(swords) >= 2 and wallet >= swords[1]["price"]:
            owned = {it.get("name") for it in c["bag"] if it.get("type") == "weapon"}
            if c.get("weapon"):
                owned.add(c["weapon"]["name"])
            if swords[1]["name"] not in owned:
                r = shop.purchase_weapon(uid, "Sword", 2, wallet)
                if r.ok:
                    wallet -= r.cost
                    c = game.get_character(uid)
                    for i, it in enumerate(c["bag"], start=1):
                        if it.get("name") == r.item["name"]:
                            game.equip_or_consume(uid, i)
                            log.append(f"🗡️ Đổi vũ khí → {r.item['name']}")
                            break
    return wallet


def main():
    random.seed(20260926)
    data_store.reload_catalogs()
    data_store._save(data_store.USERS_FILE, [])

    uid = "hero"
    log: list[str] = []
    wallet = 2500  # starting pocket gold

    print("=" * 60)
    print("PLAYTHROUGH: Level 1 → 10")
    print("=" * 60)

    game.create_character(uid, "Kael")
    _equip_starter(uid, log)
    wallet = _buy_essentials(uid, wallet, log)
    wallet = _manage_power(uid, wallet, log)

    print("\n--- Trạng thái ban đầu ---")
    print(render.render_character(game.character_summary(uid)))
    print()
    print(render.render_equipment(game.get_character(uid)))
    print()
    print(render.render_belt(game.get_character(uid)))
    print()
    print(render.render_craft_list(uid, wallet))

    hunts = wins = losses = draws = events = 0
    map_index = 1  # Ancient Forest
    printed_levels = set()

    print("\n--- Bắt đầu hành trình ---\n")
    safety = 0
    while game.get_character(uid)["level"] < 10 and safety < 600:
        safety += 1
        c = game.get_character(uid)
        # Wildspire only when strong enough & karma under control
        if c["level"] >= 6 and c.get("karma", 0) < 15 and map_index == 1:
            map_index = 2
            loc = game.set_location(uid, map_index)
            log.append(f"🗺️ Đến {loc['name']} (Lv.{c['level']})")
            print(f"\n🗺️ Đến {loc['name']}!\n")
        elif c["level"] < 6 or c.get("karma", 0) >= 25:
            if map_index != 1:
                map_index = 1
                game.set_location(uid, 1)
                log.append("🗺️ Quay lại Ancient Forest (farm / xả karma)")
            elif c["locationID"] is None:
                game.set_location(uid, 1)
        elif c["locationID"] is None:
            game.set_location(uid, map_index)

        _top_up(uid)
        if safety % 4 == 0:
            wallet = _sell_all(uid, wallet)
            wallet = _try_crafts(uid, wallet, log)
            wallet = _manage_power(uid, wallet, log)

        outcome = game.encounter_and_fight(uid)
        if not outcome.get("ok"):
            reason = outcome.get("reason")
            if reason == "bag_full":
                wallet = _sell_all(uid, wallet)
            elif reason == "weapon_broken":
                rep = game.repair_weapon(uid, wallet)
                if rep.get("ok"):
                    wallet -= rep["cost"]
            elif reason == "level_too_low":
                map_index = 1
                game.set_location(uid, 1)
            continue

        hunts += 1
        if outcome.get("draw"):
            draws += 1
        elif outcome.get("won"):
            wins += 1
        else:
            losses += 1

        c = game.get_character(uid)
        show = hunts <= 2 or outcome.get("draw") or (
            outcome.get("won") and c["level"] in (2, 3, 5, 7, 9, 10)
            and c["level"] not in printed_levels
        )
        if show and outcome.get("won"):
            printed_levels.add(c["level"])
        if show:
            print(render.render_hunt(outcome))
            print("-" * 40)

        if outcome.get("adventure"):
            events += 1
            ids = [a["id"] for a in outcome["adventure"]["actions"]]
            act = ids[0]
            for pref in ("inspect", "search", "help", "fill", "open"):
                if pref in ids:
                    act = pref
                    break
            res = game.resolve_adventure(uid, act)
            wallet += int(res.get("gold_delta") or 0)
            if events <= 3:
                print(render.render_adventure_result(res))
                print("-" * 40)

        for kind, val in outcome.get("events") or []:
            if kind == "level_up":
                print(f"\n⭐ LEVEL UP → {val} | ví {wallet}g | W/L {wins}/{losses} | hunts {hunts}\n")
                log.append(f"⭐ Level {val}")
                wallet = _sell_all(uid, wallet)
                wallet = _try_crafts(uid, wallet, log)
                wallet = _manage_power(uid, wallet, log)

    wallet = _sell_all(uid, wallet)
    wallet = _try_crafts(uid, wallet, log)
    wallet = _manage_power(uid, wallet, log)

    c = game.get_character(uid)
    summary = game.character_summary(uid)

    print("\n" + "=" * 60)
    print("KẾT THÚC PLAYTHROUGH")
    print("=" * 60)
    print(render.render_character(summary))
    print()
    print(render.render_equipment(c))
    print()
    print(render.render_belt(c))
    print()
    print(render.render_bag(c))
    print()
    print(render.render_journey(game.journey_log(uid, 12)))
    print()
    print("--- Session stats ---")
    print(f"Level: {c['level']} | EXP: {round(c['exp'])}/{data_store.exp_needed_for(c['level'])}")
    print(f"Hunts: {hunts} | W/L/D: {wins}/{losses}/{draws} | Events: {events}")
    print(f"Wallet: {wallet}g | Power: {round(summary['power_total'])} | Karma: {c['karma']}")
    print(f"Bag items: {len(c['bag'])} | Trophies: {len(c['monster'])}")
    print(f"Location: {summary.get('location_name')}")
    print("\nKey log:")
    for line in log[-25:]:
        print(" ", line)

    import json
    from pathlib import Path
    report = {
        "level": c["level"],
        "hunts": hunts,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "events": events,
        "wallet": wallet,
        "power": summary["power_total"],
        "karma": c["karma"],
        "bag": len(c["bag"]),
        "gear_bonus": summary.get("gear_bonus"),
        "weapon": summary.get("weapon_name"),
        "log": log,
        "reached_10": c["level"] >= 10,
    }
    Path("/tmp/playthrough_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n(report → /tmp/playthrough_report.json)")
    if c["level"] < 10:
        raise SystemExit(f"FAIL: only reached level {c['level']}")
    return report


if __name__ == "__main__":
    main()
