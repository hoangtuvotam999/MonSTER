"""Turn game results into embed payloads. No Discord imports."""
from __future__ import annotations

from .context import Reply, field, separator
from monster_game import render

WIN = 4321431
LOSE = 10038562
NEUTRAL = 5793266
RULE = "━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def row(label: str, value=None) -> str:
    """One aligned line. Empty values stay italic. Numbers use `measure`."""
    if value is None or str(value).strip() in ("", "không"):
        shown = "*không*"
    else:
        shown = f"**{value}**"
    return f"**{label}** » {shown}"


def measure(label: str, value) -> str:
    """A counted value, wrapped so the digits line up."""
    if value is None or str(value).strip() == "":
        return row(label, None)
    return f"**{label}** » `{value}`"


def blocks(*parts: str) -> str:
    """Up to four blocks, split by the one rule used on every card."""
    chunks = [part.strip() for part in parts if part and str(part).strip()]
    return f"\n\n{RULE}\n".join(chunks)


def _clip(text: str, limit: int = 1000) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text or "…"
    return text[: limit - 1] + "…"


def plain(text: str, *, color: int = NEUTRAL, author: str = "") -> Reply:
    body = text or "(trống)"
    return Reply(
        text=body,
        view={"color": color, "header": _clip(body, 4000), "fields": [], "author": author},
        story=[],
    )


def coerce(value) -> Reply:
    if isinstance(value, Reply):
        if value.view is None:
            return plain(value.text)
        return value
    return plain(str(value or "(trống)"))


def _items(outcome: dict) -> str:
    bits = []
    for it in outcome.get("belt") or []:
        if it:
            bits.append(f"`{it.get('name', '?')}` x{int(it.get('qty', 1))}")
    for it in outcome.get("pocket") or []:
        bits.append(f"`{it.get('name', '?')}` x{int(it.get('qty', 1))}")
    return ", ".join(bits) if bits else "`(không còn bình thuốc)`"


_BOSS_LINES = {
    "Tobi-Kadachi": ["Tobi-Kadachi trườn xuống thân cây, lông dựng lên vì điện.", "Nó không phải lũ nhỏ các người vẫn săn."],
    "Rathian": ["Rathian xòe cánh. Đuôi độc quét một vòng trước khi lao xuống.", "Mini-boss này không bỏ cuộc giữa chừng."],
    "Odogaron": ["Odogaron chạy bằng bốn chân, miệng đầy máu khô.", "Nó đã đánh hơi thấy các người từ rất xa."],
    "Legiana": ["Legiana gấp cánh, gió lạnh đọng thành sương.", "Bầu trời trên đầu không còn là chỗ trú."],
    "Azure Rathalos": ["Azure Rathalos gầm một tiếng. Lửa xanh liếm mép hàm.", "Đây là bản hung hơn của vua trời."],
    "Anjanath": ["Anjanath ngẩng đầu. Lửa chảy ra từ hàm.", "Đất rung. Đây là boss của khu rừng."],
    "Diablos": ["Diablos phá cát chui lên, sừng nhằm thẳng vào các người.", "Nó không nhìn. Nó húc."],
    "Kirin": ["Kirin đứng trong sấm. Mỗi bước một tia đánh xuống.", "Boss này không cho các người lại gần."],
    "Teostra": ["Teostra thở ra. Không khí quanh nó bắt lửa.", "Sư tử già đã thức."],
    "Rathalos": ["Rathalos đáp xuống, cánh che cả vạt rừng.", "Vua trời. Nó nhìn các người như con mồi."],
    "Black Diablos": ["Black Diablos gầm trong cát bụi. Sừng đen nhằm vào ngực.", "Con cái này còn hung hơn cả con đực."],
    "Vaal Hazak": ["Vaal Hazak bước ra từ màn sương. Hơi thở làm phổi nặng.", "Elder. Đừng hít sâu."],
    "Nergigante": ["Nergigante xòe gai. Nó đến để ăn những con còn lại.", "Elder này không nói. Nó bổ xuống."],
}


def boss_lines(name: str, tier: str) -> list[str]:
    """Extra spoken lines when a miniboss or boss shows up. Normal monsters stay quiet."""
    if tier not in ("V", "X", "XX"):
        return []
    lines = list(_BOSS_LINES.get(name) or [])
    if tier == "V" and not lines:
        lines = [f"⚠️ Mini-boss {name} chắn lối.", "Nó không chạy khi thấy đông người."]
    elif tier == "X" and not lines:
        lines = [f"☠️ Boss {name} bước ra.", "Một tiếng gầm. Những con nhỏ quanh đó im hết."]
    elif tier == "XX" and not lines:
        lines = [f"☠️ Elder {name}.", "Không khí đặc lại trước đòn đầu tiên."]
    return lines


def _action_row(label: str, detail: str) -> dict:
    row = field(label, detail, inline=True)
    row["action"] = label
    return row


def event_bits(adventure: dict) -> tuple[list[dict], dict]:
    """One row per choice. The button sits on that row, not under the hunt log."""
    actions = list((adventure or {}).get("actions") or [])[:5]
    fields = [
        separator(
            "Chọn một hướng",
            "Nút nằm bên phải mỗi hàng. Tin trận săn phía trên giữ nguyên. Nút tắt sau 8 phút.",
        ),
    ]
    buttons = []
    for action in actions:
        label = (action.get("label") or action.get("id") or "chọn")[:80]
        detail = (action.get("hint") or action.get("text") or "Đi theo hướng này.").strip()
        fields.append(_action_row(label, detail))
        buttons.append({
            "id": f"mx:pick:{action.get('id')}",
            "label": label,
            "style": "primary",
            "band": "chon",
            "hint": detail[:180],
        })
    return fields, {"buttons": buttons}


def event_reply(adventure: dict) -> Reply:
    fields, controls = event_bits(adventure)
    controls["buttons"].append({
        "id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan",
    })
    text = render.render_adventure_prompt(adventure)
    intro = adventure.get("intro") or "Chọn một hướng bên dưới."
    action_lines = [intro, ""]
    for action in (adventure.get("actions") or [])[:5]:
        label = action.get("label") or action.get("id") or "chọn"
        detail = (action.get("hint") or action.get("text") or "").strip()
        action_lines.append(f"**{label}**" + (f" — {detail}" if detail else ""))
    return Reply(
        text=text,
        view={
            "color": NEUTRAL,
            "title": adventure.get("title") or "Sự kiện",
            "header": "\n".join(action_lines)[:1500],
            "fields": fields,
            "author": adventure.get("location_name") or "",
            "menu": True,
        },
        story=[],
        controls=controls,
    )


def choice_reply(result: dict, text: str) -> Reply:
    """Result of a hunt choice. Sent as its own message so the fight log stays."""
    if not result.get("ok"):
        return plain(text, color=LOSE)
    lines = [ln for ln in (result.get("lines") or []) if ln]
    body = "\n".join(lines) if lines else (result.get("log") or text or "…")
    drops = []
    for item in result.get("drops") or []:
        drops.append(f"{item.get('name', 'vật phẩm')} ×{int(item.get('qty') or 1)}")
    effects = result.get("effects") or {}
    detail = []
    if effects.get("the_luc"):
        delta = int(effects["the_luc"])
        detail.append(f"Thể lực {'+' if delta > 0 else ''}{delta}")
    if effects.get("karma"):
        delta = int(effects["karma"])
        detail.append(f"Karma {'+' if delta > 0 else ''}{delta}")
    gold_delta = int(result.get("gold_delta") or 0)
    if gold_delta:
        detail.append(f"Vàng {'+' if gold_delta > 0 else ''}{gold_delta}")
    if drops:
        detail.append("Nhận: " + ", ".join(drops))
    fields = [
        separator("Đã chọn", "Nhật ký trận vẫn là tin nhắn phía trên. Tin này chỉ là kết quả hướng bạn chọn."),
        field(result.get("action_label") or "Hướng đã chọn", result.get("log") or body, inline=False),
    ]
    if detail:
        fields.append(field("Thay đổi", "\n".join(detail), inline=False))
    buttons = [
        {"id": "mx:nav:hunt", "label": "Săn tiếp", "style": "danger", "band": "tiep", "hint": "Đánh một trận mới"},
        {"id": "mx:nav:bag", "label": "Túi", "style": "secondary", "band": "chan"},
        {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
    ]
    fields.extend([
        separator("Tiếp tục", "Nút bên phải mỗi hàng. Nút tắt sau 8 phút."),
        _action_row("Săn tiếp", "Đánh một trận mới. Tin trận cũ vẫn nằm phía trên."),
        _action_row("Nhân vật", "Mở bảng chỉ số: máu, đòn, đỡ, tốc, thể lực, vàng."),
        _action_row("Túi", "Xem đồ vừa nhặt và trang bị."),
    ])
    return Reply(
        text=text,
        view={
            "color": NEUTRAL,
            "title": result.get("title") or "Sự kiện",
            "header": body[:1500],
            "fields": fields,
            "author": result.get("location_name") or "",
            "menu": True,
        },
        story=[],
        controls={"buttons": buttons},
    )


def hunt_reply(outcome: dict, text: str) -> Reply:
    if not outcome.get("ok"):
        return plain(text, color=LOSE)
    loc = outcome.get("location_name") or "Wilds"
    icon = render.LOCATION_ICONS.get(loc, "🗺️")
    tier = outcome.get("monster_tier") or "?"
    tier_icon = render.TIER_ICONS.get(tier, "❔")
    pname = outcome.get("player_name") or "Hunter"
    mname = outcome.get("monster_name") or "Monster"
    pstats = outcome.get("player_stats") or {}
    mstats = outcome.get("monster_stats") or {}
    header = "\n".join([
        f"{icon} {loc.upper()}" + ("  ⚡VƯỢT CẤP" if outcome.get("overlevel") else ""),
        f"{tier_icon} Xuất hiện: {mname} · Tier {tier} · Lv.{outcome.get('monster_level')} · {outcome.get('monster_threat', '')}",
        f"⚔️ {pname} ({outcome.get('weapon_name', 'tay không')}) đối đầu !",
        "",
        f"> {render.PLAYER_ICON} {pname}",
        f"`{render.hp_bar(pstats.get('HP', 1), pstats.get('maxHP', pstats.get('HP', 1)), 10)} {render.fmt(pstats.get('HP', 0))}/{render.fmt(pstats.get('maxHP', pstats.get('HP', 1)))}`",
        f"> {render.MONSTER_ICON} {mname}",
        f"`{render.hp_bar(mstats.get('HP', 1), mstats.get('maxHP', mstats.get('HP', 1)), 10)} {render.fmt(mstats.get('HP', 0))}/{render.fmt(mstats.get('maxHP', mstats.get('HP', 1)))}`",
    ])
    if outcome.get("draw"):
        title = f"☠️ HÒA sau {outcome.get('turns', 0)} đòn."
        color = NEUTRAL
    elif outcome.get("won"):
        title = f"🏆 CHIẾN THẮNG sau {outcome.get('turns', 0)} đòn! {mname} đã gục ngã."
        color = WIN
    else:
        title = f"💀 THẤT BẠI sau {outcome.get('turns', 0)} đòn."
        color = LOSE
    loot_bits = []
    for drop in outcome.get("drops") or []:
        loot_bits.append(f"`{drop.get('name', '?')} x{drop.get('qty', 1)}`")
    if outcome.get("won") or outcome.get("draw"):
        loot_bits.append(f"🎒 xác quái vật: {mname}")
    loot = "\n".join(loot_bits) if loot_bits else "Không có chiến lợi phẩm."
    exp_bar = render.hp_bar(outcome.get("player_exp", 0), outcome.get("player_exp_needed") or 1, 8)
    level_value = (
        f"✨ +{render.fmt(outcome.get('exp_gained', 0))} EXP •⚡ Thể lực: {render.fmt(outcome.get('player_the_luc', 0))}\n"
        f"Bạn còn các item sau:\n{_items(outcome)}"
    )
    if outcome.get("weapon_broken"):
        weapon_value = f"🔧 {outcome.get('weapon_name')} đã hỏng. Sửa tốn {render.fmt(outcome.get('repair_cost', 0))} vàng."
    else:
        weapon_value = f"🔧 Độ bền: {outcome.get('weapon_durability', 0)}/100"
    journey_lines = []
    for beat in (outcome.get("journey") or {}).get("beats") or []:
        journey_lines.extend(beat.get("lines") or [])
    adv = outcome.get("adventure")
    if adv:
        journey_lines.append(render.render_adventure_prompt(adv))
    result_body = "\n".join([
        title,
        f"⚔️ Gây {render.fmt(outcome.get('player_damage_dealt', 0))} · 🛡️ Nhận {render.fmt(outcome.get('player_damage_taken', 0))}",
        f"Lv {outcome.get('player_level', 1)} [{exp_bar}] {render.fmt(outcome.get('player_exp', 0))}/{render.fmt(outcome.get('player_exp_needed') or 1)}",
        level_value,
        f"Item: {outcome.get('weapon_name', '—')}",
        weapon_value,
        RULE,
        "Loot",
        loot,
    ])
    if outcome.get("daily_note"):
        result_body += "\n" + outcome["daily_note"]
    if journey_lines:
        result_body += f"\n{RULE}\n" + "\n".join(journey_lines)
    extras = [{"title": "Kết quả", "description": _clip(result_body, 3500), "color": color}]
    if journey_lines:
        extras.append({
            "title": "Hành trình",
            "description": _clip("\n".join(journey_lines), 3500),
            "color": color,
        })
    companion = None
    actions = (adv or {}).get("actions") or []
    if actions:
        ev_fields, ev_controls = event_bits(adv)
        companion = {
            "color": NEUTRAL,
            "title": adv.get("title") or "Sự kiện",
            "header": adv.get("intro") or "Có việc xảy ra sau trận.",
            "fields": ev_fields,
            "author": adv.get("location_name") or loc,
            "controls": ev_controls,
            "menu": True,
        }
    story = boss_lines(mname, str(tier)) + render.hunt_combat_lines(outcome)
    return Reply(
        text=text,
        view={
            "color": color,
            "title": f"{mname} · Tier {tier}",
            "header": header,
            "fields": [],
            "extras": extras,
            "author": pname,
            "companion": companion,
        },
        story=story,
        controls=None,
    )


def party_reply(result: dict, text: str) -> Reply:
    if not result.get("ok"):
        return plain(text, color=LOSE)
    loc = result.get("location_name") or ""
    icon = render.LOCATION_ICONS.get(loc, "🗺️")
    names = ", ".join(seg["player_name"] for seg in result.get("segments") or [])
    header = "\n".join([
        f"{icon} {loc.upper()} · 👥 {result.get('party_title', 'Tổ đội')}",
        f"🟢 {result.get('monster_name')} · Tier {result.get('monster_tier')} · Lv.{result.get('monster_level')}",
        f"⚔️ {names or 'Tổ đội'} đối đầu !",
    ])
    color = WIN if result.get("won") else LOSE
    title = "🏆 Tổ đội hạ gục mục tiêu." if result.get("won") else f"💀 Quái còn {render.fmt(result.get('monster_hp_left', 0))} HP."
    reward_lines = []
    for rw in result.get("rewards") or []:
        reward_lines.append(f"{rw['player_name']}: +{render.fmt(rw['exp'])} EXP")
        for drop in rw.get("drops") or []:
            reward_lines.append(f"`{drop.get('name')} x{drop.get('qty', 1)}`")
    journey_lines = []
    for beat in (result.get("journey") or {}).get("beats") or []:
        journey_lines.extend(beat.get("lines") or [])
    result_body = title + "\n" + ("\n".join(reward_lines) or "Không có thưởng.")
    if journey_lines:
        result_body += f"\n{RULE}\n" + "\n".join(journey_lines)
    extras = [{
        "title": "Kết quả",
        "description": _clip(result_body, 3500),
        "color": color,
    }]
    if journey_lines:
        extras.append({
            "title": "Hành trình",
            "description": _clip("\n".join(journey_lines), 3500),
            "color": color,
        })
    story = boss_lines(result.get("monster_name") or "", str(result.get("monster_tier") or ""))
    story += render.party_combat_lines(result)
    return Reply(
        text=text,
        view={
            "color": color,
            "title": f"{result.get('monster_name', 'Quái')} · tổ đội",
            "header": header,
            "fields": [],
            "extras": extras,
            "author": result.get("party_title") or "Party",
        },
        story=story,
    )


def lines_reply(text: str, lines: list[str], *, title: str, color: int = NEUTRAL, author: str = "") -> Reply:
    fields = []
    if lines:
        fields.append({"name": title, "value": "```ini\n" + _clip("\n".join(lines), 900) + "\n```", "inline": False})
    return Reply(
        text=text,
        view={"color": color, "header": _clip(text, 500), "fields": fields, "author": author},
        story=[ln for ln in lines if ln.strip()],
    )
