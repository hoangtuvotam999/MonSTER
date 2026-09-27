"""
One-session demo: hunt → dungeon → blacksmith enhance loop.
Run: python -m monster_game.session_demo
"""
from __future__ import annotations

import random

from monster_game import blacksmith as bs
from monster_game import data_store, game, render, shop


def _top_up(pid: str, stamina: int = 600) -> None:
    def mut(u):
        u["the_luc"] = max(u.get("the_luc", 0), stamina)
        if u.get("weapon"):
            u["weapon"]["durability"] = 100
            u["weapon"]["HP"] = data_store.weapon_max_hp(u["weapon"])
        return True

    data_store._mutate_user(pid, mut)


def _grant(pid: str, item_id: str, qty: int = 1) -> None:
    drop = data_store.instantiate_drop(item_id, qty)
    if drop is None:
        c = data_store.get_consumable(item_id)
        if not c:
            return
        drop = {**dict(c), "qty": qty}

    def mut(u):
        data_store._stack_into_bag(u, dict(drop))
        return True

    data_store._mutate_user(pid, mut)


def _bag_qty(pid: str, item_id: str) -> int:
    u = game.get_character(pid)
    return data_store.count_bag_item(u, item_id)


def _print(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main() -> None:
    data_store.reload_catalogs()
    data_store._save(data_store.USERS_FILE, [])
    rng = random.Random(42)
    pid = "demo"
    gold = 50_000  # external wallet

    _print("1) TẠO NHÂN VẬT + TRANG BỊ")
    game.create_character(pid, "Hunter")
    game.equip_or_consume(pid, 1)
    c = game.get_character(pid)
    for i, it in enumerate(c["bag"], 1):
        if it.get("type") == "equipment":
            game.equip_gear(pid, i)
            break
    shop.purchase_equipment(pid, 1, gold, slot="chest")
    c = game.get_character(pid)
    for i, it in enumerate(c["bag"], 1):
        if it.get("slot") == "chest":
            game.equip_gear(pid, i)
            gold -= it["price"]
            break
    print(render.render_character(game.character_summary(pid)))

    _print("2) BẢNG GIÁ CƯỜNG HÓA (cost tăng theo cấp +)")
    w = game.get_character(pid)["weapon"]
    print(f"Vũ khí: {w['name']} tier {w.get('tier')} · +{bs.enhance_level(w)}")
    for fake_lvl in (0, 3, 7, 12):
        w["enhance_level"] = fake_lvl
        q = bs.cost_for(w)
        print(f"  +{fake_lvl}→+{q['next_level']}: rate {q['rate']*100:.0f}% "
              f"(+luck max {q['rate_with_max_luck']*100:.0f}%) · "
              f"vàng {q['gold']} · đá×{q['stones'][0]['qty']}")
    data_store._mutate_user(pid, lambda u: u["weapon"].update(enhance_level=0) or True)

    _print("3) SĂN QUÁI (map 1) — 3 trận")
    game.set_location(pid, 1)
    wins = 0
    for n in range(1, 4):
        _top_up(pid)
        data_store.set_pending_event(pid, None)
        out = game.encounter_and_fight(pid)
        if not out.get("ok"):
            print(f"#{n} lỗi: {out.get('reason')}")
            continue
        flag = "WIN" if out.get("won") or out.get("draw") else "LOSE"
        if out.get("won") or out.get("draw"):
            wins += 1
        print(f"#{n} [{flag}] {out.get('monster_name')} Tier {out.get('monster_tier')} "
              f"· EXP+{out.get('exp_gained', 0)} · drops={len(out.get('drops') or [])}")
        for d in out.get("drops") or []:
            print(f"     🎁 {d['name']} ×{d.get('qty', 1)}")
        if out.get("adventure"):
            act = out["adventure"]["actions"][0]["id"]
            adv = game.resolve_adventure(pid, act)
            print(f"     ✨ adventure → {adv.get('log') or adv.get('kind')}")
    print(f"Thắng {wins}/3 · Lv.{game.get_character(pid)['level']}")

    _print("4) DUNGEON — Di Tích Rừng Cổ")
    _top_up(pid, 800)
    start = game.start_dungeon(pid, "cong_tan_thu")
    print(f"Start: {start.get('dungeon')} (−{start.get('stamina_cost')} thể lực)")
    for step in range(14):
        c = game.get_character(pid)
        if not c.get("dungeon_run"):
            break
        action = None
        if c["dungeon_run"].get("pending_event"):
            acts = [a["id"] for a in c["dungeon_run"]["pending_event"].get("actions") or []]
            action = "enter" if "enter" in acts else (acts[0] if acts else None)
        result = game.advance_dungeon(pid, action_id=action, rng=random.Random(100 + step))
        kind = result.get("kind")
        if kind == "await_choice":
            print(render.render_dungeon_result(result))
            continue
        line = render.render_dungeon_result(result)
        # compact: first 2 lines
        print("\n".join(line.splitlines()[:6]))
        if result.get("gold_delta"):
            gold += int(result["gold_delta"])
        if result.get("dungeon_complete") or result.get("dungeon_failed") or kind == "abort":
            break

    _print("5) THỢ RÈN — cost tăng cấp · ép may · bảo hộ %")
    _grant(pid, "enhance_stone_a", 20)
    _grant(pid, "xuong_lang", 20)
    _grant(pid, "scroll_keep_25", 1)
    _grant(pid, "scroll_keep_50", 1)
    _grant(pid, "scroll_keep_60", 1)
    _grant(pid, "charm_luck_s", 3)
    _grant(pid, "charm_luck_m", 2)
    _grant(pid, "charm_luck_l", 1)
    print(f"Túi: đá A×{_bag_qty(pid,'enhance_stone_a')} · xương×{_bag_qty(pid,'xuong_lang')}")
    print(render.render_enhance_quote(game.enhance_quote(pid, "weapon")))

    spent_gold = 0
    attempts = []
    for i in range(10):
        c = game.get_character(pid)
        if _bag_qty(pid, "enhance_stone_a") < 1 or _bag_qty(pid, "xuong_lang") < 1:
            print("Hết nguyên liệu — dừng.")
            break
        cur = bs.enhance_level(c["weapon"])
        quote = bs.cost_for(c["weapon"])
        if _bag_qty(pid, "enhance_stone_a") < quote["stones"][0]["qty"]:
            print("Không đủ đá cho cấp hiện tại — dừng.")
            break
        # protect: use 50% when +5+, else 25% when +3+
        prot = None
        want_prot = "scroll_keep_50" if cur >= 5 else ("scroll_keep_25" if cur >= 3 else None)
        if want_prot:
            prot = next((i for i, it in enumerate(c["bag"], 1) if it.get("id") == want_prot), None)
        # luck: stack charms up to ~36% when rate < 50%
        luck_idx = []
        if quote["rate"] < 0.5:
            need_luck = 0.36
            for bi, it in enumerate(c["bag"], 1):
                if it.get("subtype") != "enhance_luck":
                    continue
                luck_idx.append(bi)
                need_luck -= float(it.get("luck_bonus") or 0)
                if need_luck <= 0:
                    break
        before_cost = quote["gold"]
        r = game.enhance_item(
            pid, "weapon", balance=gold,
            protect_bag_index_1based=prot,
            luck_bag_indices_1based=luck_idx or None,
            rng=random.Random(200 + i * 17),
        )
        if not r.get("ok"):
            print(f"  lần {i+1}: FAIL start — {r.get('message')}")
            break
        gold -= r["gold_cost"]
        spent_gold += r["gold_cost"]
        attempts.append(r)
        icon = "✅" if r["success"] else "💥"
        print(f"  {icon} lần {i+1}: +{r['level_before']}→+{r['level_after']} "
              f"(base {r.get('rate_base', r['rate'])*100:.0f}% +luck {r.get('luck_bonus',0)*100:.0f}% "
              f"= {r['rate']*100:.0f}%, cost {before_cost} vàng)"
              + (f" · {r['protect_used']}" if r.get("protect_used") else "")
              + (f" · may:{','.join(r.get('luck_used') or [])}" if r.get("luck_used") else ""))

    c = game.get_character(pid)
    w = c["weapon"]
    print(f"\nKết quả vũ khí: {bs.display_name(w)}")
    print(f"  HP {w['HP']} · ATK {w['ATK']} · DEF {w['DEF']} · SPD {w['SPD']}")
    print(f"  Vàng còn ~{gold:,} (đã đập −{spent_gold})")

    _print("6) TRẠNG THÁI CUỐI")
    print(render.render_character(game.character_summary(pid)))
    print()
    print(render.render_bag(game.get_character(pid)))

    _print("7) ĐÁNH GIÁ NHANH")
    rates = bs.get_config()["success_rate"]
    costs = [bs.cost_for({**w, "enhance_level": lv})["gold"] for lv in range(0, 6)]
    cost_rising = all(costs[i] < costs[i + 1] for i in range(len(costs) - 1))
    print(f"· Cost tăng theo cấp +: {'OK' if cost_rising else 'BUG'} ({costs})")
    print(f"· Rate gốc giảm theo +N: +1={float(rates['1'])*100:.0f}% … +10={float(rates['10'])*100:.0f}%")
    print(f"· Luck cap: +{bs.MAX_LUCK_BONUS*100:.0f}% · bảo hộ: 25%/50%/60% cấp gốc")
    print(f"· Số lần đập demo: {len(attempts)} · thành công {sum(1 for a in attempts if a['success'])}")
    print(f"· Peak + đạt trong phiên: +{max((a['level_after'] for a in attempts), default=0)}")
    print(f"· Hunter Lv.{c['level']} · karma {c['karma']} · túi {len(c['bag'])} ô")


if __name__ == "__main__":
    main()
