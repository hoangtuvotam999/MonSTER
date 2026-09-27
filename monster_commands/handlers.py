"""Game actions. Each handler returns chat text and never imports a bot library."""
from __future__ import annotations

from monster_game import data_store, game, render, shop

from .context import Command, Ctx, UsageError


def _need(ctx: Ctx) -> str | None:
    if game.get_character(ctx.player_id) is None:
        return "Chưa có nhân vật. Dùng `tao <tên>`."
    return None


def _gold(player_id: str) -> int:
    return data_store.get_gold(player_id)


def _take(player_id: str, amount: int) -> None:
    if amount:
        data_store.add_gold(player_id, -int(amount))


def _give(player_id: str, amount: int) -> None:
    if amount:
        data_store.add_gold(player_id, int(amount))


def _one_int(ctx: Ctx, label: str) -> int:
    if not ctx.args:
        raise UsageError(f"Thiếu {label}.")
    try:
        return int(ctx.args[0])
    except ValueError as exc:
        raise UsageError(f"{label} phải là số.") from exc


def _apply_gold_result(player_id: str, result: dict) -> None:
    shares = result.get("gold_shares")
    if shares:
        for mid, amount in shares.items():
            _give(str(mid), int(amount))
        return
    delta = int(result.get("gold_delta") or 0)
    if delta:
        _give(player_id, delta)


def cmd_help(ctx: Ctx) -> str:
    from .panels import help_reply
    return help_reply(ctx.args[0] if ctx.args else None)


def cmd_tao(ctx: Ctx) -> str:
    if not ctx.args:
        raise UsageError("Đặt tên nhân vật.")
    name = " ".join(ctx.args)[:32]
    created = game.create_character(ctx.player_id, name)
    if created is None:
        return "Bạn đã có nhân vật."
    from .panels import menu_reply
    return menu_reply(ctx.player_id, ctx.channel_id)


def cmd_toi(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    from .panels import menu_reply
    return menu_reply(ctx.player_id, ctx.channel_id)


def cmd_tui(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    from .panels import bag_reply
    return bag_reply(ctx.player_id)


def cmd_trangbi(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    from .panels import gear_reply
    return gear_reply(ctx.player_id)


def cmd_nhatky(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    return render.render_journey(game.journey_log(ctx.player_id, 12))


def cmd_diem(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    if len(ctx.args) < 2:
        raise UsageError("stat <hp|atk|def|spd> <số điểm>")
    stat = ctx.args[0].lower()
    try:
        points = int(ctx.args[1])
    except ValueError as exc:
        raise UsageError("Số điểm không hợp lệ.") from exc
    result = game.spend_points(ctx.player_id, stat, points)
    if result in (data_store.NOT_FOUND, data_store.FORBIDDEN, None):
        return "Không cộng được điểm. Kiểm tra tên chỉ số và số điểm đang có."
    return cmd_toi(ctx)


def cmd_map(ctx: Ctx) -> str:
    from .panels import map_reply
    return map_reply(ctx.player_id)


def cmd_di(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    loc = game.set_location(ctx.player_id, _one_int(ctx, "số map"))
    if loc is None:
        return "Không có map này. Gõ `map` để xem danh sách."
    return f"Đã đến {loc['name']}."


def cmd_san(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    outcome = game.encounter_and_fight(ctx.player_id)
    text = render.render_hunt(outcome)
    if outcome.get("adventure"):
        text += "\nChọn bằng `pick <mã>`."
    from .present import hunt_reply
    return hunt_reply(outcome, text)


def cmd_chon(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    if not ctx.args:
        pending = game.get_pending_adventure(ctx.player_id)
        if not pending:
            return "Không có sự kiện đang chờ."
        from .present import event_reply
        return event_reply(pending)
    result = game.resolve_adventure(ctx.player_id, ctx.args[0])
    payload = result if isinstance(result, dict) else {"ok": False, "reason": "no_event"}
    _apply_gold_result(ctx.player_id, payload)
    text = render.render_adventure_result(payload)
    from .present import choice_reply
    return choice_reply(payload, text)


def cmd_shop(ctx: Ctx) -> str:
    from .panels import shop_reply
    return shop_reply(ctx.player_id)


def cmd_vk(ctx: Ctx) -> str:
    from .panels import shop_list_reply
    category = ctx.args[0] if ctx.args else "Sword"
    category = shop.WEAPON_CATEGORIES.get(str(category), category)
    return shop_list_reply(ctx.player_id, f"w:{category}")


def cmd_muavk(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    if len(ctx.args) < 2:
        raise UsageError("buywpn <loại hoặc 1-6> <số>")
    try:
        index = int(ctx.args[1])
    except ValueError as exc:
        raise UsageError("Số thứ tự vũ khí không hợp lệ.") from exc
    result = shop.purchase_weapon(ctx.player_id, ctx.args[0], index, _gold(ctx.player_id))
    if result.ok:
        _take(ctx.player_id, result.cost)
    return render.render_purchase(result)


def cmd_doan(ctx: Ctx) -> str:
    from .panels import shop_list_reply
    return shop_list_reply(ctx.player_id, "food")


def cmd_muado(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    result = shop.purchase_food(ctx.player_id, _one_int(ctx, "số món"), _gold(ctx.player_id))
    if result.ok:
        _take(ctx.player_id, result.cost)
    return render.render_purchase(result)


def cmd_nangcap(ctx: Ctx) -> str:
    from .panels import shop_list_reply
    return shop_list_reply(ctx.player_id, "stone")


def cmd_muanc(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    result = shop.purchase_upgrade_material(ctx.player_id, _one_int(ctx, "số vật phẩm"), _gold(ctx.player_id))
    if result.ok:
        _take(ctx.player_id, result.cost)
    return render.render_purchase(result)


def cmd_giap(ctx: Ctx) -> str:
    from .panels import shop_list_reply
    slot = ctx.args[0] if ctx.args else ""
    return shop_list_reply(ctx.player_id, f"a:{slot}" if slot else "armor")


def cmd_muagiap(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    if len(ctx.args) < 2:
        raise UsageError("buyarmor <slot> <số>")
    try:
        index = int(ctx.args[1])
    except ValueError as exc:
        raise UsageError("Số thứ tự không hợp lệ.") from exc
    result = shop.purchase_equipment(ctx.player_id, index, _gold(ctx.player_id), slot=ctx.args[0])
    if result.ok:
        _take(ctx.player_id, result.cost)
    return render.render_purchase(result)


def cmd_tieunhao(ctx: Ctx) -> str:
    from .panels import shop_list_reply
    return shop_list_reply(ctx.player_id, "item")


def cmd_muatc(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    result = shop.purchase_consumable(ctx.player_id, _one_int(ctx, "số"), _gold(ctx.player_id))
    if result.ok:
        _take(ctx.player_id, result.cost)
    return render.render_purchase(result)


def cmd_ban(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    count, total = shop.sell_monsters(ctx.player_id, None)
    _give(ctx.player_id, int(total or 0))
    text = render.render_sale(int(count or 0), int(total or 0))
    if count:
        note = game.complete_task(ctx.player_id, "sell")
        if note:
            text += "\n" + note
        daily = game.bump_daily(ctx.player_id, "sell")
        if daily:
            text += "\n" + daily
    return text


def cmd_banvl(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    count, total = shop.sell_materials(ctx.player_id, None)
    _give(ctx.player_id, int(total or 0))
    return render.render_sale(int(count or 0), int(total or 0), "nguyên liệu")


def cmd_mac(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    from .panels import bag_reply, use_text
    result = game.equip_or_consume(ctx.player_id, _one_int(ctx, "ô túi"))
    notice = use_text(result if isinstance(result, dict) else None)
    return bag_reply(ctx.player_id, notice=notice)


def cmd_thaogiap(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    if not ctx.args:
        raise UsageError("unequip <helmet|chest|pants|...>")
    result = game.unequip_gear(ctx.player_id, ctx.args[0])
    if not result:
        return "Không tháo được ô đó."
    return render.render_equipment(game.get_character(ctx.player_id))


def cmd_dai(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    if len(ctx.args) < 2:
        raise UsageError("belt <ô đai 1-5> <ô túi hoặc 0 để bỏ>")
    try:
        belt_slot = int(ctx.args[0])
        bag_index = int(ctx.args[1])
    except ValueError as exc:
        raise UsageError("Hai tham số phải là số.") from exc
    bag = None if bag_index == 0 else bag_index
    result = game.set_belt(ctx.player_id, belt_slot, bag)
    if result is None:
        return "Không gắn được đai."
    return render.render_belt(game.get_character(ctx.player_id))


def cmd_che(ctx: Ctx) -> str:
    return render.render_craft_list(ctx.player_id if game.get_character(ctx.player_id) else None, _gold(ctx.player_id))


def cmd_chetao(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    if not ctx.args:
        raise UsageError("make <mã công thức>")
    result = game.craft_item(ctx.player_id, ctx.args[0], _gold(ctx.player_id))
    if result.ok:
        _take(ctx.player_id, result.cost)
    return render.render_craft_result(result)


def cmd_baogia(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    from .panels import forge_reply
    return forge_reply(ctx.player_id)


def cmd_dap(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    protect = None
    if ctx.args:
        protect = _one_int(ctx, "ô bùa")
    quote = game.enhance_quote(ctx.player_id, "weapon")
    result = game.enhance_item(
        ctx.player_id, "weapon", balance=_gold(ctx.player_id),
        protect_bag_index_1based=protect,
    )
    if result.get("ok"):
        _take(ctx.player_id, result.get("gold_cost") or 0)
    head = render.render_enhance_quote(quote) if quote.get("ok") else ""
    return (head + "\n" + render.render_enhance_result(result)).strip()


def cmd_sua(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    result = game.repair_weapon(ctx.player_id, _gold(ctx.player_id))
    if result.get("ok"):
        _take(ctx.player_id, result["cost"])
    return render.render_repair(result)


def cmd_dungeon(ctx: Ctx) -> str:
    return render.render_dungeon_list()


def cmd_vaodun(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    if not ctx.args:
        raise UsageError("enter <forest_ruin|waste_tomb|elder_vault>")
    result = game.start_dungeon(ctx.player_id, ctx.args[0])
    if not result.get("ok"):
        return render.render_dungeon_result(result)
    return f"🏰 Vào {result.get('dungeon')}. Dùng `tiep` để đi tiếp."


def cmd_tiep(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    action = ctx.args[0] if ctx.args else None
    result = game.advance_dungeon(ctx.player_id, action_id=action)
    _apply_gold_result(ctx.player_id, result if isinstance(result, dict) else {})
    return render.render_dungeon_result(result)


def cmd_rodun(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    return render.render_dungeon_result(game.abandon_dungeon(ctx.player_id))


def cmd_ptao(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    title = " ".join(ctx.args)[:40] if ctx.args else "Tổ đội"
    return render.render_party_action(game.create_party(ctx.channel_id, ctx.player_id, title))


def cmd_pvao(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    return render.render_party_action(game.join_party(ctx.channel_id, ctx.player_id, _one_int(ctx, "số tổ đội")))


def cmd_proi(ctx: Ctx) -> str:
    return render.render_party_action(game.leave_party(ctx.channel_id, ctx.player_id))


def cmd_pds(ctx: Ctx) -> str:
    return render.render_party_list(ctx.channel_id)


def cmd_pdi(ctx: Ctx) -> str:
    result = game.set_party_location(ctx.channel_id, ctx.player_id, _one_int(ctx, "số map"))
    if not result.get("ok"):
        return render.render_party_action(result)
    return f"Tổ đội đến {result['location']['name']}.\n" + render.render_party(result["party"])


def cmd_psan(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    result = game.party_hunt(ctx.channel_id, ctx.player_id)
    text = render.render_party_hunt(result)
    from .present import party_reply
    return party_reply(result, text)


def cmd_pdun(ctx: Ctx) -> str:
    err = _need(ctx)
    if err:
        return err
    if not ctx.args:
        raise UsageError("penter <forest_ruin|waste_tomb|elder_vault>")
    result = game.party_start_dungeon(ctx.channel_id, ctx.player_id, ctx.args[0])
    if not result.get("ok"):
        return render.render_dungeon_result(result)
    return f"🏰 {result.get('party')} vào {result.get('dungeon')}. Dùng `ptiep` để đi tiếp."


def cmd_ptiep(ctx: Ctx) -> str:
    action = ctx.args[0] if ctx.args else None
    result = game.party_advance_dungeon(ctx.channel_id, ctx.player_id, action_id=action)
    _apply_gold_result(ctx.player_id, result if isinstance(result, dict) else {})
    return render.render_dungeon_result(result)


def cmd_proidun(ctx: Ctx) -> str:
    return render.render_dungeon_result(game.party_abandon_dungeon(ctx.channel_id, ctx.player_id))


def cmd_pduoi(ctx: Ctx) -> str:
    if not ctx.args:
        raise UsageError("kick <id người chơi>")
    return render.render_party_action(game.kick_party_member(ctx.channel_id, ctx.player_id, ctx.args[0]))


def cmd_giaipt(ctx: Ctx) -> str:
    return render.render_party_action(game.disband_party(ctx.channel_id, ctx.player_id))


def cmd_pvp(ctx: Ctx) -> str:
    title = " ".join(ctx.args)[:40] if ctx.args else ""
    room = game.create_room(ctx.channel_id, ctx.player_id, title)
    if room is None:
        return "Không tạo được phòng. Cần vũ khí còn bền và chưa ở phòng khác."
    return render.render_rooms(game.list_rooms(ctx.channel_id))


def cmd_pvplist(ctx: Ctx) -> str:
    return render.render_rooms(game.list_rooms(ctx.channel_id))


def cmd_vaopvp(ctx: Ctx) -> str:
    room = game.join_room(ctx.channel_id, ctx.player_id, _one_int(ctx, "số phòng"))
    if room is None:
        return "Không vào được phòng."
    return render.render_rooms(game.list_rooms(ctx.channel_id))


def cmd_sansang(ctx: Ctx) -> str:
    state = game.set_ready(ctx.channel_id, ctx.player_id)
    if state is None:
        return "Chỉ người vào sau mới bấm sẵn sàng, khi phòng đã đủ 2 người."
    return "Đã sẵn sàng." if state else "Đã hủy sẵn sàng."


def cmd_dau(ctx: Ctx) -> str:
    result = game.start_match(ctx.channel_id, ctx.player_id)
    if result is None:
        return "Chưa đấu được. Chủ phòng bắt đầu khi đối thủ đã sẵn sàng."
    return render.render_pvp(result, max_rounds=8)


def cmd_roipvp(ctx: Ctx) -> str:
    if not game.leave_room(ctx.channel_id, ctx.player_id):
        return "Bạn không ở phòng nào, hoặc trận đang diễn ra."
    return render.render_rooms(game.list_rooms(ctx.channel_id))


def _c(name, summary, usage, group, handler, aliases=()):
    return Command(name, summary, usage, group, handler, aliases)


COMMANDS = [
    _c("help", "Danh sách lệnh.", "help [nhóm]", "General", cmd_help, ("trogiup", "lenh")),
    _c("new", "Tạo nhân vật, nhận 2.500 vàng.", "new <tên>", "Hero", cmd_tao, ("tao",)),
    _c("me", "Trạng thái, đai và vàng.", "me", "Hero", cmd_toi, ("toi", "status")),
    _c("bag", "Túi đồ.", "bag", "Hero", cmd_tui, ("tui",)),
    _c("gear", "Giáp đang mặc và đai 5 ô.", "gear", "Hero", cmd_trangbi, ("trangbi",)),
    _c("log", "Nhật ký hành trình.", "log", "Hero", cmd_nhatky, ("nhatky", "journal")),
    _c("stat", "Cộng điểm kỹ năng.", "stat <hp|atk|def|spd> <điểm>", "Hero", cmd_diem, ("cong",)),
    _c("map", "Danh sách khu vực.", "map", "Hunt", cmd_map),
    _c("go", "Đến khu vực theo số.", "go <số>", "Hunt", cmd_di, ("di",)),
    _c("hunt", "Săn một hành trình ở map hiện tại.", "hunt", "Hunt", cmd_san, ("san",)),
    _c("pick", "Chọn hướng sự kiện.", "pick <mã>", "Hunt", cmd_chon, ("chon",)),
    _c("shop", "Menu cửa hàng.", "shop", "Shop", cmd_shop),
    _c("wpn", "Danh sách vũ khí một loại.", "wpn <sword|1-6>", "Shop", cmd_vk, ("vk",)),
    _c("buywpn", "Mua vũ khí.", "buywpn <loại> <số>", "Shop", cmd_muavk, ("muavk",)),
    _c("food", "Danh sách đồ ăn.", "food", "Shop", cmd_doan, ("doan",)),
    _c("buyfood", "Mua đồ ăn.", "buyfood <số>", "Shop", cmd_muado, ("muado",)),
    _c("stone", "Danh sách đá nâng cấp.", "stone", "Shop", cmd_nangcap, ("nangcap",)),
    _c("buystone", "Mua đá nâng cấp.", "buystone <số>", "Shop", cmd_muanc, ("muanc",)),
    _c("armor", "Cửa hàng giáp.", "armor [helmet|chest|...]", "Shop", cmd_giap, ("giap",)),
    _c("buyarmor", "Mua giáp.", "buyarmor <slot> <số>", "Shop", cmd_muagiap, ("muagiap",)),
    _c("item", "Cửa hàng tiêu hao, bùa, charm.", "item", "Shop", cmd_tieunhao, ("tieunhao",)),
    _c("buyitem", "Mua tiêu hao.", "buyitem <số>", "Shop", cmd_muatc, ("muatc",)),
    _c("sell", "Bán hết chiến lợi phẩm.", "sell", "Shop", cmd_ban, ("ban",)),
    _c("sellmat", "Bán hết nguyên liệu.", "sellmat", "Shop", cmd_banvl, ("banvl",)),
    _c("use", "Dùng ô túi. Bình máu sẽ vào đai, giữ số lượng.", "use <ô túi>", "Gear", cmd_mac, ("mac",)),
    _c("unequip", "Tháo một ô giáp.", "unequip <slot>", "Gear", cmd_thaogiap, ("thaogiap",)),
    _c("belt", "Gắn cả chồng tiêu hao vào đai. 0 là tháo.", "belt <1-5> <ô túi|0>", "Gear", cmd_dai, ("dai",)),
    _c("craft", "Công thức chế tạo.", "craft", "Craft", cmd_che, ("che",)),
    _c("make", "Chế một công thức.", "make <mã>", "Craft", cmd_chetao, ("chetao",)),
    _c("quote", "Xem giá và tỉ lệ cường hóa.", "quote", "Forge", cmd_baogia, ("baogia",)),
    _c("forge", "Cường hóa vũ khí. Có thể kèm ô bùa.", "forge [ô bùa]", "Forge", cmd_dap, ("dap",)),
    _c("repair", "Sửa vũ khí đang mặc.", "repair", "Forge", cmd_sua, ("sua",)),
    _c("dungeon", "Danh sách dungeon.", "dungeon", "Dungeon", cmd_dungeon),
    _c("enter", "Vào dungeon một mình.", "enter <mã>", "Dungeon", cmd_vaodun, ("vaodun",)),
    _c("next", "Đi tiếp một phòng dungeon.", "next [mã]", "Dungeon", cmd_tiep, ("tiep",)),
    _c("abort", "Rút khỏi dungeon.", "abort", "Dungeon", cmd_rodun, ("rodun",)),
    _c("parties", "Danh sách tổ đội.", "parties", "Party", cmd_pds, ("pds",)),
    _c("pnew", "Lập tổ đội trong kênh này.", "pnew [tên]", "Party", cmd_ptao, ("ptao",)),
    _c("join", "Vào tổ đội.", "join <số>", "Party", cmd_pvao, ("pvao",)),
    _c("leave", "Rời tổ đội.", "leave", "Party", cmd_proi, ("proi",)),
    _c("pgo", "Đội trưởng chọn map.", "pgo <số map>", "Party", cmd_pdi, ("pdi",)),
    _c("phunt", "Săn chung. Có nhật ký và hành trình.", "phunt", "Party", cmd_psan, ("psan",)),
    _c("penter", "Cả đội vào dungeon.", "penter <mã>", "Party", cmd_pdun, ("pdun",)),
    _c("pnext", "Đội trưởng đi tiếp phòng.", "pnext [mã]", "Party", cmd_ptiep, ("ptiep",)),
    _c("pleave", "Cả đội rút khỏi dungeon.", "pleave", "Party", cmd_proidun, ("proidun",)),
    _c("kick", "Đội trưởng đuổi thành viên.", "kick <id>", "Party", cmd_pduoi, ("pduoi",)),
    _c("disband", "Đội trưởng giải tán.", "disband", "Party", cmd_giaipt, ("giaipt",)),
    _c("pvp", "Tạo phòng đấu.", "pvp [tên phòng]", "PvP", cmd_pvp),
    _c("rooms", "Các phòng đấu trong kênh.", "rooms", "PvP", cmd_pvplist, ("pvplist",)),
    _c("pvpjoin", "Vào phòng đấu.", "pvpjoin <số>", "PvP", cmd_vaopvp, ("vaopvp",)),
    _c("ready", "Người vào sau bấm sẵn sàng.", "ready", "PvP", cmd_sansang, ("sansang",)),
    _c("fight", "Chủ phòng bắt đầu trận.", "fight", "PvP", cmd_dau, ("dau",)),
    _c("pvpexit", "Rời phòng đấu.", "pvpexit", "PvP", cmd_roipvp, ("roipvp",)),
]
