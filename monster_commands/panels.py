"""Embed layouts plus select/button specs. No Discord imports."""
from __future__ import annotations

from monster_game import data_store, game, render, shop
from monster_game import equipment as eq

from .context import Reply, field, separator
from .present import blocks, measure, row

PAGE = 25


def _opt(label: str, value: str, description: str = "") -> dict:
    return {
        "label": (label or "—")[:100],
        "value": str(value)[:100],
        "description": (description or "")[:100],
    }


def _reply(text: str, header: str, *, fields=None, controls=None, author: str = "",
          color: int = 5793266, notice: str = "", title: str = "", menu: bool = False) -> Reply:
    packed = [] if menu else list(fields or [])
    shown = header
    if notice:
        if menu:
            shown = f"{header}\n\n— Kết quả —\n{notice[:800]}"
        else:
            packed.append({"name": "— Kết quả —", "value": notice[:1000], "inline": False})
    return Reply(
        text=text,
        view={
            "color": color,
            "title": title or "MonSTER",
            "header": shown[:3500],
            "fields": packed,
            "author": author,
            "menu": menu,
        },
        story=[],
        controls=controls,
    )


def use_text(result: dict | None) -> str:
    if not isinstance(result, dict) or not result.get("ok"):
        if isinstance(result, dict) and result.get("message"):
            return result["message"]
        return "Không dùng được món này."
    action = result.get("action")
    name = result.get("name") or "vật phẩm"
    if action == "consume":
        lines = [f"Đã dùng **{name}**."]
        lines.extend(result.get("notes") or [])
        left = int(result.get("left") or 0)
        if left:
            lines.append(f"Còn x{left}.")
        return "\n".join(lines)
    if action == "belt":
        kind = "Bình máu và bùa tự kích hoạt trong trận." if result.get("subtype") == "heal" else "Đã đưa lên đai, kích hoạt trong trận."
        return f"Đã gắn **{name}** x{int(result.get('qty') or 1)} vào đai.\n{kind}"
    if action == "equip_weapon":
        return f"Đã trang bị **{name}**."
    if action == "equip_gear":
        return f"Đã mặc **{name}**."
    if action == "upgrade":
        return f"Đã dùng **{name}** lên vũ khí đang cầm."
    return f"Đã dùng {name}."


def _ops(hint: str, *cards: tuple[str, str]) -> list[dict]:
    """A divider, then one row per button. The button is drawn on that row."""
    rows = [separator("Thao tác", hint)]
    for name, detail in cards:
        row = field(name, detail, inline=True)
        row["action"] = name
        rows.append(row)
    return rows


def _signed(value) -> str:
    number = int(value or 0)
    if number > 0:
        return f"+{render.fmt(number)}"
    return render.fmt(number)


def _weapon_text(summary: dict) -> str:
    if not summary.get("weapon_name"):
        return "Chưa cầm vũ khí. Mở Shop → Vũ khí, hoặc chọn vũ khí trong Túi. Không có vũ khí thì không săn được."
    bits = [summary["weapon_name"]]
    if summary.get("weapon_enhance"):
        bits.append(f"+{summary['weapon_enhance']}")
    if summary.get("weapon_level"):
        bits.append(f"Lv.{summary['weapon_level']}")
    category = shop.CATEGORY_LABELS.get(summary.get("weapon_category") or "", summary.get("weapon_category") or "vũ khí")
    durability = int(summary.get("weapon_durability") or 0)
    lines = [
        f"{' '.join(bits)} · {category}",
        f"Độ bền {durability}/100. Về 0 thì gãy, phải sửa mới săn tiếp.",
        f"Máu vũ khí {render.fmt(summary.get('weapon_hp') or 0)}/{render.fmt(summary.get('weapon_max_hp') or 0)}.",
    ]
    cost = int(summary.get("repair_cost") or 0)
    if cost:
        lines.append(f"Sửa hết hao mòn: {render.fmt(cost)} vàng, ở Shop → Thợ rèn.")
    else:
        lines.append("Chưa hao, không cần sửa.")
    return "\n".join(lines)


def _armor_text(summary: dict) -> str:
    worn = summary.get("equipment") or {}
    lines = []
    for slot in eq.SINGLE_SLOTS:
        item = worn.get(slot)
        lines.append(f"{eq.SLOT_LABELS[slot]}: {item.get('name') if item else 'trống'}")
    for key, label in (("gloves", "Găng"), ("rings", "Nhẫn"), ("bracelets", "Vòng")):
        names = [item.get("name") if item else "trống" for item in (worn.get(key) or [None, None])]
        lines.append(f"{label}: {', '.join(names)}")
    bonus = summary.get("gear_bonus") or {}
    lines.append(
        "Cộng thêm "
        f"HP {_signed(bonus.get('hp'))} · ATK {_signed(bonus.get('atk'))} · "
        f"DEF {_signed(bonus.get('def'))} · SPD {_signed(bonus.get('spd'))}"
    )
    sets = bonus.get("sets") or []
    if sets:
        lines.append("Set đang đủ mảnh: " + ", ".join(piece.get("name") or "" for piece in sets))
    return "\n".join(lines)


def _belt_text(summary: dict) -> str:
    slots = list(summary.get("consumables") or [])
    while len(slots) < 5:
        slots.append(None)
    lines = []
    for index, item in enumerate(slots[:5], start=1):
        if not item:
            lines.append(f"{index}. trống")
            continue
        name = item.get("name") or "vật phẩm"
        qty = int(item.get("qty") or 1)
        if item.get("subtype") == "heal":
            note = "tự uống trong trận khi máu xuống"
        elif item.get("subtype") == "stamina" or int(item.get("heal_stamina") or 0) > 0:
            note = f"uống bằng nút Đai, +{int(item.get('heal_stamina') or 0)} thể lực"
        else:
            note = "tự kích hoạt trong trận"
        lines.append(f"{index}. {name} x{qty} — {note}")
    return "\n".join(lines)


def _pack_text(summary: dict) -> str:
    place = summary.get("location_name") or "chưa chọn map"
    karma_note = summary.get("karma_message") or "chưa đủ để làm quái khó hơn"
    lines = [
        f"Túi đang chứa {summary['bag_count']} món.",
        f"Xác quái {summary['monster_count']}/30"
        + (f", bán khoảng {render.fmt(summary['trophy_value'])} vàng" if summary["monster_count"] else "")
        + ". Đầy 30 thì không săn thêm được.",
        f"Khu hiện tại: {place}. Quái lấy từ khu này.",
        f"Karma {summary['karma']} — {karma_note}. Karma tăng khi thắng và làm quái spawn cao cấp hơn.",
    ]
    points = int(summary.get("points") or 0)
    if points:
        lines.append(
            f"Điểm kỹ năng chưa cộng: {render.fmt(points)}. "
            "1 điểm = 5 HP, 2 ATK, 2 DEF hoặc 1 SPD. Bấm Cộng điểm."
        )
    else:
        lines.append("Không có điểm kỹ năng chờ cộng. Lên cấp sẽ được thêm điểm.")
    run = summary.get("dungeon_run")
    if run:
        lines.append(
            f"Đang trong dungeon {run.get('dungeon_id')} "
            f"(phòng {int(run.get('room_index') or 0) + 1})."
        )
    return "\n".join(lines)


def me_reply(player_id: str, notice: str = "") -> Reply:
    summary = game.character_summary(player_id)
    if summary is None:
        return _reply("Chưa có nhân vật. Gõ `!new tên`.", "Chưa có nhân vật.")
    gold = data_store.get_gold(player_id)
    text = render.render_character(summary) + f"\n💰 Vàng: {render.fmt(gold)}"
    level = int(summary["level"])
    exp = int(summary["exp"])
    needed = int(summary["exp_needed"] or 1)
    stamina = int(summary["the_luc"])
    place = summary.get("location_name") or "chưa chọn map"
    loc_level = data_store.get_location_level(summary.get("location_id")) if summary.get("location_id") is not None else None
    over = loc_level is not None and level < int(loc_level)
    hunt_cost = 80 if over else 50
    fights_left = stamina // hunt_cost
    if stamina < hunt_cost:
        stamina_line = f"Thể lực {render.fmt(stamina)}. Săn ở đây tốn {hunt_cost}, hiện không đủ."
    else:
        stamina_line = f"Thể lực {render.fmt(stamina)}. Săn ở đây tốn {hunt_cost}, còn khoảng {fights_left} trận."
    if over:
        stamina_line += f" Map yêu cầu cấp {loc_level}, bạn đang cấp {level}, nên mỗi trận tốn thêm 30."
    battle = summary.get("battle") or {}
    if not battle:
        fight = "Chưa cầm vũ khí. Không có chỉ số ra trận và không săn được. Mua hoặc cầm vũ khí trong Túi."
    else:
        fight = "\n".join([
            f"Máu {render.fmt(battle.get('HP'))} — về 0 thì thua.",
            f"Đòn {render.fmt(battle.get('ATK'))} — sát thương mỗi nhát, sau khi trừ phần đỡ của quái.",
            f"Đỡ {render.fmt(battle.get('DEF'))} — giảm đòn nhận vào, không chặn hết.",
            f"Tốc {render.fmt(battle.get('SPD'))} — cao hơn quái thì bạn đánh trước.",
            f"Lực chiến {render.fmt(summary.get('power_total') or summary.get('power_basic') or 0)}.",
        ])
    karma = int(summary.get("karma") or 0)
    bonus = game.karma_level_bonus(karma)
    if bonus:
        karma_line = f"Karma {karma}. Quái spawn cao hơn {bonus} cấp."
    else:
        karma_line = f"Karma {karma}. Chưa làm quái spawn cao hơn."
    header = "\n".join([
        f"**{summary['name']}** · cấp {level} · {place}",
        f"{render.fmt(exp)}/{render.fmt(needed)} EXP · còn {render.fmt(max(0, needed - exp))} nữa thì lên cấp {level + 1}.",
        stamina_line,
        f"Vàng {render.fmt(gold)} · {karma_line}",
    ])
    fields = [
        separator("Ra trận", "Số này đã cộng vũ khí và giáp. Đây là số dùng khi đánh, không phải chỉ số trần."),
        field("Chỉ số khi đánh", fight, inline=False),
        separator("Đang mang"),
        field("Vũ khí", _weapon_text(summary), inline=False),
        field("Giáp", _armor_text(summary), inline=False),
        field("Đai", _belt_text(summary), inline=False),
        separator("Túi"),
        field("Hành trang", _pack_text(summary), inline=False),
        separator("Làm tiếp", "Mỗi hàng có nút bên phải. Không bấm thì nút tắt sau 8 phút."),
        _action_card("Túi", "Mở đồ. Chọn một món trong menu để cầm, mặc hoặc uống."),
        _action_card("Shop", "Mua vũ khí, đồ ăn, giáp, thuốc. Thợ rèn nằm trong shop."),
        _action_card("Map", "Đổi khu. Trận sau đánh quái của khu đó."),
        _action_card("Đai", "Năm ô nhanh. Uống thuốc thể lực ở đây."),
        _action_card("Săn", "Đánh một con ở khu hiện tại. Cần vũ khí còn bền và đủ thể lực."),
    ]
    buttons = [
        {"id": "mx:nav:bag", "label": "Túi", "style": "secondary"},
        {"id": "mx:nav:shop", "label": "Shop", "style": "primary"},
        {"id": "mx:nav:map", "label": "Map", "style": "secondary"},
        {"id": "mx:nav:gear", "label": "Đai", "style": "secondary"},
        {"id": "mx:nav:hunt", "label": "Săn", "style": "danger"},
    ]
    if summary.get("points"):
        fields.append(_action_card(
            "Cộng điểm",
            f"Đang có {render.fmt(summary['points'])} điểm. 1 điểm = 5 máu, 2 đòn, 2 đỡ hoặc 1 tốc.",
        ))
        buttons.append({"id": "mx:stat", "label": "Cộng điểm", "style": "success"})
    return _reply(
        text, header, fields=fields, controls={"buttons": buttons},
        author=summary["name"], title="Nhân vật", notice=notice,
    )


def _action_card(name: str, detail: str) -> dict:
    row = field(name, detail, inline=True)
    row["action"] = name
    return row


_BAG_KINDS = (
    ("all", "Tất cả"),
    ("weapon", "Vũ khí"),
    ("equipment", "Giáp"),
    ("material", "Nguyên liệu"),
    ("other", "Khác"),
)


def _bag_kind(item: dict) -> str:
    kind = item.get("type") or ""
    if kind == "weapon":
        return "weapon"
    if kind == "equipment":
        return "equipment"
    if kind == "material":
        return "material"
    return "other"


def bag_reply(player_id: str, page: int = 0, notice: str = "",
              kind: str = "all", tier: str = "all") -> Reply:
    from monster_game import tiers as tier_mod

    character = game.get_character(player_id)
    if character is None:
        return _reply("Chưa có nhân vật.", "Chưa có nhân vật.")
    if kind not in {key for key, _label in _BAG_KINDS}:
        kind = "all"
    bag = list(character.get("bag") or [])
    narrowed = [
        (index, item) for index, item in enumerate(bag, start=1)
        if kind == "all" or _bag_kind(item) == kind
    ]
    present = []
    seen = set()
    for _index, item in narrowed:
        tier_row = tier_mod.resolve(item.get("tier"))
        token = str(tier_row["id"]) if tier_row else ""
        if token and token not in seen:
            seen.add(token)
            present.append(tier_row)
    present.sort(key=lambda tier_row: int(tier_row["rank"]))
    if tier != "all" and not any(str(tier_row["id"]) == tier for tier_row in present):
        tier = "all"
    shown = narrowed
    if tier != "all":
        shown = [
            (index, item) for index, item in narrowed
            if tier_mod.same_tier(item, {"id": tier})
        ]
    pages = max(1, (len(shown) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = shown[page * PAGE:(page + 1) * PAGE]
    gold = data_store.get_gold(player_id)
    options = []
    for index, item in chunk:
        label = f"{index}. {item.get('name', '?')} x{int(item.get('qty', 1))}"
        hint = _bag_hint(item)
        tier_row = tier_mod.resolve(item.get("tier"))
        mark = f"bậc {tier_row['label']} · " if tier_row else ""
        options.append(_opt(label, str(index), f"{mark}{hint}"))
    kind_name = dict(_BAG_KINDS).get(kind, "Tất cả")
    tier_name = "mọi bậc" if tier == "all" else tier_mod.label_of(tier)
    if not bag:
        body = row("Túi", None)
        note = "Mở chợ để mua đồ ăn, thuốc và vũ khí."
    elif not shown:
        body = row("Lọc", None)
        note = "Không có món nào trong lọc này."
    else:
        body = "\n".join(
            row(str(index), f"{item.get('name')} x{int(item.get('qty', 1))}")
            for index, item in chunk
        )
        note = f"Trang {page + 1}/{pages}. Số thứ tự là vị trí thật trong túi."
    header_bits = blocks(
        "\n".join([
            row("Tên", character["name"]),
            row("Đang cầm", (character.get("weapon") or {}).get("name")),
        ]),
        "\n".join([
            row("Loại", kind_name),
            row("Bậc", tier_name),
            body,
        ]),
        "\n".join([
            measure("Vàng", render.fmt(gold)),
            measure("Thể lực", render.fmt(character.get("the_luc", 0))),
        ]),
        note,
    )
    selects = []
    tier_options = [_opt("Mọi bậc", "all", "Bỏ lọc bậc")]
    for tier_row in present[:24]:
        tier_options.append(_opt(f"Bậc {tier_row['label']}", str(tier_row["id"]), tier_row.get("obtain") or ""))
    selects.append({
        "id": f"mx:bagt:{kind}",
        "placeholder": "Chọn bậc…",
        "options": tier_options,
    })
    if options:
        selects.append({
            "id": f"mx:bag:{kind}:{tier}:{page}",
            "placeholder": "Dùng hoặc trang bị…",
            "options": options,
        })
    buttons = []
    for key, label in _BAG_KINDS:
        buttons.append({
            "id": f"mx:bagk:{key}",
            "label": label,
            "style": "primary" if kind == key else "secondary",
            "band": "loai",
        })
    if page > 0:
        buttons.append({
            "id": f"mx:page:{kind}:{tier}:{page - 1}",
            "label": "Trước", "style": "secondary", "band": "trang",
        })
    if page + 1 < pages:
        buttons.append({
            "id": f"mx:page:{kind}:{tier}:{page + 1}",
            "label": "Sau", "style": "secondary", "band": "trang",
        })
    buttons.extend([
        {"id": "mx:sell", "label": "Bán xác", "style": "success", "band": "ban", "hint": "Bán xác quái, nhận vàng"},
        {"id": "mx:nav:gear", "label": "Đai", "style": "primary", "band": "chan"},
        {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
    ])
    text = render.render_bag(character)
    if notice:
        text = notice + "\n" + text
    return _reply(
        text, header_bits,
        controls={"selects": selects, "buttons": buttons},
        author=character["name"], notice=notice, title="Túi đồ", menu=True,
    )


def _bag_hint(item: dict) -> str:
    kind = item.get("type")
    if kind == "weapon":
        return "Trang bị vũ khí"
    if kind == "equipment":
        return f"Mặc {item.get('slot', 'giáp')}"
    if item.get("subtype") == "stamina" or item.get("type") == "food":
        amount = int(item.get("heal_stamina") or item.get("heal") or 0)
        return f"Uống, +{amount} thể lực" if amount else "Dùng ngay"
    if item.get("subtype") == "heal":
        return "Đưa cả chồng lên đai"
    if item.get("belt") is True:
        return "Đưa lên đai, dùng trong trận"
    if kind == "upgrade":
        return "Cộng vào vũ khí đang cầm"
    if kind == "material":
        return "Nguyên liệu, không dùng trực tiếp"
    return kind or "vật phẩm"


def gear_reply(player_id: str, notice: str = "") -> Reply:
    character = game.get_character(player_id)
    if character is None:
        return _reply("Chưa có nhân vật.", "Chưa có nhân vật.")
    eq.ensure_loadout(character)
    options = []
    slot_lines = []
    for i, item in enumerate(character["consumables"], start=1):
        if not item:
            slot_lines.append(row(str(i), None))
            continue
        qty = int(item.get("qty", 1))
        slot_lines.append(row(str(i), f"{item.get('name')} x{qty}"))
        if item.get("subtype") == "stamina" or int(item.get("heal_stamina") or 0) > 0:
            options.append(_opt(f"Uống {item.get('name')} x{qty}", f"drink:{i}", f"+{int(item.get('heal_stamina') or 0)} thể lực"))
        else:
            options.append(_opt(f"{item.get('name')} x{qty}", f"info:{i}", "Tự dùng trong trận"))
    header = blocks(
        row("Đai", character["name"]),
        "\n".join(slot_lines),
        "Bình máu sẽ tự uống trong trận.",
        "Thuốc thể lực uống ở đây.",
    )
    controls = {"buttons": [
        {"id": "mx:nav:rest", "label": "Nghỉ", "style": "success", "band": "nghi", "hint": "Hồi thể lực"},
        {"id": "mx:nav:bag", "label": "Túi", "style": "primary", "band": "chan"},
        {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
    ]}
    if options:
        controls["selects"] = [{"id": "mx:belt", "placeholder": "Chọn ô đai…", "options": options}]
    text = render.render_equipment(character) + "\n\n" + render.render_belt(character)
    return _reply(
        text, header,
        controls=controls, author=character["name"], notice=notice, title="Đai", menu=True,
    )


def map_reply(player_id: str, notice: str = "") -> Reply:
    character = game.get_character(player_id)
    locs = game.list_locations()
    options = []
    loc_lines = []
    here = str(character.get("locationID")) if character else ""
    for i, loc in enumerate(locs, start=1):
        here_mark = "đang ở" if str(loc.get("ID")) == here else None
        loc_lines.append(row(str(i), loc.get("name")))
        if here_mark:
            loc_lines.append(row("Đang ở", loc.get("name")))
        options.append(_opt(f"{i}. {loc.get('name')}", str(i), f"Lv.{loc.get('level', '?')}"))
    header = blocks(
        row("Bản đồ", "Chọn khu vực"),
        "\n".join(loc_lines) or row("Map", None),
        measure("Số map", str(len(locs))),
        "Trận sau sẽ săn quái ở khu vừa chọn.",
    )
    controls = {
        "selects": [{"id": "mx:go", "placeholder": "Đi đến…", "options": options}],
        "buttons": [
            {"id": "mx:nav:hunt", "label": "Săn", "style": "danger", "band": "san", "hint": "Săn ngay tại map đang đứng"},
            {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
        ],
    } if options else {"buttons": [{"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"}]}
    text = render.render_locations(locs, character)
    return _reply(
        text, header,
        controls=controls, notice=notice, title="Bản đồ", menu=True,
    )


def shop_reply(player_id: str, notice: str = "") -> Reply:
    gold = data_store.get_gold(player_id) if game.get_character(player_id) else 0
    options = [
        _opt("Vũ khí", "weapons", "Chọn loại kiếm, thương, súng…"),
        _opt("Đồ ăn và thuốc", "food", "Hồi thể lực, cộng chỉ số"),
        _opt("Giáp và trang sức", "armor", "Chọn ô rồi mua"),
        _opt("Tiêu hao và bùa", "item", "Bình máu, thể lực, bùa"),
        _opt("Chế tạo", "craft", "Công thức đang có"),
        _opt("Thợ rèn", "forge", "Đập, sửa, xem tỉ lệ"),
    ]
    header = blocks(
        row("Chợ", "Chọn quầy"),
        "Vũ khí, đồ ăn, giáp, thuốc, chế tạo.",
        measure("Vàng", render.fmt(gold)),
        "Thợ rèn nằm ở nút Rèn.",
    )
    return _reply(
        render.render_shop_menu(),
        header,
        controls={
            "selects": [{"id": "mx:shop", "placeholder": "Chọn quầy…", "options": options}],
            "buttons": [
                {"id": "mx:forge:open", "label": "Rèn", "style": "primary", "band": "ren", "hint": "Đập và sửa vũ khí"},
                {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
            ],
        },
        notice=notice,
        title="Cửa hàng",
        menu=True,
    )


def weapon_menu_reply(player_id: str, notice: str = "") -> Reply:
    options = [
        _opt(shop.CATEGORY_LABELS.get(name, name), name, "Xem vũ khí loại này")
        for _key, name in shop.WEAPON_CATEGORIES.items()
    ]
    header = blocks(
        row("Vũ khí", "Chọn loại"),
        "Kiếm Lời Thoại có nhiều câu ra đòn hơn kiếm thường.",
        measure("Loại", str(len(options))),
        "Chọn loại trong menu.",
    )
    return _reply(header, header, controls={
        "selects": [{"id": "mx:wcat", "placeholder": "Chọn loại…", "options": options}],
        "buttons": [
            {"id": "mx:back", "label": "Chợ", "style": "secondary", "band": "nav", "hint": "Về quầy chính"},
            {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
        ],
    }, notice=notice, title="Vũ khí", menu=True)


def forge_reply(player_id: str, notice: str = "") -> Reply:
    character = game.get_character(player_id)
    if character is None:
        return _reply("Chưa có nhân vật.", "Chưa có nhân vật.", title="Thợ rèn")
    quote = game.enhance_quote(player_id, "weapon")
    if not quote.get("ok"):
        header = blocks(
            row("Thợ rèn", character["name"]),
            row("Vũ khí", None),
            row("Vàng", None),
            "Hãy cầm vũ khí, rồi mở lại.",
        )
    else:
        need = list(quote.get("stones") or []) + list(quote.get("materials") or [])
        bits = []
        for req in need:
            drop = data_store.get_drop(req["item_id"]) or data_store.get_consumable(req["item_id"])
            bits.append(row((drop or {}).get("name", req["item_id"]), f"x{req['qty']}"))
        rate = f"{quote['rate'] * 100:.0f}%"
        if quote.get("rate_with_max_luck") is not None:
            rate += f" · may {quote['rate_with_max_luck'] * 100:.0f}%"
        header = blocks(
            "\n".join([
                row("Thợ rèn", character["name"]),
                row("Vũ khí", quote.get("display")),
            ]),
            "\n".join(bits) or row("Nguyên liệu", None),
            "\n".join([
                measure("Cấp", f"+{quote.get('current', 0)} → +{quote['next_level']}"),
                measure("Tỉ lệ", rate),
                measure("Vàng", render.fmt(quote["gold"])),
            ]),
            "Chọn bùa trong menu. Nút Sửa dùng để hồi độ bền.",
        )
    options = [_opt("Đập không bùa", "plain", "Chỉ tốn vàng và đá")]
    for index, item in enumerate(character.get("bag") or [], start=1):
        subtype = item.get("subtype")
        if subtype == "enhance_protect":
            options.append(_opt(f"Bảo hộ: {item.get('name')}", f"p:{index}", "Giữ một phần cấp khi vỡ"))
        elif subtype == "enhance_luck":
            options.append(_opt(f"May mắn: {item.get('name')}", f"l:{index}", "Cộng tỉ lệ, có trần theo cấp +"))
    controls = {
        "buttons": [
            {"id": "mx:repair", "label": "Sửa vũ khí", "style": "success"},
            {"id": "mx:stones", "label": "Mua đá", "style": "primary"},
            {"id": "mx:back", "label": "Quay lại shop", "style": "secondary"},
        ],
    }
    if options:
        controls["selects"] = [{"id": "mx:forge", "placeholder": "Đập như thế nào…", "options": options[:25]}]
    controls["buttons"] = [
        {"id": "mx:repair", "label": "Sửa", "style": "success", "band": "ren", "hint": "Sửa độ bền vũ khí đang cầm"},
        {"id": "mx:stones", "label": "Mua đá", "style": "primary", "band": "chan"},
        {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
    ]
    return _reply(header, header[:1500], controls=controls, notice=notice, title="Thợ rèn", menu=True)


def _catalog_items(catalog: str) -> tuple[list[dict], bool]:
    """Return (items, stackable)."""
    if catalog.startswith("w:"):
        return shop.weapons_by_category(catalog[2:]), False
    if catalog == "food":
        return data_store.get_food_items(), True
    if catalog == "stone":
        return shop.stone_catalog(), True
    if catalog == "item":
        return data_store.get_consumables(), True
    if catalog.startswith("a:"):
        return shop.for_sale(data_store.get_equipment(catalog[2:])), False
    return [], False


def _num(item: dict | None, *keys: str) -> int:
    if not item:
        return 0
    for key in keys:
        if item.get(key) is not None:
            return int(item.get(key) or 0)
    return 0


def _compare(shop_item: dict, worn: dict | None) -> str:
    if not worn:
        return "chưa có món đang dùng"
    bits = []
    for keys, label in ((("HP", "hp"), "máu"), (("ATK", "atk"), "đòn"), (("DEF", "def"), "đỡ"), (("SPD", "spd"), "tốc")):
        delta = _num(shop_item, *keys) - _num(worn, *keys)
        if delta:
            bits.append(f"{label} {'+' if delta > 0 else ''}{delta}")
    return ", ".join(bits) if bits else "ngang món đang dùng"


def _worn_for(character: dict | None, catalog: str):
    if character is None:
        return None
    if catalog.startswith("w:"):
        return character.get("weapon")
    if catalog.startswith("a:"):
        worn = (character.get("equipment") or {}).get(catalog[2:])
        if isinstance(worn, list):
            return next((piece for piece in worn if piece), None)
        return worn
    return None


def shop_list_reply(player_id: str, catalog: str, notice: str = "") -> Reply:
    if catalog == "armor":
        options = [_opt(eq.SLOT_LABELS.get(slot, slot), slot, "Xem món của ô này") for slot in list(eq.SLOT_LABELS)]
        header = blocks(
            row("Giáp", "Chọn ô"),
            "Mũ, áo, quần, giày và đồ tay.",
            measure("Ô", str(len(options))),
            "Chọn ô trong menu.",
        )
        return _reply(header, header, controls={
            "selects": [{"id": "mx:aslot", "placeholder": "Ô trang bị…", "options": options}],
            "buttons": [
                {"id": "mx:back", "label": "Chợ", "style": "secondary", "band": "nav", "hint": "Về quầy chính"},
                {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
            ],
        }, notice=notice, title="Giáp", menu=True)
    if catalog == "craft":
        from monster_game import craft as craft_mod
        recipes = craft_mod.list_recipes()
        options = []
        recipe_lines = []
        gold = data_store.get_gold(player_id)
        for recipe in recipes[:25]:
            check = craft_mod.can_craft(player_id, recipe["id"], gold)
            flag = "làm được" if check.get("ok") else "thiếu đồ"
            recipe_lines.append(row(recipe["name"], flag))
            options.append(_opt(recipe["name"], recipe["id"], flag))
        header = blocks(
            row("Chế tạo", "Chọn công thức"),
            "\n".join(recipe_lines) or row("Công thức", None),
            measure("Vàng", render.fmt(gold)),
            "Chọn công thức trong menu.",
        )
        controls = {"buttons": [{"id": "mx:back", "label": "Quay lại shop", "style": "secondary"}]}
        if options:
            controls["selects"] = [{"id": "mx:make", "placeholder": "Chọn công thức…", "options": options}]
        controls["buttons"] = [
            {"id": "mx:back", "label": "Chợ", "style": "secondary", "band": "nav", "hint": "Về quầy chính"},
            {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
        ]
        return _reply(header, header[:1500], controls=controls, notice=notice, title="Chế tạo", menu=True)

    items, stackable = _catalog_items(catalog)
    gold = data_store.get_gold(player_id)
    worn = _worn_for(game.get_character(player_id), catalog)
    lines = []
    options = []
    for i, item in enumerate(items[:25], start=1):
        price = int(item.get("price") or 0)
        attack_n = len(item.get("attacks") or [])
        extra = f" · {attack_n} câu ra đòn" if attack_n else ""
        compared = _compare(item, worn) if worn is not None or catalog.startswith(("w:", "a:")) else ""
        if compared:
            extra += f" · {compared}"
        lines.append(f"{i}. {item.get('name')} · {render.fmt(price)} vàng{extra}")
        value = f"q:{i}" if stackable else f"b:{i}"
        desc = compared or f"{render.fmt(price)} vàng"
        if attack_n and not compared:
            desc = f"{desc}, {attack_n} câu"
        options.append(_opt(f"{i}. {item.get('name')}", value, desc))
    title = catalog.split(":", 1)[-1]
    header = blocks(
        row("Quầy", title),
        "\n".join(row(str(i), item.get("name")) for i, item in enumerate(items[:25], start=1)) or row("Quầy", None),
        measure("Vàng", render.fmt(gold)),
        "Chọn món, rồi nhập số lượng." if stackable else "Chọn món trong menu.",
    )
    controls = {"buttons": [
        {"id": "mx:back", "label": "Chợ", "style": "secondary", "band": "nav", "hint": "Về quầy chính"},
        {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
    ]}
    if options:
        controls["selects"] = [{"id": f"mx:buy:{catalog}", "placeholder": "Chọn món…", "options": options}]
    return _reply(header, header[:1500], controls=controls, notice=notice, title=title[:80], menu=True)


def buy_amount(player_id: str, catalog: str, index: int, qty: int) -> str:
    qty = max(1, min(20, int(qty)))
    items, stackable = _catalog_items(catalog)
    if not (1 <= index <= len(items)):
        return "Không có món này."
    if not stackable:
        qty = 1
    got = 0
    spent = 0
    name = items[index - 1].get("name", "món")
    error = ""
    for _ in range(qty):
        balance = data_store.get_gold(player_id)
        if catalog.startswith("w:"):
            result = shop.purchase_weapon(player_id, catalog[2:], index, balance)
        elif catalog == "food":
            result = shop.purchase_food(player_id, index, balance)
        elif catalog == "stone":
            result = shop.purchase_upgrade_material(player_id, index, balance)
        elif catalog == "item":
            result = shop.purchase_consumable(player_id, index, balance)
        elif catalog.startswith("a:"):
            result = shop.purchase_equipment(player_id, index, balance, slot=catalog[2:])
        else:
            return "Quầy không bán món này."
        if not result.ok:
            error = result.message
            break
        data_store.add_gold(player_id, -int(result.cost))
        got += 1
        spent += int(result.cost)
        name = (result.item or {}).get("name", name)
    if got == 0:
        return f"Không mua được. {error}"
    left = data_store.get_gold(player_id)
    text = f"Đã mua **{name}** x{got} · −{render.fmt(spent)} vàng. Còn {render.fmt(left)}."
    if error and got < qty:
        text += f"\nDừng vì: {error}"
    return text


def _task_buttons(player_id: str) -> list[dict]:
    user = game.get_character(player_id) or {}
    flags = user.get("tasks") or {}
    spec = {
        "sell": ("mx:task:sell", "💰 Bán xác"),
        "craft": ("mx:task:craft", "🧪 Chế đồ"),
        "dungeon": ("mx:task:dungeon", "🏰 Vào hầm"),
    }
    lines = []
    buttons = []
    for task_id, text, gold in game.TASKS:
        if flags.get(task_id):
            continue
        cid, label = spec[task_id]
        buttons.append({
            "id": cid, "label": label, "style": "success", "band": "viec",
        })
        lines.append(f"{text}. Thưởng {render.fmt(gold)} vàng.")
    if buttons:
        buttons[0]["caption"] = "\n".join(lines)
    return buttons


def _stat_buttons(player_id: str) -> list[dict]:
    user = game.get_character(player_id) or {}
    if int(user.get("points") or 0) <= 0:
        return []
    names = {"hp": "Máu", "atk": "Đòn", "def": "Đỡ", "spd": "Tốc"}
    labels = {
        "hp": "❤️ Cộng máu",
        "atk": "⚔️ Cộng đòn",
        "def": "🛡️ Cộng đỡ",
        "spd": "💨 Cộng tốc",
    }
    keys = {"hp": "HP", "atk": "ATK", "def": "DEF", "spd": "SPD"}
    lines = []
    buttons = []
    for stat in ("hp", "atk", "def", "spd"):
        now, nxt = game.next_battle(player_id, stat)
        if now and nxt:
            lines.append(f"**{names[stat]}** » `{render.fmt(now[keys[stat]])}` → `{render.fmt(nxt[keys[stat]])}`")
        else:
            lines.append(f"**{names[stat]}** » *chưa có vũ khí*")
        buttons.append({
            "id": f"mx:stat:{stat}",
            "label": labels[stat],
            "style": "success",
            "band": "diem",
            "stack": True,
        })
    if buttons:
        buttons[0]["caption"] = (
            f"Còn {render.fmt(int(user.get('points') or 0))} điểm. "
            "Mỗi điểm máu, đòn hoặc đỡ tăng 1% chỉ số trong trận. Mỗi điểm tốc tăng 1.\n"
            + "\n".join(lines)
        )
    return buttons


def _daily_buttons(player_id: str) -> list[dict]:
    rows = game.daily_view(player_id)
    if not rows:
        return []
    if all(row["done"] for row in rows):
        return [{
            "id": "mx:daily:done",
            "label": "Mai",
            "style": "secondary",
            "band": "ngay",
            "caption": "Hôm nay đã xong việc. Mai sẽ có việc mới.",
        }]
    labels = {"hunt": "🎯 Săn ngày", "sell": "💰 Bán ngày", "rest": "💤 Nghỉ ngày"}
    ids = {"hunt": "mx:daily:hunt", "sell": "mx:daily:sell", "rest": "mx:daily:rest"}
    lines = []
    buttons = []
    for daily in rows:
        if daily["done"]:
            lines.append(f"✓ {daily['text']} {daily['need']}/{daily['need']}")
            continue
        lines.append(f"○ {daily['text']}: {daily['have']}/{daily['need']}. Thưởng {render.fmt(daily['gold'])} vàng.")
        buttons.append({
            "id": ids[daily["id"]], "label": labels[daily["id"]],
            "style": "primary", "band": "ngay",
        })
    buttons[0]["caption"] = "\n".join(lines)
    return buttons


def _menu_buttons(player_id: str) -> list[dict]:
    pending = game.get_pending_adventure(player_id)
    hunt_id = "mx:nav:event" if pending else "mx:nav:hunt"
    buttons = [
        {"id": hunt_id, "label": "🗡️ Đi săn", "style": "danger", "band": "chinh"},
        {"id": "mx:nav:map", "label": "🗺️ Đổi map", "style": "secondary", "band": "chinh"},
        {"id": "mx:nav:rest", "label": "💤 Nghỉ ngơi", "style": "success", "band": "chinh"},
        {"id": "mx:nav:bag", "label": "🎒 Túi đồ", "style": "secondary", "band": "chinh"},
        {"id": "mx:nav:shop", "label": "🏪 Cửa hàng", "style": "primary", "band": "chinh"},
        {"id": "mx:forge:open", "label": "🔨 Thợ rèn", "style": "primary", "band": "chinh"},
    ]
    buttons.extend(_stat_buttons(player_id))
    buttons.extend([
        {"id": "mx:nav:dungeon", "label": "🏰 Vào hầm", "style": "secondary", "band": "xa"},
        {"id": "mx:nav:party", "label": "👥 Tổ đội", "style": "secondary", "band": "xa"},
        {"id": "mx:nav:pvp", "label": "⚔️ Đấu tay", "style": "secondary", "band": "xa"},
    ])
    buttons.extend(_task_buttons(player_id))
    buttons.extend(_daily_buttons(player_id))
    return buttons


def menu_reply(player_id: str, channel_id: str = "", notice: str = "") -> Reply:
    summary = game.character_summary(player_id)
    if summary is None:
        return _reply("Chưa có nhân vật. Gõ `!new tên`.", "Chưa có nhân vật.")
    gold = data_store.get_gold(player_id)
    level = int(summary["level"])
    stamina = int(summary["the_luc"])
    place = summary.get("location_name") or "chưa chọn map"
    loc_level = data_store.get_location_level(summary.get("location_id")) if summary.get("location_id") is not None else None
    over = loc_level is not None and level < int(loc_level)
    hunt_cost = 80 if over else 50
    battle = summary.get("battle")
    if battle:
        fight = "\n".join([
            measure("Máu", render.fmt(battle["HP"])),
            measure("Đòn", render.fmt(battle["ATK"])),
            measure("Đỡ", render.fmt(battle["DEF"])),
            measure("Tốc", render.fmt(battle["SPD"])),
        ])
    else:
        fight = row("Vũ khí", None)
    points = int(summary.get("points") or 0)
    numbers = [
        measure("Thể lực", render.fmt(stamina)),
        measure("Săn tốn", render.fmt(hunt_cost)),
        measure("Vàng", render.fmt(gold)),
    ]
    if summary.get("weapon_name"):
        numbers.append(measure("Bền", f"{int(summary.get('weapon_durability') or 0)}/100"))
    else:
        numbers.append(row("Bền", None))
    if points:
        numbers.append(measure("Điểm", render.fmt(points)))
    waiting = game.waiting_text(player_id, channel_id)
    if waiting.startswith("Đang chờ: "):
        waiting = waiting[len("Đang chờ: "):]
    header = blocks(
        "\n".join([
            row("Tên", summary["name"]),
            measure("Cấp", render.fmt(level)),
            row("Map", place),
        ]),
        fight,
        "\n".join(numbers),
        row("Đang chờ", waiting),
    )
    text = render.render_character(summary) + f"\n💰 Vàng: {render.fmt(gold)}"
    controls = {"buttons": _menu_buttons(player_id)}
    if points:
        controls["selects"] = [_spend_all_select(player_id, points)]
    return _reply(
        text, header, controls=controls,
        author=summary["name"], notice=notice, title="Menu", menu=True,
    )


def _spend_all_select(player_id: str, points: int) -> dict:
    names = {"hp": "Máu", "atk": "Đòn", "def": "Đỡ", "spd": "Tốc"}
    keys = {"hp": "HP", "atk": "ATK", "def": "DEF", "spd": "SPD"}
    options = []
    for stat in ("hp", "atk", "def", "spd"):
        now, nxt = game.next_battle(player_id, stat, points)
        if now and nxt:
            desc = f"{render.fmt(now[keys[stat]])} → {render.fmt(nxt[keys[stat]])}"
        else:
            desc = "Chưa cầm vũ khí, điểm vẫn được giữ"
        options.append(_opt(names[stat], stat, desc))
    return {
        "id": "mx:statall",
        "placeholder": "Cộng hết vào…",
        "options": options,
    }


def dungeon_reply(player_id: str, notice: str = "") -> Reply:
    character = game.get_character(player_id)
    if character is None:
        return _reply("Chưa có nhân vật.", "Chưa có nhân vật.")
    run = character.get("dungeon_run")
    if not run:
        labels = {
            "cong_tan_thu": "🏰 Vào cổng",
            "ham_pho_dem": "🌃 Vào phố",
            "kho_cutscene": "🎬 Vào kho",
        }
        lines = []
        buttons = []
        for dungeon in game.list_dungeons():
            dungeon_id = dungeon.get("id") or ""
            lines.append(row(
                dungeon.get("name") or "Hầm",
                f"cấp {dungeon.get('min_level', 1)}+, tốn {dungeon.get('stamina_cost', 0)} thể lực",
            ))
            buttons.append({
                "id": f"mx:dun:{dungeon_id}",
                "label": labels.get(dungeon_id, (dungeon.get("name") or "Vào")[:20]),
                "style": "primary",
                "band": "vao",
            })
        buttons.append({"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"})
        header = blocks(
            row("Hầm", "Chưa vào"),
            "\n".join(lines) or row("Hầm", None),
            measure("Số hầm", str(len(lines))),
            "Bấm một hầm để vào.",
        )
        return _reply(header, header, controls={"buttons": buttons}, notice=notice, title="Hầm", menu=True)
    pending = (run.get("pending_event") or {})
    dungeon = next((item for item in game.list_dungeons() if item.get("id") == run.get("dungeon_id")), {})
    name = dungeon.get("name") or run.get("dungeon_id")
    room_no = int(run.get("room_index") or 0) + 1
    buttons = []
    if pending:
        main = (pending.get("intro") or "").strip() or row("Việc", "Chọn một hướng")
        for action in (pending.get("actions") or [])[:3]:
            label = (action.get("label") or action.get("id") or "chọn")[:80]
            detail = (action.get("hint") or action.get("text") or "").strip()
            buttons.append({
                "id": f"mx:dact:{action.get('id')}", "label": label, "style": "primary", "band": "phong",
                **({"hint": detail[:180]} if detail and detail != label else {}),
            })
        note = "Bấm nút trên thẻ này."
    else:
        main = row("Việc", "Vào phòng này")
        buttons.append({"id": "mx:dnext", "label": "Tiếp", "style": "danger", "band": "phong", "hint": "Vào phòng này"})
        note = "Bấm Tiếp để vào phòng."
    buttons.extend([
        {"id": "mx:dabort", "label": "Rút", "style": "secondary", "band": "chan"},
        {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
    ])
    header = blocks(
        row("Hầm", name),
        main,
        measure("Phòng", str(room_no)),
        note,
    )
    return _reply(header, header, controls={"buttons": buttons}, notice=notice, title="Hầm", menu=True)


def party_menu_reply(player_id: str, channel_id: str, notice: str = "") -> Reply:
    from monster_game import party as party_mod
    mine = party_mod.find_party(str(channel_id), str(player_id))
    parties = party_mod.list_parties(str(channel_id))
    options = []
    if mine:
        names = ", ".join(mine.get("members") or [])
        header = blocks(
            row("Đội", mine.get("title")),
            row("Thành viên", names),
            measure("Người", str(len(mine.get("members") or []))),
            "Đội sẽ mất khi bot khởi động lại.",
        )
        buttons = [
            {"id": "mx:party:hunt", "label": "Săn cùng", "style": "danger", "band": "di", "hint": "Cả đội đánh một trận"},
            {"id": "mx:party:leave", "label": "Rời", "style": "secondary", "band": "chan"},
            {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
        ]
    else:
        header = blocks(
            row("Đội", None),
            "Lập đội, hoặc chọn đội có sẵn.",
            measure("Đội đang mở", str(len(parties))),
            "Đội sẽ mất khi bot khởi động lại.",
        )
        for party in parties[:25]:
            options.append(_opt(party.get("title") or "Đội", str(party.get("stt")), f"{len(party.get('members') or [])} người"))
        buttons = [
            {"id": "mx:party:new", "label": "Lập đội", "style": "primary", "band": "lap", "hint": "Tạo đội trong kênh này"},
            {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
        ]
    controls = {"buttons": buttons}
    if options:
        controls["selects"] = [{"id": "mx:pjoin", "placeholder": "Vào đội…", "options": options}]
    return _reply(header, header, controls=controls, notice=notice, title="Đội", menu=True)


def pvp_menu_reply(player_id: str, channel_id: str, notice: str = "") -> Reply:
    rooms = game.list_rooms(str(channel_id))
    mine = game.find_room(str(channel_id), str(player_id))
    options = []
    if mine:
        header = blocks(
            row("Phòng", mine.get("title") or mine.get("stt")),
            measure("Người", str(len(mine.get("players") or []))),
            measure("Phòng số", str(mine.get("stt") or "")),
            "Phòng đấu sẽ mất khi bot khởi động lại.",
        )
        buttons = [
            {"id": "mx:pvp:ready", "label": "Sẵn sàng", "style": "success", "band": "dau", "hint": "Báo đã sẵn sàng"},
            {"id": "mx:pvp:fight", "label": "Đánh", "style": "danger", "band": "dau", "hint": "Bắt đầu trận khi đủ người"},
            {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
        ]
    else:
        header = blocks(
            row("Phòng", None),
            "Tạo phòng, hoặc chọn phòng đang mở.",
            measure("Phòng đang mở", str(len(rooms))),
            "Phòng đấu sẽ mất khi bot khởi động lại.",
        )
        for index, room in enumerate(rooms[:25], start=1):
            options.append(_opt(room.get("title") or f"Phòng {index}", str(index), f"{len(room.get('players') or [])} người"))
        buttons = [
            {"id": "mx:pvp:new", "label": "Tạo phòng", "style": "primary", "band": "tao", "hint": "Mở phòng đấu trong kênh này"},
            {"id": "mx:nav:menu", "label": "Menu", "style": "secondary", "band": "chan"},
        ]
    controls = {"buttons": buttons}
    if options:
        controls["selects"] = [{"id": "mx:pvpjoin", "placeholder": "Vào phòng…", "options": options}]
    return _reply(header, header, controls=controls, notice=notice, title="Đấu", menu=True)


def _lenh(prefix: str, meaning: str, slash: str = "") -> str:
    value = f"/{slash} · {meaning}" if slash else meaning
    return row(f"!{prefix}", value)


_HELP_GROUPS = (
    ("nhan", "Nhân vật", [
        _lenh("me", "mở menu nhân vật", "toi"),
        _lenh("bag", "mở túi đồ", "tui"),
        _lenh("gear", "xem giáp và đai"),
        _lenh("log", "xem nhật ký các trận"),
        _lenh("new tên", "tạo nhân vật mới"),
        _lenh("stat hp 1", "cộng điểm vào máu, đòn, đỡ hoặc tốc"),
    ]),
    ("san", "Săn", [
        _lenh("hunt", "săn một trận ở map hiện tại", "san"),
        _lenh("map", "xem danh sách khu vực", "bando"),
        _lenh("go 1", "đến khu vực theo số trên bản đồ"),
        _lenh("pick mã", "chọn một hướng khi có sự kiện"),
        "Khi thẻ sự kiện đang mở, bấm nút trên thẻ đó.",
    ]),
    ("cho", "Chợ", [
        _lenh("shop", "mở cửa hàng", "cho"),
        _lenh("sell", "bán hết xác quái, nhận vàng"),
        _lenh("sellmat", "bán hết nguyên liệu trong túi"),
        "Mua vũ khí, giáp và thuốc bằng nút trên thẻ chợ.",
    ]),
    ("do", "Đồ", [
        _lenh("use 1", "dùng món ở ô số 1 trong túi"),
        _lenh("unequip helmet", "tháo mũ đang mặc"),
        _lenh("belt 1 2", "gắn ô túi 2 vào đai ô 1"),
        _lenh("gear", "uống thuốc thể lực trên đai"),
    ]),
    ("ren", "Rèn", [
        _lenh("quote", "xem vàng và tỉ lệ đập"),
        _lenh("forge", "cường hóa vũ khí đang cầm"),
        _lenh("repair", "hồi độ bền vũ khí"),
    ]),
    ("ham", "Hầm", [
        _lenh("dungeon", "xem các hầm đang mở"),
        _lenh("enter cong_tan_thu", "vào hầm cổng tân thủ"),
        _lenh("next", "đi tiếp một phòng"),
        _lenh("abort", "rút khỏi hầm"),
        "Khi đang trong hầm, bấm nút trên thẻ đang mở.",
    ]),
    ("doi", "Đội", [
        _lenh("pnew", "lập đội trong kênh này"),
        _lenh("parties", "xem các đội đang mở"),
        _lenh("join 1", "vào đội theo số"),
        _lenh("phunt", "cả đội săn một trận"),
        _lenh("leave", "rời đội"),
        "Khi đang trong đội, bấm nút trên thẻ đang mở.",
    ]),
    ("dau", "Đấu", [
        _lenh("pvp", "tạo phòng đấu"),
        _lenh("rooms", "xem phòng trong kênh"),
        _lenh("pvpjoin 1", "vào phòng theo số"),
        _lenh("ready", "báo đã sẵn sàng"),
        _lenh("fight", "chủ phòng bắt đầu trận"),
        "Khi đang trong phòng, bấm nút trên thẻ đang mở.",
    ]),
)

_HELP_ALIAS = {
    "nhan": "nhan", "nhân": "nhan", "nhân vật": "nhan", "hero": "nhan",
    "san": "san", "săn": "san", "hunt": "san",
    "cho": "cho", "chợ": "cho", "shop": "cho",
    "do": "do", "đồ": "do", "gear": "do",
    "ren": "ren", "rèn": "ren", "forge": "ren",
    "ham": "ham", "hầm": "ham", "dungeon": "ham",
    "doi": "doi", "đội": "doi", "party": "doi",
    "dau": "dau", "đấu": "dau", "pvp": "dau",
}


def help_reply(group: str | None = None) -> Reply:
    key = _HELP_ALIAS.get((group or "").strip().lower())
    options = [_opt(title, gid, "Xem việc trong nhóm này") for gid, title, _lines in _HELP_GROUPS]
    if key:
        title, lines = next((title, lines) for gid, title, lines in _HELP_GROUPS if gid == key)
        body = "\n".join(lines)
        note = "Bấm Về menu để quay lại chỗ chơi."
        heading = title
    else:
        body = "\n".join([
            row("/trogiup", "xem tên lệnh theo nhóm"),
            row("/toi", "mở menu nhân vật"),
            row("/san", "săn một trận ở map hiện tại"),
            row("/tui", "mở túi đồ"),
            row("/cho", "mở cửa hàng"),
            row("/bando", "xem và đổi khu vực"),
        ])
        if group:
            note = "Không có nhóm này. Chọn một nhóm bên dưới."
        else:
            note = "Chọn một nhóm để xem lệnh gõ !. Có thể dùng ! hoặc m!."
        heading = "Lệnh dấu /"
    header = blocks(
        row("Trợ giúp", heading),
        body,
        measure("Nhóm", str(len(_HELP_GROUPS))),
        note,
    )
    return _reply(header, header, controls={
        "selects": [{"id": "mx:help", "placeholder": "Chọn nhóm…", "options": options}],
        "buttons": [{"id": "mx:nav:menu", "label": "↩️ Về menu", "style": "secondary", "band": "chan"}],
    }, title="Trợ giúp", menu=True)


def make_recipe(player_id: str, recipe_id: str) -> str:
    result = game.craft_item(player_id, recipe_id, data_store.get_gold(player_id))
    if getattr(result, "ok", False) and getattr(result, "cost", 0):
        data_store.add_gold(player_id, -int(result.cost))
    text = render.render_craft_result(result)
    if getattr(result, "ok", False):
        note = game.complete_task(player_id, "craft")
        if note:
            text += "\n" + note
    return text
