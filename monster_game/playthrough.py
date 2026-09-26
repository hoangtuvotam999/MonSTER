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


def _grant(uid: str, item_id: str, qty: int = 1) -> None:
    item = data_store.instantiate_drop(item_id, qty)
    if not item:
        return

    def mut(u):
        data_store._stack_into_bag(u, dict(item))
        return True

    data_store._mutate_user(uid, mut)


def _try_enhance(uid: str, wallet: int, log: list, rng: random.Random) -> int:
    """Attempt weapon enhance using stacked luck charms (cap +36%)."""
    from monster_game import blacksmith as bs

    c = game.get_character(uid)
    if not c or not c.get("weapon"):
        return wallet
    quote = bs.cost_for(c["weapon"])
    if wallet < quote["gold"]:
        return wallet
    for req in quote["stones"] + quote["materials"]:
        if data_store.count_bag_item(c, req["item_id"]) < int(req["qty"]):
            return wallet

    # Stack luck charms toward +36% when base rate is rough
    luck_idx: list[int] = []
    need = bs.MAX_LUCK_BONUS if quote["rate"] < 0.7 else (0.18 if quote["rate"] < 0.9 else 0.0)
    got = 0.0
    for i, it in enumerate(c["bag"], 1):
        if got >= need - 1e-9:
            break
        if it.get("subtype") != "enhance_luck":
            continue
        luck_idx.append(i)
        # account for stack qty in planning
        qty = int(it.get("qty", 1))
        bonus = float(it.get("luck_bonus") or 0)
        for _ in range(qty):
            if got >= need:
                break
            got = min(bs.MAX_LUCK_BONUS, got + bonus)

    # Protect: 50% if +5+, else 25% if +3+
    cur = bs.enhance_level(c["weapon"])
    want = "scroll_keep_50" if cur >= 5 else ("scroll_keep_25" if cur >= 3 else None)
    prot = None
    if want:
        prot = next((i for i, it in enumerate(c["bag"], 1) if it.get("id") == want), None)

    r = game.enhance_item(
        uid, "weapon", balance=wallet,
        protect_bag_index_1based=prot,
        luck_bag_indices_1based=luck_idx or None,
        rng=rng,
    )
    if not r.get("ok"):
        return wallet
    wallet -= r["gold_cost"]
    luck = r.get("luck_bonus") or 0
    icon = "✅" if r["success"] else "💥"
    line = (f"{icon} Đập +{r['level_before']}→+{r['level_after']} "
            f"(base {r.get('rate_base',0)*100:.0f}% +luck {luck*100:.0f}%/{bs.MAX_LUCK_BONUS*100:.0f}% "
            f"= {r['rate']*100:.0f}%, −{r['gold_cost']}g)")
    if r.get("protect_used"):
        line += f" · {r['protect_used']}"
    log.append(line)
    print(line)
    return wallet


def _stock_smith(uid: str, wallet: int, log: list) -> int:
    """Buy luck/protect from shop when affordable; grant a few stones early."""
    c = game.get_character(uid)
    cons = data_store.get_consumables()
    # buy small luck if we have few
    luck_have = sum(data_store.count_bag_item(c, x["id"]) for x in cons if x.get("subtype") == "enhance_luck")
    if luck_have < 4:
        for want_id in ("charm_luck_s", "charm_luck_m", "charm_luck_l"):
            idx = next((i for i, it in enumerate(cons, 1) if it.get("id") == want_id), None)
            if not idx:
                continue
            price = cons[idx - 1]["price"]
            if wallet < price:
                continue
            r = shop.purchase_consumable(uid, idx, wallet)
            if r.ok:
                wallet -= r.cost
                log.append(f"🛒 Mua {r.item['name']} (ép may)")
    # protect scrolls
    for want_id in ("scroll_keep_25", "scroll_keep_50"):
        if data_store.count_bag_item(game.get_character(uid), want_id) > 0:
            continue
        idx = next((i for i, it in enumerate(cons, 1) if it.get("id") == want_id), None)
        if idx and wallet >= cons[idx - 1]["price"]:
            r = shop.purchase_consumable(uid, idx, wallet)
            if r.ok:
                wallet -= r.cost
                log.append(f"🛒 Mua {r.item['name']}")
    # seed stones/mats matching equipped weapon tier
    c = game.get_character(uid)
    tier = str((c.get("weapon") or {}).get("tier") or "A").lower()
    stone = f"enhance_stone_{tier}"
    bone = {"a": "monster_bone_s", "b": "monster_bone_m", "c": "monster_bone_l", "d": "elder_dragon_bone"}.get(tier, "monster_bone_s")
    if data_store.count_bag_item(c, stone) < 4:
        _grant(uid, stone, 4)
        _grant(uid, bone, 4)
        if tier == "b":
            _grant(uid, "iron_ore", 4)
    return wallet


def _try_dungeon(uid: str, wallet: int, log: list, rng: random.Random) -> int:
    c = game.get_character(uid)
    if not c or c.get("dungeon_run"):
        return wallet
    dungeon_id = "forest_ruin" if c["level"] < 5 else "waste_tomb"
    if c["level"] < 5 and dungeon_id == "waste_tomb":
        dungeon_id = "forest_ruin"
    if c["level"] < 5:
        dungeon_id = "forest_ruin"
    elif c["level"] >= 5:
        dungeon_id = "waste_tomb"
    start = game.start_dungeon(uid, dungeon_id)
    if not start.get("ok"):
        if c["level"] >= 5:
            start = game.start_dungeon(uid, "forest_ruin")
        if not start.get("ok"):
            return wallet
        dungeon_id = "forest_ruin"
    log.append(f"🏰 Vào {start.get('dungeon')}")
    print(f"\n🏰 Dungeon: {start.get('dungeon')}")
    for step in range(16):
        c = game.get_character(uid)
        if not c.get("dungeon_run"):
            break
        action = None
        if c["dungeon_run"].get("pending_event"):
            acts = [a["id"] for a in c["dungeon_run"]["pending_event"].get("actions") or []]
            action = "enter" if "enter" in acts else (acts[0] if acts else None)
        result = game.advance_dungeon(uid, action_id=action, rng=random.Random(rng.randint(1, 10_000)))
        wallet += int(result.get("gold_delta") or 0)
        if result.get("kind") == "combat" and (result.get("won") or result.get("draw")):
            print(f"   ⚔️ {result.get('monster_name')} — thắng · EXP+{result.get('exp_gained', 0)}")
        if result.get("dungeon_complete"):
            log.append(f"🏰 Clear {dungeon_id}")
            print("   🏰 Clear!")
            break
        if result.get("dungeon_failed") or result.get("kind") == "abort":
            log.append(f"🏰 Fail/abort {dungeon_id}")
            print("   💀 Fail/abort")
            break
    return wallet


def main():
    rng = random.Random(20260926)
    random.seed(20260926)
    data_store.reload_catalogs()
    data_store._save(data_store.USERS_FILE, [])

    uid = "hero"
    log: list[str] = []
    wallet = 8000  # pocket gold for smith + gear

    print("=" * 60)
    print("PLAYTHROUGH: Level 1 → 10 (ép may tối đa +36%)")
    print("=" * 60)
    print(f"Quy tắc: charm may cộng dồn, trần cứng +{int(0.36*100)}% tỉ lệ đập.\n")

    game.create_character(uid, "Kael")
    _equip_starter(uid, log)
    wallet = _buy_essentials(uid, wallet, log)
    wallet = _stock_smith(uid, wallet, log)
    wallet = _manage_power(uid, wallet, log)

    print("\n--- Trạng thái ban đầu ---")
    print(render.render_character(game.character_summary(uid)))
    print()
    print(render.render_equipment(game.get_character(uid)))
    print()
    print(render.render_belt(game.get_character(uid)))

    hunts = wins = losses = draws = events = 0
    enhances = 0
    map_index = 1
    printed_levels = set()

    print("\n--- Bắt đầu hành trình ---\n")
    safety = 0
    while game.get_character(uid)["level"] < 10 and safety < 600:
        safety += 1
        c = game.get_character(uid)
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
            wallet = _stock_smith(uid, wallet, log)

        # dungeon every ~8 hunts
        if safety % 8 == 1 and c["level"] >= 1:
            wallet = _try_dungeon(uid, wallet, log, rng)
            _top_up(uid)

        # try enhance every few loops when stocked
        if safety % 5 == 0:
            before = len(log)
            wallet = _try_enhance(uid, wallet, log, rng)
            if len(log) > before:
                enhances += 1

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
        show = hunts <= 2 or (
            outcome.get("won") and c["level"] in (2, 3, 5, 7, 9, 10)
            and c["level"] not in printed_levels
        )
        if show and outcome.get("won"):
            printed_levels.add(c["level"])
        if show:
            # compact hunt line
            print(f"⚔️ Hunt#{hunts} Lv.{c['level']} | "
                  f"{'WIN' if outcome.get('won') or outcome.get('draw') else 'LOSE'} "
                  f"{outcome.get('monster_name')} · EXP+{outcome.get('exp_gained', 0)} · "
                  f"karma {c['karma']}")

        if outcome.get("adventure"):
            events += 1
            ids = [a["id"] for a in outcome["adventure"]["actions"]]
            act = ids[0]
            for pref in ("inspect", "search", "help", "fill", "open", "bathe"):
                if pref in ids:
                    act = pref
                    break
            res = game.resolve_adventure(uid, act)
            wallet += int(res.get("gold_delta") or 0)
            if events <= 2:
                print(render.render_adventure_result(res))

        for kind, val in outcome.get("events") or []:
            if kind == "level_up":
                print(f"\n⭐ LEVEL UP → {val} | ví {wallet}g | W/L {wins}/{losses} | hunts {hunts}\n")
                log.append(f"⭐ Level {val}")
                wallet = _sell_all(uid, wallet)
                wallet = _try_crafts(uid, wallet, log)
                wallet = _manage_power(uid, wallet, log)
                wallet = _stock_smith(uid, wallet, log)
                wallet = _try_enhance(uid, wallet, log, rng)

    # final enhance push
    for _ in range(8):
        wallet = _stock_smith(uid, wallet, log)
        c = game.get_character(uid)
        tier = str((c.get("weapon") or {}).get("tier") or "A").lower()
        _grant(uid, f"enhance_stone_{tier}", 6)
        bone = {"a": "monster_bone_s", "b": "monster_bone_m", "c": "monster_bone_l"}.get(tier, "monster_bone_s")
        _grant(uid, bone, 6)
        if tier == "b":
            _grant(uid, "iron_ore", 6)
        # buy max luck pack to demonstrate 36% cap
        for lid in ("charm_luck_l", "charm_luck_m", "charm_luck_s"):
            cons = data_store.get_consumables()
            idx = next((i for i, it in enumerate(cons, 1) if it.get("id") == lid), None)
            if idx and wallet >= cons[idx - 1]["price"]:
                r = shop.purchase_consumable(uid, idx, wallet)
                if r.ok:
                    wallet -= r.cost
        before = len(log)
        wallet = _try_enhance(uid, wallet, log, rng)
        if len(log) == before:
            break
        enhances += 1

    wallet = _sell_all(uid, wallet)
    wallet = _try_crafts(uid, wallet, log)
    wallet = _manage_power(uid, wallet, log)

    c = game.get_character(uid)
    summary = game.character_summary(uid)
    from monster_game import blacksmith as bs

    print("\n" + "=" * 60)
    print("KẾT THÚC PLAYTHROUGH")
    print("=" * 60)
    print(render.render_character(summary))
    print()
    print(render.render_equipment(c))
    print()
    w = c.get("weapon") or {}
    print(f"Vũ khí: {bs.display_name(w)} · tier {w.get('tier')} · "
          f"HP {w.get('HP')} ATK {w.get('ATK')} DEF {w.get('DEF')} SPD {w.get('SPD')}")
    print()
    print("--- Session stats ---")
    print(f"Level: {c['level']} | EXP: {round(c['exp'])}/{data_store.exp_needed_for(c['level'])}")
    print(f"Hunts: {hunts} | W/L/D: {wins}/{losses}/{draws} | Events: {events} | Enhance tries: {enhances}")
    print(f"Wallet: {wallet}g | Power: {round(summary['power_total'])} | Karma: {c['karma']}")
    print(f"Bag: {len(c['bag'])} | Trophies: {len(c['monster'])} | Loc: {summary.get('location_name')}")
    print(f"Luck cap xác nhận: +{bs.MAX_LUCK_BONUS*100:.0f}% (không vượt trần)")
    print("\nKey log (smith / level / dungeon):")
    for line in log:
        if line.startswith(("⭐", "✅", "💥", "🏰", "🗺️", "🛒 Mua Bùa", "🛒 Mua charm", "🗡️", "🔨")):
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
        "enhances": enhances,
        "wallet": wallet,
        "power": summary["power_total"],
        "karma": c["karma"],
        "weapon_enhance": int(w.get("enhance_level") or 0),
        "weapon": bs.display_name(w),
        "luck_cap": bs.MAX_LUCK_BONUS,
        "reached_10": c["level"] >= 10,
        "log": log,
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
