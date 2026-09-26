"""
Battle renderer — turns the outcome dicts produced by `game.encounter_and_fight`
and `game.start_match` into lively, platform-neutral chat text (plain text +
emoji, no markdown), ready to send on Discord / Messenger / Telegram.

Typical usage:

    outcome = game.encounter_and_fight(uid)
    text = render.render_hunt(outcome)          # handles both ok and !ok
    for chunk in render.split_message(text, 1900):
        send(chunk)

    send(render.render_character(game.character_summary(uid)))
    send(render.render_bag(game.get_character(uid)))
    send(render.render_shop_menu())
    send(render.render_weapon_list("Great Sword", game.get_character(uid)))
    send(render.render_locations(game.list_locations(), game.get_character(uid)))

Rendering is deterministic given the same outcome and `rng`; pass your own
`random.Random(seed)` if you need reproducible flavour text (e.g. in tests).
"""
from __future__ import annotations

import random
from typing import Callable, Optional

from . import data_store, shop

BAR_FULL = "█"
BAR_EMPTY = "░"

PLAYER_ICON = "🧑‍🚀"
MONSTER_ICON = "👾"
TIER_ICONS = {"I": "🟢", "II": "🟢", "III": "🟡", "IV": "🟠", "V": "🟠", "X": "🔴", "XX": "☠️"}
LOCATION_ICONS = {
    "Ancient Forest": "🌲",
    "Wildspire Waste": "🏜️",
    "Coral Highlands": "🪸",
    "Elder's Recess": "🌋",
}

WEAPON_VERBS = {
    "Great Sword": ["vung đại kiếm bổ xuống", "xoay người chém ngang", "tích lực giáng một nhát"],
    "Lance": ["đâm thương thẳng vào", "lao tới xọc thương", "chống khiên rồi đâm mạnh"],
    "Sword": ["chém một đường", "chém liên tiếp", "đỡ khiên rồi phản công"],
    "Dual Blades": ["xoay song đao như bão", "lướt qua chém chéo", "múa đao cắt xé"],
    "Heavy Bowgun": ["nã một loạt đạn", "bắn đạn xuyên giáp", "khai hỏa"],
    "Light Bowgun": ["bắn liên thanh", "lăn tránh rồi bắn trả", "bắn tỉa"],
}
DEFAULT_WEAPON_VERBS = ["tấn công", "ra đòn", "đánh tới"]
MONSTER_VERBS = ["cắn", "quật đuôi", "húc thẳng", "cào", "lao tới đè", "gầm lên rồi tấn công"]

# (hp fraction the defender just dropped below, message template)
HURT_LINES = [
    (0.5, "💢 {name} bắt đầu khập khiễng!"),
    (0.25, "🩸 {name} gần kiệt sức, mắt đã đỏ ngầu!"),
]
PLAYER_HURT_LINES = [
    (0.5, "😰 {name} loạng choạng, máu đã mất quá nửa!"),
    (0.25, "🚨 {name} thở dốc — chỉ còn chút hơi tàn!"),
]

FAILURE_MESSAGES = {
    "no_character": "❌ Bạn chưa có nhân vật. Hãy tạo nhân vật trước khi đi săn.",
    "no_location": "🗺️ Bạn chưa chọn khu vực săn. Hãy chọn một địa điểm trước.",
    "invalid_location": "🗺️ Khu vực hiện tại không tồn tại. Hãy chọn lại địa điểm.",
    "no_weapon": "🗡️ Bạn chưa trang bị vũ khí. Mở túi và trang bị một món trước.",
    "weapon_broken": "🔧 Vũ khí của bạn đã hỏng! Hãy sửa nó trước khi đi săn.",
    "level_too_low": "⛔ Khu vực này yêu cầu cấp {required_level}. Hãy săn ở nơi thấp hơn để lên cấp.",
    "no_stamina": "😮‍💨 Bạn đã kiệt sức (cần 50 thể lực). Ăn gì đó rồi quay lại nhé.",
    "bag_full": "🎒 Túi chiến lợi phẩm đã đầy. Hãy bán bớt quái trước khi săn tiếp.",
    "no_encounter": "🍃 Bạn lùng sục khắp nơi nhưng chẳng thấy bóng con quái nào... Thử lại lần nữa!",
}


# --------------------------------------------------------------------------
# Small formatting helpers
# --------------------------------------------------------------------------

def fmt(n: float) -> str:
    """1234567 -> '1.234.567' (Vietnamese thousands separator)."""
    return f"{int(round(n)):,}".replace(",", ".")


def hp_bar(current: float, maximum: float, width: int = 10) -> str:
    current = max(0.0, current)
    ratio = current / maximum if maximum > 0 else 0
    filled = round(ratio * width)
    if current > 0 and filled == 0:
        filled = 1
    filled = min(width, filled)
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def _hp_line(icon: str, name: str, current: float, maximum: float, pad: int) -> str:
    current = max(0.0, current)
    return f"{icon} {name.ljust(pad)} {hp_bar(current, maximum)} {fmt(current)}/{fmt(maximum)}"


def split_message(text: str, limit: int = 1900) -> list[str]:
    """Split on line boundaries so no chunk exceeds `limit` characters
    (Discord: 2000, Telegram: 4096, Messenger: ~2000)."""
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # pathological single long line
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit and current:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


# --------------------------------------------------------------------------
# Core battle narration (shared by PvE and PvP)
# --------------------------------------------------------------------------

class _Side:
    def __init__(self, label: str, name: str, icon: str, stats: dict, verbs: list[str],
                 hurt_lines: list[tuple[float, str]]):
        self.label = label
        self.name = name
        self.icon = icon
        self.max_hp = max(stats["HP"], 1)
        self.spd = stats["SPD"]
        self.verbs = verbs
        self.hurt_lines = hurt_lines
        self.hurt_shown: set[float] = set()


def _group_rounds(log: list[dict]) -> list[list[dict]]:
    """Consecutive attacks by the same side form one 'round'."""
    rounds: list[list[dict]] = []
    for entry in log:
        if rounds and rounds[-1][0]["attacker"] == entry["attacker"]:
            rounds[-1].append(entry)
        else:
            rounds.append([entry])
    return rounds


def _hit_text(entry: dict) -> str:
    if entry.get("skill") == "skill":
        return f"🔥 TUYỆT KỸ −{fmt(entry['damage'])}"
    return f"−{fmt(entry['damage'])}"


def _render_round(rnd: list[dict], attacker: _Side, defender: _Side, rng: random.Random) -> list[str]:
    total = sum(e["damage"] for e in rnd)
    hits = ", ".join(_hit_text(e) for e in rnd)
    verb = rng.choice(attacker.verbs)
    if len(rnd) == 1:
        head = f"▶ {attacker.name} {verb}: {hits}"
    else:
        head = f"▶ {attacker.name} {verb} ×{len(rnd)}: {hits}  (tổng −{fmt(total)})"
    lines = [head]

    defender_hp = rnd[-1][defender.label]["HP"]
    lines.append("   " + _hp_line(defender.icon, defender.name, defender_hp, defender.max_hp, 0))

    frac = defender_hp / defender.max_hp
    for threshold, template in defender.hurt_lines:
        if frac < threshold and threshold not in defender.hurt_shown and defender_hp > 0:
            defender.hurt_shown.add(threshold)
            lines.append("   " + template.format(name=defender.name))
            break
    return lines


def _render_battle(log: list[dict], a: _Side, b: _Side, max_rounds: int, rng: random.Random) -> list[str]:
    sides = {a.label: a, b.label: b}
    rounds = _group_rounds(log)
    lines: list[str] = []

    # Opening: who strikes first and why.
    first = sides[log[0]["attacker"]] if log else a
    second = b if first is a else a
    if first.spd >= second.spd * 2:
        per_round = int(first.spd // max(second.spd, 1))
        lines.append(f"⚡ {first.name} nhanh hơn hẳn ({fmt(first.spd)} vs {fmt(second.spd)}) "
                     f"— ra tay trước và được {per_round} đòn mỗi lượt!")
    elif first.spd > second.spd:
        lines.append(f"⚡ {first.name} nhanh hơn ({fmt(first.spd)} vs {fmt(second.spd)}) và ra tay trước.")
    else:
        lines.append(f"⚡ Hai bên ngang tốc độ — {first.name} chớp thời cơ ra tay trước.")
    lines.append("")

    if len(rounds) <= max_rounds:
        shown = [(i, r) for i, r in enumerate(rounds)]
        skipped: Optional[tuple[int, int]] = None
    else:
        head = max_rounds // 2
        tail = max_rounds - head
        shown = [(i, r) for i, r in enumerate(rounds[:head])]
        skipped = (head, len(rounds) - tail)
        shown += [(i, r) for i, r in enumerate(rounds[skipped[1]:], start=skipped[1])]

    for i, rnd in shown:
        if skipped and i == skipped[1]:
            skipped_rounds = rounds[skipped[0]:skipped[1]]
            dmg = {a.label: 0, b.label: 0}
            for r in skipped_rounds:
                dmg[r[0]["attacker"]] += sum(e["damage"] for e in r)
            lines.append(f"⋯ {len(skipped_rounds)} lượt giao tranh ác liệt "
                         f"({a.name} gây −{fmt(dmg[a.label])}, {b.name} gây −{fmt(dmg[b.label])}) ⋯")
            lines.append("")
            # Hurt lines for thresholds crossed inside the skipped part
            # would be confusing out of order, so mark them as shown.
            last = skipped_rounds[-1][-1]
            for side in (a, b):
                frac = last[side.label]["HP"] / side.max_hp
                for threshold, _ in side.hurt_lines:
                    if frac < threshold:
                        side.hurt_shown.add(threshold)
        attacker = sides[rnd[0]["attacker"]]
        defender = b if attacker is a else a
        lines.extend(_render_round(rnd, attacker, defender, rng))
    return lines


# --------------------------------------------------------------------------
# PvE
# --------------------------------------------------------------------------

def render_failure(outcome: dict) -> str:
    template = FAILURE_MESSAGES.get(outcome.get("reason"), "❌ Không thể đi săn lúc này.")
    return template.format(**{k: v for k, v in outcome.items() if k != "reason"})


def render_hunt(outcome: dict, max_rounds: int = 12, rng: Optional[random.Random] = None) -> str:
    """Full narration of an `encounter_and_fight` outcome. Falls back to a
    one-line failure message when `outcome['ok']` is False."""
    if not outcome.get("ok"):
        return render_failure(outcome)
    rng = rng or random.Random()

    player = _Side("player", outcome["player_name"], PLAYER_ICON, outcome["player_stats"],
                   WEAPON_VERBS.get(outcome.get("weapon_category"), DEFAULT_WEAPON_VERBS),
                   PLAYER_HURT_LINES)
    monster = _Side("monster", outcome["monster_name"], MONSTER_ICON, outcome["monster_stats"],
                    MONSTER_VERBS, HURT_LINES)
    pad = max(len(player.name), len(monster.name))

    tier = outcome["monster_tier"]
    lines = []
    loc = outcome.get("location_name") or ""
    if loc:
        lines.append(f"{LOCATION_ICONS.get(loc, '🗺️')} {loc.upper()}")
    lines.append(f"{TIER_ICONS.get(tier, '❔')} Xuất hiện: {monster.name} · Tier {tier} · "
                 f"Lv.{outcome['monster_level']} · {outcome['monster_threat']}")
    lines.append(f"⚔️ {player.name} ({outcome['weapon_name']}) đối đầu {monster.name}!")
    lines.append("")
    lines.append(_hp_line(player.icon, player.name, player.max_hp, player.max_hp, pad))
    lines.append(_hp_line(monster.icon, monster.name, monster.max_hp, monster.max_hp, pad))
    lines.append("")

    lines.extend(_render_battle(outcome["log"], player, monster, max_rounds, rng))
    lines.append("")

    turns = outcome["turns"]
    if outcome["won"]:
        lines.append(f"🏆 CHIẾN THẮNG sau {turns} đòn! {monster.name} đã gục ngã.")
    else:
        last = outcome["log"][-1]["monster"]["HP"] if outcome["log"] else monster.max_hp
        lines.append(f"💀 THẤT BẠI sau {turns} đòn... {monster.name} vẫn còn {fmt(last)} HP.")
    lines.append(f"⚔️ Gây {fmt(outcome['player_damage_dealt'])} · 🛡️ Nhận {fmt(outcome['player_damage_taken'])}")

    if outcome["won"]:
        exp_bar = hp_bar(outcome["player_exp"], outcome["player_exp_needed"], 8)
        lines.append(f"✨ +{fmt(outcome['exp_gained'])} EXP → Lv.{outcome['player_level']} "
                     f"[{exp_bar}] {fmt(outcome['player_exp'])}/{fmt(outcome['player_exp_needed'])}")
        for kind, value in outcome.get("events", []):
            if kind == "level_up":
                lines.append(f"🎉 LÊN CẤP {value}! (+{fmt(500 * value)} điểm kỹ năng)")
            elif kind == "weapon_level_up":
                lines.append(f"🗡️ {outcome['weapon_name']} lên cấp {value}!")
        lines.append(f"🎒 Chiến lợi phẩm: {monster.name} (bán được {fmt(outcome['monster_price'])} vàng)")

    if outcome["weapon_broken"]:
        lines.append(f"🔧 {outcome['weapon_name']} đã HỎNG! Sửa tốn {fmt(outcome['repair_cost'])} vàng.")
    else:
        lines.append(f"🔧 Độ bền: {outcome['weapon_durability']}/100 · ⚡ Thể lực: {outcome['player_the_luc']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# PvP
# --------------------------------------------------------------------------

def render_pvp(result: dict, max_rounds: int = 12, rng: Optional[random.Random] = None) -> str:
    """Full narration of a `start_match` result."""
    rng = rng or random.Random()
    p1 = _Side("player1", result["player1_name"], "🔵", result["player1_stats"],
               WEAPON_VERBS.get(result.get("player1_weapon_category"), DEFAULT_WEAPON_VERBS),
               PLAYER_HURT_LINES)
    p2 = _Side("player2", result["player2_name"], "🔴", result["player2_stats"],
               WEAPON_VERBS.get(result.get("player2_weapon_category"), DEFAULT_WEAPON_VERBS),
               PLAYER_HURT_LINES)
    pad = max(len(p1.name), len(p2.name))

    lines = [f"🏟️ ĐẤU TRƯỜNG — {result.get('room_title', 'PvP')}",
             f"🔵 {p1.name} ({result['player1_weapon']})  vs  🔴 {p2.name} ({result['player2_weapon']})",
             "",
             _hp_line(p1.icon, p1.name, p1.max_hp, p1.max_hp, pad),
             _hp_line(p2.icon, p2.name, p2.max_hp, p2.max_hp, pad),
             ""]
    lines.extend(_render_battle(result["log"], p1, p2, max_rounds, rng))
    lines.append("")

    winner = p1 if result["winner_id"] == result["player1_id"] else p2
    loser = p2 if winner is p1 else p1
    lines.append(f"🏆 {winner.name} CHIẾN THẮNG sau {result['rounds']} đòn! {loser.name} đã bị hạ.")
    lines.append(f"⚔️ Sát thương: {p1.name} {fmt(result['player1_damage'])} · "
                 f"{p2.name} {fmt(result['player2_damage'])}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Character status / bag / trophies
# --------------------------------------------------------------------------

ITEM_ICONS = {"weapon": "🗡️", "food": "🍖", "upgrade": "💎", "buff": "✨"}
CATEGORY_ICONS = {
    "Great Sword": "🗡️", "Lance": "🔱", "Sword": "⚔️",
    "Dual Blades": "🔪", "Heavy Bowgun": "💣", "Light Bowgun": "🔫",
}
STAMINA_MAX = 500  # a fresh character's the_luc; used only for the bar


def _stat_with_bonus(base: float, bonus: Optional[float]) -> str:
    if bonus:
        return f"{fmt(base)} (+{fmt(bonus)})"
    return fmt(base)


def render_character(summary: Optional[dict]) -> str:
    """Status card for `game.character_summary(uid)`."""
    if summary is None:
        return FAILURE_MESSAGES["no_character"]
    s = summary
    wb = s.get("weapon_bonus") or {}
    lines = [
        f"🧑‍🚀 {s['name']} — Lv.{s['level']}",
        f"✨ EXP [{hp_bar(s['exp'], s['exp_needed'], 10)}] {fmt(s['exp'])}/{fmt(s['exp_needed'])}",
        f"⚡ Thể lực [{hp_bar(s['the_luc'], max(STAMINA_MAX, s['the_luc']), 10)}] {fmt(s['the_luc'])}",
        "",
        f"❤️ HP  {_stat_with_bonus(s['hp'], wb.get('hp'))}",
        f"⚔️ ATK {_stat_with_bonus(s['atk'], wb.get('atk'))}",
        f"🛡️ DEF {_stat_with_bonus(s['def'], wb.get('def'))}",
        f"💨 SPD {_stat_with_bonus(s['spd'], wb.get('spd'))}",
        f"💪 Lực chiến: {fmt(s['power_total'] or s['power_basic'])}"
        + (f" (bản thân {fmt(s['power_basic'])})" if s["power_total"] else ""),
    ]
    if s["points"]:
        lines.append(f"🎯 Điểm kỹ năng chưa dùng: {fmt(s['points'])}")
    lines.append("")

    if s["weapon_name"]:
        icon = CATEGORY_ICONS.get(s.get("weapon_category"), "🗡️")
        lvl = f" +{s['weapon_level']}" if s.get("weapon_level") else ""
        lines.append(f"{icon} {s['weapon_name']}{lvl}")
        dur = s["weapon_durability"]
        lines.append(f"   🔧 Độ bền [{hp_bar(dur, data_store.MAX_DURABILITY, 10)}] {dur}/{data_store.MAX_DURABILITY}")
        lines.append(f"   ❤️ HP vũ khí [{hp_bar(s['weapon_hp'], s['weapon_max_hp'], 10)}] "
                     f"{fmt(s['weapon_hp'])}/{fmt(s['weapon_max_hp'])}")
        if s["repair_cost"]:
            lines.append(f"   💰 Sửa chữa: {fmt(s['repair_cost'])} vàng")
    else:
        lines.append("🗡️ Chưa trang bị vũ khí!")
    lines.append("")

    lines.append(f"🎒 Túi đồ: {s['bag_count']} món · "
                 f"{s['bag_status_icon'] or '⚪'} Chiến lợi phẩm: {s['monster_count']}/30"
                 + (f" (~{fmt(s['trophy_value'])} vàng)" if s["monster_count"] else ""))
    lines.append(f"📍 Khu vực: {s['location_name'] or 'chưa chọn'}")
    karma_line = f"😈 Karma: {s['karma']}"
    if s["karma_message"]:
        karma_line += f" — {s['karma_message']}"
    lines.append(karma_line)
    return "\n".join(lines)


def _weapon_stats_line(w: dict) -> str:
    parts = [f"HP {fmt(w['HP'])}", f"ATK {fmt(w['ATK'])}", f"DEF {fmt(w['DEF'])}", f"SPD {fmt(w['SPD'])}"]
    extras = []
    for key, label in (("dmgBonus", "ATK"), ("defBonus", "DEF"), ("hpBonus", "HP"), ("spdBonus", "SPD")):
        if w.get(key, 1) != 1:
            extras.append(f"{label} ×{w[key]:g}")
    ap = w.get("ArmorPiercing", 1)
    if ap != 1:
        extras.append(f"xuyên giáp {round((1 - ap) * 100)}%")
    text = " · ".join(parts)
    if extras:
        text += "  [" + ", ".join(extras) + "]"
    return text


def _food_effects(item: dict) -> str:
    effects = []
    if item.get("heal"):
        effects.append(f"+{fmt(item['heal'])} thể lực")
    same = {item.get(k, 0) for k in ("boostHP", "boostATK", "boostDEF", "boostSPD")}
    if len(same) == 1 and same != {0}:
        effects.append(f"+{fmt(same.pop())} mọi chỉ số")
    else:
        for key, label in (("boostHP", "HP"), ("boostATK", "ATK"), ("boostDEF", "DEF"), ("boostSPD", "SPD")):
            if item.get(key):
                effects.append(f"+{fmt(item[key])} {label}")
    if item.get("boostEXP"):
        effects.append(f"+{fmt(item['boostEXP'])} EXP")
    if item.get("boostKarma"):
        effects.append(f"{item['boostKarma']:+d} karma")
    if item.get("boostPoints"):
        effects.append(f"+{fmt(item['boostPoints'])} điểm kỹ năng")
    return ", ".join(effects) or "không có hiệu ứng"


def _upgrade_effects(item: dict) -> str:
    return (f"vũ khí +{fmt(item.get('boostHPweapon', 0))} HP · +{fmt(item.get('boostATKweapon', 0))} ATK · "
            f"+{fmt(item.get('boostDEFweapon', 0))} DEF · +{fmt(item.get('boostSPDweapon', 0))} SPD")


def describe_item(item: dict) -> str:
    """One-line description of any bag/shop item (without index or price)."""
    kind = item.get("type")
    icon = CATEGORY_ICONS.get(item.get("category"), ITEM_ICONS.get(kind, "📦"))
    name = item["name"]
    if kind == "weapon":
        lvl = f" +{item['usage']}" if item.get("usage") else ""
        return f"{icon} {name}{lvl} — {_weapon_stats_line(item)}"
    if kind == "food":
        return f"{icon} {name} — {_food_effects(item)}"
    if kind == "upgrade":
        return f"{icon} {name} — {_upgrade_effects(item)}"
    return f"{icon} {name}"


def render_bag(character: Optional[dict]) -> str:
    """Numbered bag listing (the numbers match `game.equip_or_consume`)."""
    if character is None:
        return FAILURE_MESSAGES["no_character"]
    lines = [f"🎒 TÚI ĐỒ CỦA {character['name'].upper()}"]
    w = character.get("weapon")
    if w:
        lines.append(f"Đang trang bị: {describe_item(w)}")
        lines.append(f"   🔧 {w['durability']}/{data_store.MAX_DURABILITY} · "
                     f"❤️ {fmt(w['HP'])}/{fmt(data_store.weapon_max_hp(w))}")
    else:
        lines.append("Đang trang bị: — (chưa có vũ khí)")
    lines.append("")
    if not character["bag"]:
        lines.append("Túi trống. Ghé cửa hàng để mua vũ khí, đồ ăn hoặc nguyên liệu nâng cấp.")
    else:
        for i, item in enumerate(character["bag"], start=1):
            lines.append(f"{i}. {describe_item(item)}")
        lines.append("")
        lines.append("Dùng số thứ tự để trang bị vũ khí hoặc sử dụng vật phẩm.")
    return "\n".join(lines)


def render_trophies(character: Optional[dict]) -> str:
    """Numbered trophy (hunted monster) listing (numbers match `shop.sell_monsters`)."""
    if character is None:
        return FAILURE_MESSAGES["no_character"]
    monsters = character["monster"]
    lines = [f"🏆 CHIẾN LỢI PHẨM CỦA {character['name'].upper()} ({len(monsters)}/30)"]
    if not monsters:
        lines.append("Chưa có gì. Đi săn đi!")
        return "\n".join(lines)
    for i, m in enumerate(monsters, start=1):
        tier = m.get("Tier", "?")
        lvl = f" · Lv.{m['level']}" if m.get("level") else ""
        lines.append(f"{i}. {TIER_ICONS.get(tier, '❔')} {m['Name']} · Tier {tier}{lvl} · 💰 {fmt(m.get('price', 0))}")
    lines.append("")
    lines.append(f"Tổng giá trị: {fmt(sum(m.get('price', 0) for m in monsters))} vàng")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Shop
# --------------------------------------------------------------------------

SHOP_FOOD_KEY = "7"
SHOP_UPGRADE_KEY = "8"


def render_shop_menu() -> str:
    lines = ["🏪 CỬA HÀNG THỢ SĂN", ""]
    for key, name in shop.WEAPON_CATEGORIES.items():
        lines.append(f"{key}. {CATEGORY_ICONS.get(name, '🗡️')} {name}")
    lines.append(f"{SHOP_FOOD_KEY}. 🍖 Đồ ăn & thuốc")
    lines.append(f"{SHOP_UPGRADE_KEY}. 💎 Nguyên liệu nâng cấp vũ khí")
    lines.append("")
    lines.append("Chọn một mục để xem danh sách.")
    return "\n".join(lines)


def _owned_weapon_names(character: Optional[dict]) -> set[str]:
    if not character:
        return set()
    names = {it["name"] for it in character["bag"] if it.get("type") == "weapon"}
    if character.get("weapon"):
        names.add(character["weapon"]["name"])
    return names


def render_weapon_list(category: str, character: Optional[dict] = None, balance: Optional[int] = None) -> str:
    """Weapons of one category (display name or shop key '1'..'6'),
    marking ones the player already owns and ones they can't afford."""
    name = shop.WEAPON_CATEGORIES.get(str(category), category)
    weapons = shop.weapons_by_category(name)
    lines = [f"{CATEGORY_ICONS.get(name, '🗡️')} {name.upper()}", ""]
    if not weapons:
        lines.append("Chưa có vũ khí nào trong mục này.")
        return "\n".join(lines)
    owned = _owned_weapon_names(character)
    for i, w in enumerate(weapons, start=1):
        flag = ""
        if w["name"] in owned:
            flag = " ✅ đã sở hữu"
        elif balance is not None and balance < w["price"]:
            flag = " 🔒 chưa đủ vàng"
        lines.append(f"{i}. {w['name']} — 💰 {fmt(w['price'])}{flag}")
        lines.append(f"   {_weapon_stats_line(w)}")
    return "\n".join(lines)


def render_food_list(balance: Optional[int] = None) -> str:
    lines = ["🍖 ĐỒ ĂN & THUỐC", ""]
    for i, item in enumerate(shop.FOOD_ITEMS, start=1):
        flag = " 🔒" if balance is not None and balance < item["price"] else ""
        lines.append(f"{i}. {item['name']} — 💰 {fmt(item['price'])}{flag}")
        lines.append(f"   {_food_effects(item)}")
    return "\n".join(lines)


def render_upgrade_list(balance: Optional[int] = None) -> str:
    lines = ["💎 NGUYÊN LIỆU NÂNG CẤP", ""]
    for i, item in enumerate(shop.UPGRADE_MATERIALS, start=1):
        flag = " 🔒" if balance is not None and balance < item["price"] else ""
        lines.append(f"{i}. {item['name']} — 💰 {fmt(item['price'])}{flag}")
        lines.append(f"   {_upgrade_effects(item)}")
    lines.append("")
    lines.append(f"Dùng lên vũ khí đang trang bị (tối đa cấp {shop.MAX_WEAPON_LEVEL}).")
    return "\n".join(lines)


def render_purchase(result) -> str:
    """For a `shop.PurchaseResult`."""
    if result.ok:
        return f"🛒 {result.message}! (−{fmt(result.cost)} vàng)\n{describe_item(result.item)}"
    return f"❌ {result.message}."


def render_repair(result: dict) -> str:
    """For a `game.repair_weapon` result."""
    if result["ok"]:
        w = result["weapon"]
        return (f"🔧 Đã sửa {w['name']}! (−{fmt(result['cost'])} vàng)\n"
                f"   Độ bền {w['durability']}/{data_store.MAX_DURABILITY} · HP {fmt(w['HP'])}/{fmt(w['maxHP'])}")
    messages = {
        "no_character": FAILURE_MESSAGES["no_character"],
        "no_weapon": FAILURE_MESSAGES["no_weapon"],
        "already_full": "✅ Vũ khí đang ở trạng thái hoàn hảo, không cần sửa.",
        "not_enough_money": f"💸 Không đủ vàng — sửa chữa tốn {fmt(result.get('cost', 0))} vàng.",
    }
    return messages.get(result.get("reason"), "❌ Không thể sửa vũ khí lúc này.")


def render_sale(count: int, total: int) -> str:
    if count == 0:
        return "❌ Không có chiến lợi phẩm nào được bán."
    return f"💰 Đã bán {count} chiến lợi phẩm, thu về {fmt(total)} vàng!"


# --------------------------------------------------------------------------
# Locations & PvP rooms
# --------------------------------------------------------------------------

def render_locations(locations: list[dict], character: Optional[dict] = None) -> str:
    """Numbered location list (numbers match `game.set_location`)."""
    lines = ["🗺️ BẢN ĐỒ SĂN", ""]
    level = character["level"] if character else None
    current = str(character["locationID"]) if character and character.get("locationID") is not None else None
    for i, loc in enumerate(locations, start=1):
        icon = LOCATION_ICONS.get(loc["name"], "🗺️")
        flags = []
        if current is not None and str(loc["ID"]) == current:
            flags.append("📍 đang ở đây")
        if level is not None and level < loc["level"]:
            flags.append(f"🔒 cần Lv.{loc['level']}")
        flag = f"  {' · '.join(flags)}" if flags else ""
        lines.append(f"{i}. {icon} {loc['name']} — Lv.{loc['level']}+ · quái Lv.{loc['minLevel']}–{loc['maxLevel']}{flag}")
        if loc.get("description"):
            lines.append(f"   {loc['description']}")
        bosses = [m for m in loc.get("creature", []) if m.get("Tier") in ("X", "XX")]
        if bosses:
            lines.append("   Boss: " + ", ".join(f"{TIER_ICONS[m['Tier']]} {m['Name']}" for m in bosses))
    return "\n".join(lines)


def render_rooms(rooms: list[dict], name_of: Callable[[str], str] = lambda pid: pid) -> str:
    """PvP room list for one channel. `name_of` maps a player id to a display name."""
    from .game import STATUS_LABELS  # local import: game does not import render

    lines = ["🏟️ PHÒNG PVP", ""]
    if not rooms:
        lines.append("Chưa có phòng nào. Tạo một phòng để thách đấu!")
        return "\n".join(lines)
    for room in rooms:
        players = " vs ".join(name_of(p) for p in room["players"])
        if len(room["players"]) == 1:
            players += " vs ❔"
        ready = " ✅ sẵn sàng" if room.get("ready") else ""
        lines.append(f"{room['stt']}. {room['title']} — {players}{ready}")
        lines.append(f"   {STATUS_LABELS.get(room['status'], '')}")
    return "\n".join(lines)
