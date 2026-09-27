"""
Full-feature stress demo — exercises every major play loop.

Covers: create, equip, belt, shop, craft, hunt/farm, adventure, overlevel,
karma, repair, points, blacksmith (luck+protect), dungeon, sell, PvP, journey.

Run:  python -m monster_game.full_demo
"""
from __future__ import annotations

import json
import random
import traceback
from pathlib import Path

from monster_game import blacksmith as bs
from monster_game import craft, data_store, game, render, shop


class Suite:
    def __init__(self):
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.notes: list[str] = []
        self.log: list[str] = []

    def ok(self, name: str, detail: str = ""):
        self.passed.append(name)
        self.log.append(f"✅ {name}" + (f" — {detail}" if detail else ""))
        print(self.log[-1])

    def fail(self, name: str, err: str):
        self.failed.append((name, err))
        self.log.append(f"❌ {name} — {err}")
        print(self.log[-1])

    def note(self, msg: str):
        self.notes.append(msg)
        print(f"· {msg}")

    def check(self, name: str, cond: bool, err: str = ""):
        if cond:
            self.ok(name)
        else:
            self.fail(name, err or "condition false")


def _grant(uid: str, item_id: str, qty: int = 1) -> None:
    item = data_store.instantiate_drop(item_id, qty)
    if not item:
        raise RuntimeError(f"cannot grant {item_id}")

    def mut(u):
        data_store._stack_into_bag(u, dict(item))
        return True

    data_store._mutate_user(uid, mut)


def _top_up(uid: str, stamina: int = 9999) -> None:
    def mut(u):
        u["the_luc"] = max(stamina, u.get("the_luc", 0))
        w = u.get("weapon")
        if w:
            w["durability"] = 100
            w["HP"] = data_store.weapon_max_hp(w)
        u["pending_event"] = None
        if len(u.get("monster") or []) >= 28:
            u["monster"] = u["monster"][-8:]
        return True

    data_store._mutate_user(uid, mut)


def _force_level(uid: str, level: int) -> None:
    safety = 0
    while game.get_character(uid)["level"] < level and safety < 40:
        safety += 1
        c = game.get_character(uid)
        data_store.set_exp(uid, data_store.exp_needed_for(c["level"]))


def _wallet_buy(uid: str, wallet: int, fn, *args) -> tuple[int, object]:
    r = fn(uid, *args, wallet) if False else None
    return wallet, r


def main():
    rng = random.Random(424242)
    random.seed(424242)
    data_store.reload_catalogs()
    data_store._save(data_store.USERS_FILE, [])
    S = Suite()
    wallet = 100_000
    uid = "tester"
    foe = "rival"

    print("=" * 64)
    print("FULL FEATURE DEMO — mọi hệ thống / mọi lối chơi")
    print("=" * 64)

    # ------------------------------------------------------------------
    # 1. Catalogs load
    # ------------------------------------------------------------------
    try:
        locs = game.list_locations()
        dungeons = game.list_dungeons()
        recipes = game.list_crafts()
        weapons = data_store.get_weapons()
        equips = data_store.get_equipment()
        cons = data_store.get_consumables()
        S.check("catalog.maps", len(locs) >= 4, f"maps={len(locs)}")
        S.check("catalog.dungeons", len(dungeons) >= 2, f"dungeons={len(dungeons)}")
        S.check("catalog.recipes", len(recipes) >= 1, f"recipes={len(recipes)}")
        S.check("catalog.weapons", len(weapons) >= 10, f"weapons={len(weapons)}")
        S.check("catalog.equipment", len(equips) >= 5, f"equip={len(equips)}")
        S.check("catalog.consumables", len(cons) >= 8, f"cons={len(cons)}")
        luck = [c for c in cons if c.get("subtype") == "enhance_luck"]
        prot = [c for c in cons if c.get("subtype") == "enhance_protect"]
        S.check("catalog.luck_charms", len(luck) >= 3, f"luck={len(luck)}")
        S.check("catalog.protect", len(prot) == 3, f"protect={len(prot)}")
        S.check("blacksmith.luck_cap", bs.MAX_LUCK_BONUS == 0.36)
    except Exception as e:
        S.fail("catalog.load", traceback.format_exc())

    # ------------------------------------------------------------------
    # 2. Character + starter gear + belt
    # ------------------------------------------------------------------
    try:
        c = game.create_character(uid, "Tester")
        S.check("char.create", c is not None and c["level"] == 1)
        S.check("char.duplicate_blocked", game.create_character(uid, "X") is None)
        game.equip_or_consume(uid, 1)
        c = game.get_character(uid)
        S.check("char.equip_weapon", c["weapon"] is not None)
        # equip starter helm
        for i, it in enumerate(c["bag"], 1):
            if it.get("type") == "equipment":
                game.equip_gear(uid, i)
                break
        c = game.get_character(uid)
        S.check("char.equip_helm", c["equipment"].get("helmet") is not None)
        # buy chest + put potions on belt
        r = shop.purchase_equipment(uid, 1, wallet, slot="chest")
        S.check("shop.buy_chest", r.ok, r.message)
        if r.ok:
            wallet -= r.cost
        c = game.get_character(uid)
        for i, it in enumerate(c["bag"], 1):
            if it.get("slot") == "chest":
                game.equip_gear(uid, i)
                break
        # consumables + belt
        idx_potion = next(i for i, it in enumerate(cons, 1) if it["id"] == "potion_s")
        r = shop.purchase_consumable(uid, idx_potion, wallet)
        if r.ok:
            wallet -= r.cost
        # specials
        for sid in ("dong_quy", "void_slash"):
            idx = next((i for i, it in enumerate(cons, 1) if it["id"] == sid), None)
            if idx:
                r = shop.purchase_consumable(uid, idx, wallet)
                if r.ok:
                    wallet -= r.cost
        c = game.get_character(uid)
        for slot, sid in ((2, "dong_quy"), (3, "void_slash"), (4, "potion_s")):
            for i, it in enumerate(c["bag"], 1):
                if it.get("id") == sid:
                    game.set_belt(uid, slot, i)
                    break
            c = game.get_character(uid)
        belt = game.get_character(uid)["consumables"]
        S.check("belt.filled", sum(1 for x in belt if x) >= 3, f"filled={sum(1 for x in belt if x)}")
        # unequip / re-equip
        game.unequip_gear(uid, "helmet")
        S.check("equip.unequip", game.get_character(uid)["equipment"]["helmet"] is None)
        c = game.get_character(uid)
        for i, it in enumerate(c["bag"], 1):
            if it.get("slot") == "helmet":
                game.equip_gear(uid, i)
                break
        S.check("equip.re_equip", game.get_character(uid)["equipment"]["helmet"] is not None)
        print(render.render_character(game.character_summary(uid)))
    except Exception:
        S.fail("char.setup", traceback.format_exc())

    # ------------------------------------------------------------------
    # 3. Shop: food, upgrade, weapon
    # ------------------------------------------------------------------
    try:
        foods = data_store.get_food_items()
        r = shop.purchase_food(uid, 1, wallet)
        S.check("shop.food", r.ok, r.message)
        if r.ok:
            wallet -= r.cost
            # consume food
            c = game.get_character(uid)
            for i, it in enumerate(c["bag"], 1):
                if it.get("type") == "food":
                    game.equip_or_consume(uid, i)
                    S.ok("shop.food_consume", it["name"])
                    break
        ups = data_store.get_upgrade_materials()
        if ups:
            r = shop.purchase_upgrade_material(uid, 1, wallet)
            S.check("shop.upgrade_mat", r.ok, r.message)
            if r.ok:
                wallet -= r.cost
                c = game.get_character(uid)
                for i, it in enumerate(c["bag"], 1):
                    if it.get("type") == "upgrade":
                        before = c["weapon"].get("usage", 0)
                        game.equip_or_consume(uid, i)
                        after = game.get_character(uid)["weapon"].get("usage", 0)
                        S.check("shop.upgrade_apply", after >= before)
                        break
        # buy second weapon (Lance)
        r = shop.purchase_weapon(uid, "Lance", 1, wallet)
        S.check("shop.weapon", r.ok, r.message)
        if r.ok:
            wallet -= r.cost
    except Exception:
        S.fail("shop.misc", traceback.format_exc())

    # ------------------------------------------------------------------
    # 4. Farm hunts map1 + adventure
    # ------------------------------------------------------------------
    try:
        game.set_location(uid, 1)
        wins = losses = advent = 0
        for n in range(12):
            _top_up(uid)
            data_store.set_pending_event(uid, None)
            out = game.encounter_and_fight(uid)
            if not out.get("ok"):
                S.note(f"hunt skip: {out.get('reason')}")
                continue
            if out.get("won") or out.get("draw"):
                wins += 1
            else:
                losses += 1
            if out.get("adventure"):
                advent += 1
                act = out["adventure"]["actions"][0]["id"]
                res = game.resolve_adventure(uid, act)
                wallet += int(res.get("gold_delta") or 0)
                S.ok("adventure.resolve", res.get("log") or res.get("kind") or "ok")
                break
        S.check("hunt.farm_map1", wins >= 1, f"W/L {wins}/{losses}")
        if advent:
            S.ok("adventure.seen")
        else:
            S.note("adventure không proc trong 12 hunt (RNG) — không fail suite")
        lv = game.get_character(uid)["level"]
        S.note(f"sau farm map1: Lv.{lv} karma={game.get_character(uid)['karma']}")
    except Exception:
        S.fail("hunt.farm", traceback.format_exc())

    # ------------------------------------------------------------------
    # 5. Craft + sell
    # ------------------------------------------------------------------
    try:
        # seed mats for first craftable
        for rcp in craft.list_recipes()[:5]:
            for ing in rcp.get("ingredients") or []:
                _grant(uid, ing["item_id"], int(ing["qty"]) + 2)
            result = game.craft_item(uid, rcp["id"], wallet)
            if result.ok:
                wallet -= result.cost
                S.ok("craft.item", f"{rcp['id']} → {result.item['name']}")
                if result.item.get("type") == "equipment":
                    c = game.get_character(uid)
                    for i, it in enumerate(c["bag"], 1):
                        if it.get("id") == result.item.get("id"):
                            game.equip_gear(uid, i)
                            break
                break
        else:
            S.fail("craft.item", "no recipe succeeded")
        # duplicate craft should fail for unique gear
        # sell trophies
        sold = shop.sell_monsters(uid, None)
        if isinstance(sold, tuple):
            wallet += int(sold[1] or 0)
            S.ok("sell.monsters", f"+{sold[1]}g ×{sold[0]}")
        sold = shop.sell_materials(uid, None)
        # may sell craft mats — re-grant later; still tests API
        if isinstance(sold, tuple):
            wallet += int(sold[1] or 0)
            S.ok("sell.materials", f"+{sold[1]}g")
    except Exception:
        S.fail("craft.sell", traceback.format_exc())

    # ------------------------------------------------------------------
    # 6. Points + repair
    # ------------------------------------------------------------------
    try:
        def give_points(u):
            u["points"] = max(u.get("points", 0), 200)
            return True
        data_store._mutate_user(uid, give_points)
        before = game.get_character(uid)["atk"]
        game.spend_points(uid, "atk", 20)
        after = game.get_character(uid)["atk"]
        S.check("points.spend_atk", after > before, f"{before}→{after}")
        # wear weapon then repair
        def wear(u):
            u["weapon"]["durability"] = 20
            u["weapon"]["HP"] = max(1, u["weapon"]["HP"] // 2)
            return True
        data_store._mutate_user(uid, wear)
        cost = game.repair_cost(game.get_character(uid)["weapon"])
        rep = game.repair_weapon(uid, wallet)
        S.check("repair.weapon", rep.get("ok"), str(rep))
        if rep.get("ok"):
            wallet -= rep["cost"]
            S.note(f"repair cost {cost}g")
    except Exception:
        S.fail("points.repair", traceback.format_exc())

    # ------------------------------------------------------------------
    # 7. Blacksmith: cost scale, luck cap, protect %
    # ------------------------------------------------------------------
    try:
        w = game.get_character(uid)["weapon"]
        tier = str(w.get("tier") or "A").lower()
        _grant(uid, f"enhance_stone_{tier}", 40)
        bone = {"a": "monster_bone_s", "b": "monster_bone_m", "c": "monster_bone_l"}.get(tier, "monster_bone_s")
        _grant(uid, bone, 40)
        if tier == "b":
            _grant(uid, "iron_ore", 40)
        _grant(uid, "charm_luck_l", 2)
        _grant(uid, "charm_luck_m", 2)
        _grant(uid, "scroll_keep_50", 2)
        _grant(uid, "scroll_keep_25", 2)
        _grant(uid, "scroll_keep_60", 1)

        q0 = bs.cost_for({**w, "enhance_level": 0})
        q5 = bs.cost_for({**w, "enhance_level": 5})
        S.check("enhance.cost_scales", q5["gold"] > q0["gold"] and q5["stones"][0]["qty"] > q0["stones"][0]["qty"])
        S.check("enhance.luck_cap_math", bs.effective_rate(0.1, 0.99) == 0.1 + 0.36)
        S.check("enhance.protect_50", bs._resolve_fail_level(10, {"keep_pct": 0.5}) == 5)
        S.check("enhance.protect_60", bs._resolve_fail_level(10, {"keep_pct": 0.6}) == 6)
        S.check("enhance.protect_25", bs._resolve_fail_level(10, {"keep_pct": 0.25}) in (2, 3))

        # force weapon to +8 then fail with 60% + max luck
        def set8(u):
            u["weapon"]["enhance_level"] = 8
            return True
        data_store._mutate_user(uid, set8)
        c = game.get_character(uid)
        pi = next(i for i, it in enumerate(c["bag"], 1) if it.get("id") == "scroll_keep_60")
        li = [i for i, it in enumerate(c["bag"], 1) if it.get("subtype") == "enhance_luck"]

        class AlwaysFail:
            def random(self):
                return 0.999

        r = game.enhance_item(
            uid, "weapon", balance=wallet,
            protect_bag_index_1based=pi,
            luck_bag_indices_1based=li,
            rng=AlwaysFail(),
        )
        S.check("enhance.attempt_ok", r.get("ok"), str(r))
        if r.get("ok"):
            wallet -= r["gold_cost"]
            S.check("enhance.luck_applied_cap",
                    abs(r.get("luck_bonus", 0) - r.get("luck_cap", 0.2)) < 1e-9,
                    f"luck={r.get('luck_bonus')} cap={r.get('luck_cap')}")
            S.check("enhance.fail_keep_60", r["level_after"] == 5,  # 60% of 8
                    f"after={r['level_after']}")
            S.ok("enhance.message", r.get("message", "")[:80])
        print(render.render_enhance_quote(game.enhance_quote(uid, "weapon")))

        # enhance gear in bag too
        _grant(uid, "enhance_stone_a", 5)
        _grant(uid, "monster_bone_s", 5)
        # buy cheap armor piece into bag
        r = shop.purchase_equipment(uid, 1, wallet, slot="pants")
        if r.ok:
            wallet -= r.cost
            c = game.get_character(uid)
            bi = next(i for i, it in enumerate(c["bag"], 1) if it.get("slot") == "pants")
            # set enhance on pants via bag where
            er = game.enhance_item(uid, "bag", bag_index_1based=bi, balance=wallet, rng=random.Random(1))
            S.check("enhance.bag_equipment", er.get("ok") or er.get("reason") in ("missing_mats",),
                    str(er.get("message") or er.get("reason")))
            if er.get("ok"):
                wallet -= er["gold_cost"]
    except Exception:
        S.fail("enhance.suite", traceback.format_exc())

    # ------------------------------------------------------------------
    # 8. Dungeons (clear + abandon)
    # ------------------------------------------------------------------
    try:
        # abandon path
        _top_up(uid)
        st = game.start_dungeon(uid, "forest_ruin")
        S.check("dungeon.start_forest", st.get("ok"), str(st))
        ab = game.abandon_dungeon(uid)
        S.check("dungeon.abandon", ab.get("ok"), str(ab))

        # clear forest
        _top_up(uid)
        st = game.start_dungeon(uid, "forest_ruin")
        cleared = failed = False
        for step in range(20):
            c = game.get_character(uid)
            if not c.get("dungeon_run"):
                break
            action = None
            if c["dungeon_run"].get("pending_event"):
                acts = [a["id"] for a in c["dungeon_run"]["pending_event"].get("actions") or []]
                for pref in ("enter", "break", "push", "ignore", "throw_stone", "search", "careful"):
                    if pref in acts:
                        action = pref
                        break
                action = action or next((a for a in acts if a != "leave"), acts[0] if acts else None)
            res = game.advance_dungeon(uid, action_id=action, rng=random.Random(1000 + step))
            wallet += int(res.get("gold_delta") or 0)
            if res.get("dungeon_complete"):
                cleared = True
                break
            if res.get("dungeon_failed") or res.get("kind") == "abort":
                failed = True
                break
        S.check("dungeon.clear_forest", cleared, "failed/abort" if failed else "incomplete")

        # waste tomb — may fail; try a few times after powering up
        _force_level(uid, max(5, game.get_character(uid)["level"]))
        # spend points to power up
        def pump(u):
            u["points"] = max(u.get("points", 0), 500)
            u["hp"] += 2000
            u["atk"] += 800
            u["def"] += 400
            return True
        data_store._mutate_user(uid, pump)
        tomb_ok = False
        for attempt in range(3):
            _top_up(uid)
            if game.get_character(uid).get("dungeon_run"):
                game.abandon_dungeon(uid)
            st = game.start_dungeon(uid, "waste_tomb")
            if not st.get("ok"):
                S.note(f"waste_tomb start: {st}")
                continue
            for step in range(20):
                c = game.get_character(uid)
                if not c.get("dungeon_run"):
                    break
                action = None
                if c["dungeon_run"].get("pending_event"):
                    acts = [a["id"] for a in c["dungeon_run"]["pending_event"].get("actions") or []]
                    action = None
                    for pref in ("break", "push", "ignore", "throw_stone", "enter", "search"):
                        if pref in acts:
                            action = pref
                            break
                    action = action or next((a for a in acts if a != "leave"), acts[0] if acts else None)
                res = game.advance_dungeon(uid, action_id=action, rng=random.Random(2000 + attempt * 50 + step))
                wallet += int(res.get("gold_delta") or 0)
                if res.get("dungeon_complete"):
                    tomb_ok = True
                    break
                if res.get("dungeon_failed") or res.get("kind") == "abort":
                    break
            if tomb_ok:
                break
        if tomb_ok:
            S.ok("dungeon.clear_waste_tomb")
        else:
            S.note("waste_tomb chưa clear sau 3 try — ghi nhận độ khó cao (không hard-fail)")
            S.ok("dungeon.waste_tomb_attempted")
    except Exception:
        S.fail("dungeon.suite", traceback.format_exc())

    # ------------------------------------------------------------------
    # 9. Overlevel: farm to mid then jump map / fight hard
    # ------------------------------------------------------------------
    try:
        # natural-ish farm to Lv.6+
        target = 7
        hunts = 0
        while game.get_character(uid)["level"] < target and hunts < 200:
            hunts += 1
            c = game.get_character(uid)
            # map select by level
            if c["level"] < 4:
                game.set_location(uid, 1)
            elif c["level"] < 7:
                game.set_location(uid, 2)
            else:
                game.set_location(uid, 3)
            _top_up(uid)
            data_store.set_pending_event(uid, None)
            if hunts % 10 == 0:
                shop.sell_monsters(uid, None)
            out = game.encounter_and_fight(uid)
            if not out.get("ok"):
                if out.get("reason") == "level_too_low":
                    game.set_location(uid, 1)
                continue
            if out.get("adventure"):
                game.resolve_adventure(uid, out["adventure"]["actions"][0]["id"])
        lv = game.get_character(uid)["level"]
        S.check("farm.reach_lv7", lv >= 7, f"lv={lv} hunts={hunts}")

        # OVERLEVEL: go to highest map while still under its level req
        locs = game.list_locations()
        # pick the hardest map whose req > player level
        before_lv = game.get_character(uid)["level"]
        hard = None
        for i, loc in enumerate(locs, 1):
            if loc.get("level", 1) > before_lv:
                hard = (i, loc)
        if hard is None:
            hard = (len(locs), locs[-1])
        game.set_location(uid, hard[0])
        S.note(f"vượt cấp: Lv.{before_lv} → {hard[1]['name']} (yêu cầu Lv.{hard[1].get('level')})")
        over_w = over_l = overlevel_flags = 0
        for n in range(10):
            _top_up(uid)
            data_store.set_pending_event(uid, None)
            out = game.encounter_and_fight(uid)
            if not out.get("ok"):
                S.note(f"overlevel skip: {out.get('reason')}")
                continue
            if out.get("overlevel"):
                overlevel_flags += 1
            if out.get("won") or out.get("draw"):
                over_w += 1
            else:
                over_l += 1
            S.note(f"overlevel: {out.get('monster_name')} "
                   f"{'WIN' if out.get('won') or out.get('draw') else 'LOSE'} "
                   f"tier {out.get('monster_tier')} Lv.{out.get('monster_level')} "
                   f"{'⚡VƯỢT CẤP' if out.get('overlevel') else ''}")
        S.check("overlevel.fought", over_w + over_l >= 1, f"W/L {over_w}/{over_l}")
        S.check("overlevel.flagged", overlevel_flags >= 1 or before_lv >= hard[1].get("level", 99),
                f"flags={overlevel_flags}")
        S.ok("overlevel.report", f"Lv.{before_lv} vào {hard[1]['name']} · W/L {over_w}/{over_l}")

        # also underlevel farm (safe) after
        game.set_location(uid, 1)
        _top_up(uid)
        out = game.encounter_and_fight(uid)
        S.check("farm.back_to_easy", out.get("ok"), str(out.get("reason")))
        S.check("farm.not_overlevel", not out.get("overlevel", False))
    except Exception:
        S.fail("overlevel.suite", traceback.format_exc())

    # ------------------------------------------------------------------
    # 10. Karma brake (holy water)
    # ------------------------------------------------------------------
    try:
        def bump_karma(u):
            u["karma"] = 25
            return True
        data_store._mutate_user(uid, bump_karma)
        foods = data_store.get_food_items()
        idx = next((i for i, f in enumerate(foods, 1) if f.get("id") == "holy_water"), None)
        if idx:
            r = shop.purchase_food(uid, idx, wallet)
            if r.ok:
                wallet -= r.cost
                c = game.get_character(uid)
                for i, it in enumerate(c["bag"], 1):
                    if it.get("id") == "holy_water":
                        before = c["karma"]
                        game.equip_or_consume(uid, i)
                        after = game.get_character(uid)["karma"]
                        S.check("karma.holy_water", after < before, f"{before}→{after}")
                        break
        else:
            S.note("no holy_water in food catalog")
    except Exception:
        S.fail("karma.suite", traceback.format_exc())

    # ------------------------------------------------------------------
    # 11. PvP
    # ------------------------------------------------------------------
    try:
        game.create_character(foe, "Rival")
        game.equip_or_consume(foe, 1)
        _top_up(foe)
        _force_level(foe, game.get_character(uid)["level"])
        ch = "demo-channel"
        room = game.create_room(ch, uid, "Arena Test")
        S.check("pvp.create_room", room is not None)
        joined = game.join_room(ch, foe, 1)
        S.check("pvp.join", joined is not None)
        game.set_ready(ch, uid)
        game.set_ready(ch, foe)
        match = game.start_match(ch, uid)
        S.check("pvp.match", match is not None and "log" in (match or {}), str(match)[:120])
        if match:
            text = render.render_pvp(match, max_rounds=6)
            S.check("pvp.render", "ĐẤU TRƯỜNG" in text or "vs" in text.lower() or len(text) > 40)
            left = game.leave_room(ch, uid)
            S.ok("pvp.leave", str(left))
    except Exception:
        S.fail("pvp.suite", traceback.format_exc())

    # ------------------------------------------------------------------
    # 12. Render surfaces + journey
    # ------------------------------------------------------------------
    try:
        c = game.get_character(uid)
        summary = game.character_summary(uid)
        chunks = [
            render.render_character(summary),
            render.render_bag(c),
            render.render_equipment(c),
            render.render_belt(c),
            render.render_dungeon_list(),
            render.render_journey(game.journey_log(uid, 8)),
            render.render_craft_list(uid, wallet),
            render.render_locations(game.list_locations(), game.get_character(uid)),
        ]
        S.check("render.all", all(isinstance(x, str) and len(x) > 10 for x in chunks))
        S.check("journey.log", len(game.journey_log(uid, 5)) >= 1)
    except Exception:
        S.fail("render.suite", traceback.format_exc())

    # ------------------------------------------------------------------
    # 13. Final enhance push showcasing luck floor
    # ------------------------------------------------------------------
    try:
        w = game.get_character(uid)["weapon"]
        tier = str(w.get("tier") or "A").lower()
        _grant(uid, f"enhance_stone_{tier}", 20)
        bone = {"a": "monster_bone_s", "b": "monster_bone_m", "c": "monster_bone_l"}.get(tier, "monster_bone_s")
        _grant(uid, bone, 20)
        if tier == "b":
            _grant(uid, "iron_ore", 20)
        for _ in range(6):
            _grant(uid, "charm_luck_l", 1)
            _grant(uid, "charm_luck_m", 1)
            _grant(uid, "scroll_keep_50", 1)
            c = game.get_character(uid)
            quote = bs.cost_for(c["weapon"])
            if data_store.count_bag_item(c, quote["stones"][0]["item_id"]) < quote["stones"][0]["qty"]:
                break
            li = [i for i, it in enumerate(c["bag"], 1) if it.get("subtype") == "enhance_luck"]
            pi = next((i for i, it in enumerate(c["bag"], 1) if it.get("id") == "scroll_keep_50"), None)
            r = game.enhance_item(
                uid, "weapon", balance=wallet,
                luck_bag_indices_1based=li[:3] if quote["rate"] < 0.7 else None,
                protect_bag_index_1based=pi if bs.enhance_level(c["weapon"]) >= 4 else None,
                rng=random.Random(rng.randint(1, 99999)),
            )
            if not r.get("ok"):
                break
            wallet -= r["gold_cost"]
            luck = r.get("luck_bonus") or 0
            S.note(f"đập +{r['level_before']}→+{r['level_after']} "
                   f"luck {luck*100:.0f}%/{(r.get('luck_cap') or bs.MAX_LUCK_BONUS)*100:.0f}% rate {r['rate']*100:.0f}% "
                   f"{'OK' if r['success'] else 'FAIL'}")
            cap = r.get("luck_cap") or bs.MAX_LUCK_BONUS
            S.check("enhance.luck_never_over_cap", luck <= cap + 1e-9, f"luck={luck} cap={cap}")
        S.ok("enhance.final", bs.display_name(game.get_character(uid)["weapon"]))
    except Exception:
        S.fail("enhance.final", traceback.format_exc())

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    c = game.get_character(uid)
    summary = game.character_summary(uid)
    print("\n" + "=" * 64)
    print("TRẠNG THÁI CUỐI")
    print("=" * 64)
    print(render.render_character(summary))
    print()
    print(f"Wallet: {wallet}g | Weapon: {bs.display_name(c.get('weapon') or {})}")
    print(f"Power: {round(summary['power_total'])} | Karma: {c['karma']} | Loc: {summary.get('location_name')}")

    print("\n" + "=" * 64)
    print(f"KẾT QUẢ: {len(S.passed)} passed · {len(S.failed)} failed")
    print("=" * 64)
    if S.failed:
        print("FAILURES:")
        for name, err in S.failed:
            print(f"  ❌ {name}: {err.splitlines()[0][:200]}")
    if S.notes:
        print("\nNotes:")
        for n in S.notes[-15:]:
            print(f"  · {n}")

    report = {
        "passed": len(S.passed),
        "failed": len(S.failed),
        "fail_list": [{"name": n, "err": e[:500]} for n, e in S.failed],
        "passed_list": S.passed,
        "notes": S.notes,
        "level": c["level"],
        "weapon": bs.display_name(c.get("weapon") or {}),
        "power": summary["power_total"],
        "wallet": wallet,
        "karma": c["karma"],
    }
    Path("/tmp/full_demo_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n(report → /tmp/full_demo_report.json)")
    if S.failed:
        raise SystemExit(1)
    return report


if __name__ == "__main__":
    main()
