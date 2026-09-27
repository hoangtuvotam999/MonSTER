"""
Party + remaining render/API coverage demo.

Run:  python -m monster_game.party_demo
"""
from __future__ import annotations

import json
import random
import traceback
from pathlib import Path

from monster_game import data_store, game, party, render, shop


def _top(uid: str) -> None:
    def mut(u):
        u["the_luc"] = 9999
        if u.get("weapon"):
            u["weapon"]["durability"] = 100
            u["weapon"]["HP"] = data_store.weapon_max_hp(u["weapon"])
        u["pending_event"] = None
        u["dungeon_run"] = None
        return True
    data_store._mutate_user(uid, mut)


def _make(uid: str, name: str) -> None:
    if game.get_character(uid):
        return
    game.create_character(uid, name)
    game.equip_or_consume(uid, 1)
    _top(uid)


class Suite:
    def __init__(self):
        self.passed, self.failed, self.log = [], [], []

    def ok(self, n, d=""):
        self.passed.append(n)
        msg = f"✅ {n}" + (f" — {d}" if d else "")
        self.log.append(msg)
        print(msg)

    def fail(self, n, e):
        self.failed.append((n, e))
        msg = f"❌ {n} — {e.splitlines()[0][:180]}"
        self.log.append(msg)
        print(msg)

    def check(self, n, cond, err=""):
        (self.ok if cond else self.fail)(n, "" if cond else (err or "false"))


def main():
    random.seed(7)
    data_store.reload_catalogs()
    data_store._save(data_store.USERS_FILE, [])
    party.clear_all()
    S = Suite()
    ch = "party-channel"
    wallet = 50_000

    print("=" * 64)
    print("PARTY + REMAINING RENDER DEMO")
    print("=" * 64)

    # ---- setup 3 hunters ----
    try:
        for uid, name in (("a", "Alpha"), ("b", "Bravo"), ("c", "Charlie")):
            _make(uid, name)
        S.ok("setup.trio")
    except Exception:
        S.fail("setup.trio", traceback.format_exc())
        raise SystemExit(1)

    # ---- party lifecycle ----
    try:
        r = game.create_party(ch, "a", "Hunter Squad")
        S.check("party.create", r.get("ok"), str(r))
        print(render.render_party_action(r))
        r = game.create_party(ch, "a", "Dup")
        S.check("party.no_dup", not r.get("ok") and r.get("reason") == "already_in_party")
        r = game.join_party(ch, "b", 1)
        S.check("party.join_b", r.get("ok"), str(r))
        r = game.join_party(ch, "c", 1)
        S.check("party.join_c", r.get("ok"), str(r))
        print(render.render_party_list(ch))
        print(render.render_party(game.list_parties(ch)[0]))
        # kick
        r = game.kick_party_member(ch, "a", "c")
        S.check("party.kick", r.get("ok") and "c" not in r["party"]["members"], str(r))
        r = game.join_party(ch, "c", 1)
        S.check("party.rejoin", r.get("ok"))
        # location
        r = game.set_party_location(ch, "a", 1)
        S.check("party.set_location", r.get("ok"), str(r))
        for uid in ("a", "b", "c"):
            S.check(f"party.sync_loc_{uid}",
                    str(game.get_character(uid)["locationID"]) == str(r["location"]["ID"]))
    except Exception:
        S.fail("party.lifecycle", traceback.format_exc())

    # ---- party hunt (shared HP) ----
    try:
        for uid in ("a", "b", "c"):
            _top(uid)
        # force encounter-friendly: retry
        hunt = None
        for seed in range(50):
            hunt = game.party_hunt(ch, "a", rng=random.Random(seed))
            if hunt.get("ok"):
                break
        S.check("party.hunt_ok", hunt and hunt.get("ok"), str(hunt))
        if hunt and hunt.get("ok"):
            text = render.render_party_hunt(hunt)
            print(text)
            S.check("party.hunt_render", "SĂN TỔ ĐỘI" in text and len(text) > 40)
            S.check("party.hunt_segments", len(hunt.get("segments") or []) >= 1)
            if hunt.get("won"):
                S.ok("party.hunt_win", f"rewards={len(hunt.get('rewards') or [])}")
                S.check("party.hunt_reward_all",
                        len(hunt.get("rewards") or []) == len(hunt.get("members") or []))
            else:
                S.ok("party.hunt_lose_ok", f"hp_left={hunt.get('monster_hp_left')}")
    except Exception:
        S.fail("party.hunt", traceback.format_exc())

    # ---- party dungeon ----
    try:
        for uid in ("a", "b", "c"):
            _top(uid)
        st = game.party_start_dungeon(ch, "a", "forest_ruin")
        S.check("party.dungeon_start", st.get("ok"), str(st))
        print(render.render_party(game.list_parties(ch)[0]))
        # non-leader cannot advance
        bad = game.party_advance_dungeon(ch, "b")
        S.check("party.dungeon_leader_only", not bad.get("ok"), str(bad))
        cleared = False
        for step in range(16):
            p = game.list_parties(ch)[0]
            if not p.get("dungeon_run"):
                break
            action = None
            run = p["dungeon_run"]
            if run.get("pending_event"):
                acts = [a["id"] for a in run["pending_event"].get("actions") or []]
                action = "enter" if "enter" in acts else (acts[0] if acts else None)
            res = game.party_advance_dungeon(ch, "a", action_id=action, rng=random.Random(10 + step))
            print(render.render_dungeon_result(res)[:300])
            if res.get("dungeon_complete"):
                cleared = True
                break
            if res.get("dungeon_failed") or res.get("kind") == "abort":
                break
        if cleared:
            S.ok("party.dungeon_clear")
        else:
            # try abandon path with fresh dungeon
            for uid in ("a", "b", "c"):
                _top(uid)
            if game.list_parties(ch)[0].get("dungeon_run"):
                ab = game.party_abandon_dungeon(ch, "a")
                S.check("party.dungeon_abandon", ab.get("ok"), str(ab))
            else:
                st = game.party_start_dungeon(ch, "a", "forest_ruin")
                if st.get("ok"):
                    ab = game.party_abandon_dungeon(ch, "a")
                    S.check("party.dungeon_abandon", ab.get("ok"), str(ab))
                S.ok("party.dungeon_attempted")
    except Exception:
        S.fail("party.dungeon", traceback.format_exc())

    # ---- leave / promote / disband ----
    try:
        # ensure no dungeon
        p0 = game.list_parties(ch)[0]
        if p0.get("dungeon_run"):
            game.party_abandon_dungeon(ch, "a")
        r = game.leave_party(ch, "a")  # leader leaves → promote
        S.check("party.leader_leave_promote", r.get("ok") and r.get("promoted"), str(r))
        print(render.render_party_action(r))
        # remaining leader disbands
        leader = game.list_parties(ch)[0]["leader"]
        r = game.disband_party(ch, leader)
        S.check("party.disband", r.get("ok") and r.get("disbanded"), str(r))
        S.check("party.empty", len(game.list_parties(ch)) == 0)
        print(render.render_party_list(ch))
    except Exception:
        S.fail("party.teardown", traceback.format_exc())

    # ---- remaining renders ----
    print("\n--- Remaining renders ---\n")
    try:
        uid = "a"
        c = game.get_character(uid)
        # ensure some trophies/materials
        shop.sell_monsters(uid, None)  # may be empty
        # buy stuff for purchase/repair renders
        foods = data_store.get_food_items()
        fr = shop.purchase_food(uid, 1, wallet)
        if fr.ok:
            wallet -= fr.cost
        ur = shop.purchase_upgrade_material(uid, 1, wallet)
        if ur.ok:
            wallet -= ur.cost
        # wear for repair
        def wear(u):
            u["weapon"]["durability"] = 40
            return True
        data_store._mutate_user(uid, wear)
        rep = game.repair_weapon(uid, wallet)
        if rep.get("ok"):
            wallet -= rep["cost"]

        # craft for craft_result
        from monster_game import craft
        for rcp in craft.list_recipes()[:3]:
            for ing in rcp.get("ingredients") or []:
                item = data_store.instantiate_drop(ing["item_id"], int(ing["qty"]) + 1)
                if item:
                    data_store._mutate_user(uid, lambda u, it=dict(item): (
                        data_store._stack_into_bag(u, it), True)[1])
            cr = game.craft_item(uid, rcp["id"], wallet)
            if cr.ok:
                wallet -= cr.cost
                print(render.render_craft_result(cr))
                S.ok("render.craft_result")
                break

        checks = {
            "render.failure": render.render_failure({"reason": "no_location"}),
            "render.shop_menu": render.render_shop_menu(),
            "render.weapon_list": render.render_weapon_list("Sword", c, wallet),
            "render.food_list": render.render_food_list(wallet),
            "render.upgrade_list": render.render_upgrade_list(wallet),
            "render.purchase": render.render_purchase(fr),
            "render.repair": render.render_repair(rep if rep.get("ok") else {"ok": False, "reason": "already_full", "cost": 0}),
            "render.sale": render.render_sale(2, 1500),
            "render.locations": render.render_locations(game.list_locations(), c),
            "render.rooms": render.render_rooms(game.list_rooms("x") or []),
            "render.trophies": render.render_trophies(c),
            "render.materials": render.render_materials(c),
            "render.equipment_shop": render.render_equipment_shop("helmet", wallet),
            "render.consumable_shop": render.render_consumable_shop(wallet),
            "render.enhance_result": render.render_enhance_result(
                {"ok": True, "success": True, "message": "Đinh! +1", "gold_cost": 300}
            ),
            "render.adventure_prompt": render.render_adventure_prompt({
                "title": "Test", "intro": "Hi", "actions": [{"id": "go", "label": "Đi"}]
            }),
            "render.craft_list": render.render_craft_list(uid, wallet),
            "render.party_list_empty": render.render_party_list(ch),
        }
        # PvP rooms render with a room
        game.create_party(ch, "a", "Temp")  # recreate for nothing — use pvp rooms
        game.leave_party(ch, "a") if game.list_parties(ch) else None
        room = game.create_room("pvp-ch", "a", "Test Arena")
        game.join_room("pvp-ch", "b", 1)
        checks["render.rooms_filled"] = render.render_rooms(game.list_rooms("pvp-ch"))

        for name, text in checks.items():
            ok = isinstance(text, str) and len(text) > 5
            S.check(name, ok, f"len={len(text) if isinstance(text, str) else type(text)}")
            print(f"\n[{name}]\n{text[:400]}\n")
    except Exception:
        S.fail("render.remaining", traceback.format_exc())

    # ---- summary ----
    print("=" * 64)
    print(f"KẾT QUẢ: {len(S.passed)} passed · {len(S.failed)} failed")
    print("=" * 64)
    if S.failed:
        for n, e in S.failed:
            print(f"  ❌ {n}: {e.splitlines()[0][:200]}")
    report = {
        "passed": len(S.passed),
        "failed": len(S.failed),
        "passed_list": S.passed,
        "fail_list": [{"name": n, "err": e[:400]} for n, e in S.failed],
    }
    Path("/tmp/party_demo_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("(report → /tmp/party_demo_report.json)")
    if S.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
