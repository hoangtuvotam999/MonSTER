"""
Battle renderer — turns the outcome dicts produced by `game.encounter_and_fight`
and `game.start_match` into lively, platform-neutral chat text (plain text +
emoji, no markdown), ready to send on Discord / Messenger / Telegram.

Typical usage:

    outcome = game.encounter_and_fight(uid)
    text = render.render_hunt(outcome)          # handles both ok and !ok
    for chunk in render.split_message(text, 1900):
        send(chunk)

Rendering is deterministic given the same outcome and `rng`; pass your own
`random.Random(seed)` if you need reproducible flavour text (e.g. in tests).
"""
from __future__ import annotations

import random
from typing import Optional

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
