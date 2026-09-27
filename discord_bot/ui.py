"""Discord select menus, buttons, and modals. Game rules stay outside this file."""
from __future__ import annotations

import asyncio
import secrets
import time

import discord
from discord.ui import ActionRow, Button, Container, LayoutView, Section, Select, Separator, TextDisplay, View

from monster_commands.context import Reply
from monster_commands.present import RULE
from monster_commands.panels import (
    bag_reply,
    buy_amount,
    forge_reply,
    gear_reply,
    make_recipe,
    dungeon_reply,
    map_reply,
    help_reply,
    menu_reply,
    party_menu_reply,
    pvp_menu_reply,
    shop_list_reply,
    shop_reply,
    use_text,
    weapon_menu_reply,
)
from monster_game import data_store, game, render

_LOGS: dict[str, list[str]] = {}
_LIVE: dict[int, View | LayoutView] = {}
_SWEEPER: asyncio.Task | None = None
BUTTON_LIFE = 8 * 60
TEXT_BUDGET = 3700

STYLES = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}


def _stamp(view) -> None:
    view.message = None
    view.settled = False
    view.deadline = time.monotonic() + BUTTON_LIFE


class PanelView(View):
    """Classic components under an embed. Used for the hunt log button."""

    def __init__(self):
        super().__init__(timeout=BUTTON_LIFE)
        _stamp(self)

    def halt(self) -> None:
        self.settled = True
        if not self.is_finished():
            self.stop()

    def attach(self, message: discord.Message) -> None:
        _attach(self, message)

    async def on_timeout(self) -> None:
        await expire(self)


class Board(LayoutView):
    """Text rows with the button on the right of the row, plus divider lines."""

    def __init__(self):
        super().__init__(timeout=BUTTON_LIFE)
        _stamp(self)

    def halt(self) -> None:
        self.settled = True
        if not self.is_finished():
            self.stop()

    def attach(self, message: discord.Message) -> None:
        _attach(self, message)

    async def on_timeout(self) -> None:
        await expire(self)


def _attach(view, message: discord.Message) -> None:
    view.message = message
    previous = _LIVE.get(message.id)
    if previous is not None and previous is not self_view(view):
        previous.halt()
    _LIVE[message.id] = view


def self_view(view):
    return view


def remember(view, message) -> None:
    if view is not None and message is not None and hasattr(view, "attach"):
        view.attach(message)


def _release(panel, message) -> None:
    """Stop an old panel so its timer cannot overwrite the message we are about to replace."""
    if panel is None or not hasattr(panel, "halt"):
        return
    panel.halt()
    if message is not None and _LIVE.get(message.id) is panel:
        _LIVE.pop(message.id, None)


def _disable(view) -> None:
    for child in view.walk_children():
        if isinstance(child, (Button, Select)):
            child.disabled = True


async def expire(view) -> None:
    if getattr(view, "settled", False):
        return
    view.settled = True
    _disable(view)
    message = getattr(view, "message", None)
    if message is not None and _LIVE.get(message.id) is view:
        _LIVE.pop(message.id, None)
    if hasattr(view, "stop") and not view.is_finished():
        view.stop()
    if message is None:
        return
    try:
        await message.edit(view=view)
    except discord.HTTPException as exc:
        print(f"button expire failed: {exc}", flush=True)


async def expire_loop() -> None:
    while True:
        await asyncio.sleep(20)
        now = time.monotonic()
        for message_id, panel in list(_LIVE.items()):
            if getattr(panel, "settled", False):
                continue
            if now < getattr(panel, "deadline", now + 1):
                continue
            if _LIVE.get(message_id) is not panel:
                continue
            await expire(panel)


def start_sweeper() -> None:
    global _SWEEPER
    if _SWEEPER is not None and not _SWEEPER.done():
        return
    _SWEEPER = asyncio.get_running_loop().create_task(expire_loop())


class QtyModal(discord.ui.Modal, title="Số lượng mua"):
    amount = discord.ui.TextInput(label="Số lượng từ 1 đến 20", default="1", max_length=2)

    def __init__(self, catalog: str, index: int):
        super().__init__()
        self.catalog = catalog
        self.index = index

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(str(self.amount.value).strip())
        except ValueError:
            await interaction.response.send_message("Nhập một số.", ephemeral=True)
            return
        notice = buy_amount(str(interaction.user.id), self.catalog, self.index, qty)
        reply = shop_list_reply(str(interaction.user.id), self.catalog, notice)
        _release(None, None)
        await edit_current(interaction, reply, interaction.user.id)


class StatModal(discord.ui.Modal, title="Cộng điểm kỹ năng"):
    stat = discord.ui.TextInput(label="Chỉ số: hp, atk, def hoặc spd", default="atk", max_length=4)
    amount = discord.ui.TextInput(label="Số điểm", default="1", max_length=4)

    async def on_submit(self, interaction: discord.Interaction):
        from monster_commands import dispatch
        stat = self.stat.value.strip().lower()
        amount = self.amount.value.strip()
        reply = dispatch(str(interaction.user.id), str(interaction.channel_id), f"stat {stat} {amount}")
        title = (getattr(reply, "view", None) or {}).get("title")
        if title == "Menu":
            note = f"Đã cộng {amount} điểm vào {stat}."
        else:
            note = (getattr(reply, "text", None) or "Không cộng được điểm.")[:300]
        fresh = menu_reply(str(interaction.user.id), str(interaction.channel_id), notice=note)
        await edit_current(interaction, fresh, interaction.user.id)


def is_menu(reply) -> bool:
    return bool((getattr(reply, "view", None) or {}).get("menu"))


def wants_board(reply) -> bool:
    if is_menu(reply):
        return False
    if list(getattr(reply, "story", None) or []):
        return False
    if (getattr(reply, "view", None) or {}).get("companion"):
        return False
    controls = getattr(reply, "controls", None) or {}
    view = getattr(reply, "view", None) or {}
    return bool(controls.get("buttons") or controls.get("selects") or view.get("fields"))


def companion_reply(payload: dict) -> Reply:
    return Reply(
        text=payload.get("header") or "",
        view={
            "color": payload.get("color"),
            "title": payload.get("title") or "Sự kiện",
            "header": payload.get("header") or "",
            "fields": [] if payload.get("menu") else (payload.get("fields") or []),
            "author": payload.get("author") or "",
            "menu": True,
        },
        controls=payload.get("controls"),
    )


def _clip_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_log_view(reply, owner_id: int) -> PanelView | None:
    story = list(getattr(reply, "story", None) or [])
    if len(story) <= 4:
        return None
    token = secrets.token_hex(4)
    _LOGS[token] = story
    while len(_LOGS) > 30:
        _LOGS.pop(next(iter(_LOGS)))
    view = PanelView()
    view.add_item(ActionButton(
        {"id": f"mx:log:{token}", "label": "Xem hết diễn biến", "style": "secondary"},
        owner_id,
    ))
    return view


def _band_rule(caption: str = "") -> str:
    """Blank line, then the bar. The next control sits against the bar."""
    text = f"\n\n{RULE}"
    if caption:
        text += f"\n{caption}"
    return text


def build_menu_view(reply, owner_id: int) -> Board:
    """Card with one rule between bands. Plain buttons sit two on a row. A hinted button is its own wide row under that text."""
    payload = getattr(reply, "view", None) or {}
    controls = dict(getattr(reply, "controls", None) or {})
    board = Board()
    box = Container(accent_colour=int(payload.get("color") or 5793266))
    title = payload.get("title") or "Menu"
    header = payload.get("header") or getattr(reply, "text", None) or "…"
    author = payload.get("author") or ""
    opening = f"**{title}**"
    if author:
        opening += f"\n{author}"
    opening += f"\n{header}"
    box.add_item(TextDisplay(_clip_text(opening, 2800)))

    selects = [dict(spec) for spec in (controls.get("selects") or []) if spec.get("options")]
    for spec in selects:
        row = ActionRow()
        row.add_item(ActionSelect(spec, owner_id))
        box.add_item(row)

    buttons = [dict(spec) for spec in (controls.get("buttons") or [])]
    pending: list[dict] = []
    current_band = None
    started = False

    def flush_row() -> None:
        if not pending:
            return
        row = ActionRow()
        for spec in pending:
            row.add_item(ActionButton(spec, owner_id))
        box.add_item(row)
        pending.clear()

    def place_wide(spec: dict) -> None:
        hint = (spec.get("hint") or "").strip()
        if hint:
            box.add_item(TextDisplay(_clip_text(hint, 300)))
        row = ActionRow()
        row.add_item(ActionButton(spec, owner_id))
        box.add_item(row)

    for spec in buttons:
        band = spec.get("band") or ""
        if not started or band != current_band:
            flush_row()
            caption = (spec.get("caption") or "").strip()
            box.add_item(TextDisplay(_clip_text(_band_rule(caption), 500)))
            current_band = band
            started = True
        if spec.get("stack") or (spec.get("hint") or "").strip():
            flush_row()
            place_wide(spec)
            continue
        pending.append(spec)
        width = 3 if current_band in ("viec", "ngay") else 2
        if len(pending) == width:
            flush_row()
    flush_row()
    board.add_item(box)
    return board


def build_board(reply, owner_id: int) -> Board:
    view = getattr(reply, "view", None) or {}
    controls = dict(getattr(reply, "controls", None) or {})
    buttons = [dict(spec) for spec in (controls.get("buttons") or [])]
    by_label = {spec.get("label"): spec for spec in buttons}
    used: set[str] = set()
    board = Board()
    box = Container(accent_colour=int(view.get("color") or 5793266))
    budget = {"chars": 0, "parts": 1}

    def room() -> int:
        return TEXT_BUDGET - budget["chars"]

    def add_text(content: str) -> None:
        content = (content or "").strip()
        if not content or budget["parts"] >= 34 or room() < 24:
            return
        content = _clip_text(content, min(900, room()))
        budget["chars"] += len(content)
        budget["parts"] += 1
        box.add_item(TextDisplay(content))

    def add_section(content: str, spec: dict) -> None:
        content = (content or spec.get("label") or "Chọn").strip()
        if budget["parts"] + 3 > 36 or room() < 12:
            return
        content = _clip_text(content, min(280, room()))
        budget["chars"] += len(content)
        budget["parts"] += 3
        box.add_item(Section(content, accessory=ActionButton(spec, owner_id)))

    title = view.get("title") or "MonSTER"
    header = view.get("header") or getattr(reply, "text", None) or "…"
    author = view.get("author") or ""
    opening = f"**{title}**"
    if author:
        opening += f"\n{author}"
    opening += f"\n{_clip_text(header, 900)}"
    add_text(opening)

    for spec in controls.get("selects") or []:
        if not spec.get("options") or budget["parts"] + 2 > 36:
            continue
        row = ActionRow()
        row.add_item(ActionSelect(dict(spec), owner_id))
        budget["parts"] += 2
        box.add_item(row)

    for raw in view.get("fields") or []:
        name = str(raw.get("name") or "—")
        value = str(raw.get("value") or "").strip()
        value = "\n".join(line for line in value.splitlines() if set(line.strip()) != {"━"})
        action = raw.get("action")
        if name.startswith("▣"):
            if budget["parts"] < 34:
                box.add_item(Separator(spacing=discord.enums.SeparatorSpacing.large))
                budget["parts"] += 1
            add_text(f"**{name}**" + (f"\n{value}" if value else ""))
            continue
        spec = by_label.get(action) if action else None
        if spec is not None:
            used.add(spec.get("label"))
            add_section(f"**{name}**\n{value}" if value else f"**{name}**", spec)
        else:
            add_text(f"**{name}**\n{value}" if value else f"**{name}**")

    for spec in buttons:
        if spec.get("label") in used:
            continue
        add_section(f"**{spec.get('label')}**", spec)

    if budget["parts"] <= 1:
        add_text("…")
    board.add_item(box)
    return board


def _shown(reply) -> tuple[list[str], bool]:
    story = list(getattr(reply, "story", None) or [])
    shown = story[:3]
    final = not story or len(story) <= 3
    return shown, final


async def _send_hunt(send, reply, owner_id: int):
    """Post the fight log, then the choice rows as their own message."""
    from discord_bot.bot import build_embeds, play_story
    shown, final = _shown(reply)
    log_view = build_log_view(reply, owner_id)
    first = {"embeds": build_embeds(reply, shown, final=final), "wait": True}
    if log_view is not None:
        first["view"] = log_view
    message = await send(**first)
    remember(log_view, message)
    companion = (getattr(reply, "view", None) or {}).get("companion")
    if companion:
        choice_view = build_menu_view(companion_reply(companion), owner_id)
        choice = await send(view=choice_view, wait=True)
        remember(choice_view, choice)
    if reply.story and len(reply.story) > 3:
        await play_story(message.edit, reply)


async def deliver_prefix(ctx, reply) -> None:
    from discord_bot.bot import build_embeds
    owner = ctx.author.id
    companion = (getattr(reply, "view", None) or {}).get("companion")
    if list(getattr(reply, "story", None) or []) or companion:
        await _send_hunt(lambda **kwargs: ctx.send(**{k: v for k, v in kwargs.items() if k != "wait"}), reply, owner)
        return
    if is_menu(reply):
        view = build_menu_view(reply, owner)
        remember(view, await ctx.send(view=view))
        return
    if wants_board(reply):
        board = build_board(reply, owner)
        remember(board, await ctx.send(view=board))
        return
    await ctx.send(embeds=build_embeds(reply, [], final=True))


async def deliver_slash(interaction: discord.Interaction, reply) -> None:
    from discord_bot.bot import build_embeds, play_story
    owner = interaction.user.id
    companion = (getattr(reply, "view", None) or {}).get("companion")
    story = list(getattr(reply, "story", None) or [])
    if story or companion:
        shown, final = _shown(reply)
        log_view = build_log_view(reply, owner)
        await interaction.response.send_message(
            embeds=build_embeds(reply, shown, final=final),
            view=log_view,
        )
        message = await interaction.original_response()
        remember(log_view, message)
        if companion:
            choice_view = build_menu_view(companion_reply(companion), owner)
            remember(choice_view, await interaction.followup.send(view=choice_view, wait=True))
        if len(story) > 3:
            await play_story(message.edit, reply)
        return
    if is_menu(reply):
        view = build_menu_view(reply, owner)
        await interaction.response.send_message(view=view)
        remember(view, await interaction.original_response())
        return
    if wants_board(reply):
        board = build_board(reply, owner)
        await interaction.response.send_message(view=board)
        remember(board, await interaction.original_response())
        return
    await interaction.response.send_message(embeds=build_embeds(reply, [], final=True))


async def edit_current(interaction: discord.Interaction, reply, owner_id: int) -> None:
    """Replace the panel in place. Hunt logs are never edited from here."""
    from discord_bot.bot import build_embeds
    message = interaction.message
    v2 = bool(message and message.flags.components_v2)
    if is_menu(reply):
        view = build_menu_view(reply, owner_id)
        if v2:
            await interaction.response.edit_message(view=view)
        else:
            await interaction.response.edit_message(content=None, embeds=[], attachments=[], view=view)
        remember(view, message)
        return
    board = build_board(reply, owner_id) if wants_board(reply) or v2 else None
    if board is None:
        await interaction.response.edit_message(embeds=build_embeds(reply, [], final=True), view=None)
        return
    if v2:
        await interaction.response.edit_message(view=board)
    else:
        await interaction.response.edit_message(content=None, embeds=[], attachments=[], view=board)
    remember(board, message)


async def _apply(interaction: discord.Interaction, custom_id: str, value: str | None, owner_id: int, panel=None):
    if interaction.user.id != owner_id:
        await interaction.response.send_message("Bảng này của người khác.", ephemeral=True)
        return
    player = str(interaction.user.id)
    channel = str(interaction.channel_id)
    cid = custom_id

    if cid.startswith("mx:log:"):
        lines = _LOGS.get(cid.split("mx:log:", 1)[1], [])
        if not lines:
            await interaction.response.send_message("Diễn biến này không còn.", ephemeral=True)
            return
        chunks: list[str] = []
        buf: list[str] = []
        size = 0
        for line in lines:
            if buf and size + len(line) > 1600:
                chunks.append("\n".join(buf))
                buf, size = [], 0
            buf.append(line)
            size += len(line) + 1
        if buf:
            chunks.append("\n".join(buf))
        embeds = [
            discord.Embed(title=f"Diễn biến {i}/{len(chunks[:10])}", description=f"```\n{chunk[:3500]}\n```")
            for i, chunk in enumerate(chunks[:10], start=1)
        ]
        await interaction.response.send_message(embeds=embeds, ephemeral=True)
        return

    if cid.startswith("mx:pick:"):
        _release(panel, interaction.message)
        from monster_commands import dispatch
        reply = dispatch(player, channel, f"pick {cid.split(':', 2)[2]}")
        await edit_current(interaction, reply, interaction.user.id)
        return

    if cid.startswith("mx:buy:") and value and value.startswith("q:"):
        catalog = cid.split("mx:buy:", 1)[1]
        await interaction.response.send_modal(QtyModal(catalog, int(value[2:])))
        return
    if cid == "mx:stat":
        await interaction.response.send_modal(StatModal())
        return

    if cid in ("mx:nav:hunt", "mx:party:hunt", "mx:daily:hunt"):
        await interaction.response.defer()
        line = "phunt" if cid == "mx:party:hunt" else "hunt"
        reply = __import__("monster_commands", fromlist=["dispatch"]).dispatch(player, channel, line)
        await _send_hunt(interaction.followup.send, reply, interaction.user.id)
        return

    _release(panel, interaction.message)

    notice = ""
    reply = None
    if cid.startswith("mx:bagk:"):
        reply = bag_reply(player, 0, notice, cid.split(":")[2], "all")
    elif cid.startswith("mx:bagt:"):
        kind = cid.split(":")[2]
        reply = bag_reply(player, 0, notice, kind, value or "all")
    elif cid.startswith("mx:bag"):
        parts = cid.split(":")
        if len(parts) >= 5:
            kind, tier, page = parts[2], parts[3], int(parts[4] or 0)
        else:
            kind, tier, page = "all", "all", int(parts[-1] or 0)
        if value:
            used = game.equip_or_consume(player, int(value))
            if isinstance(used, dict) and used.get("action") == "equip_gear":
                notice = use_text({"ok": True, "action": "equip_gear", "name": "trang bị"})
            else:
                notice = use_text(used if isinstance(used, dict) else None)
        reply = bag_reply(player, page, notice, kind, tier)
    elif cid.startswith("mx:page:"):
        parts = cid.split(":")
        if len(parts) >= 5:
            reply = bag_reply(player, int(parts[4] or 0), "", parts[2], parts[3])
        else:
            reply = bag_reply(player, int(parts[-1] or 0))
    elif cid == "mx:help" and value:
        reply = help_reply(value)
    elif cid == "mx:shop" and value == "weapons":
        reply = weapon_menu_reply(player)
    elif cid == "mx:shop" and value == "forge":
        reply = forge_reply(player)
    elif cid == "mx:shop" and value:
        reply = shop_list_reply(player, value)
    elif cid == "mx:wcat" and value:
        reply = shop_list_reply(player, f"w:{value}")
    elif cid in ("mx:forge:open",):
        reply = forge_reply(player)
    elif cid == "mx:forge" and value:
        protect = int(value[2:]) if value.startswith("p:") else None
        luck = [int(value[2:])] if value.startswith("l:") else None
        result = game.enhance_item(
            player, "weapon", balance=data_store.get_gold(player),
            protect_bag_index_1based=protect, luck_bag_indices_1based=luck,
        )
        if result.get("ok") and result.get("gold_cost"):
            data_store.add_gold(player, -int(result["gold_cost"]))
        reply = forge_reply(player, render.render_enhance_result(result))
    elif cid == "mx:stones":
        reply = shop_list_reply(player, "stone")
    elif cid == "mx:repair":
        result = game.repair_weapon(player, data_store.get_gold(player))
        if result.get("ok"):
            data_store.add_gold(player, -int(result.get("cost") or 0))
        reply = forge_reply(player, render.render_repair(result))
    elif cid.startswith("mx:buy:") and value and value.startswith("b:"):
        catalog = cid.split("mx:buy:", 1)[1]
        notice = buy_amount(player, catalog, int(value[2:]), 1)
        reply = shop_list_reply(player, catalog, notice)
    elif cid == "mx:aslot" and value:
        reply = shop_list_reply(player, f"a:{value}")
    elif cid == "mx:make" and value:
        notice = make_recipe(player, value)
        reply = shop_list_reply(player, "craft", notice)
    elif cid == "mx:go" and value:
        loc = game.set_location(player, int(value))
        notice = f"Đã đến {loc['name']}." if loc else "Không có map này."
        reply = map_reply(player, notice)
    elif cid == "mx:belt" and value:
        kind, _, slot = value.partition(":")
        if kind == "drink":
            notice = use_text(game.drink_belt(player, int(slot)))
        else:
            notice = "Món này chờ đến trận đánh."
        reply = gear_reply(player, notice)
    elif cid == "mx:statall" and value:
        names = {"hp": "máu", "atk": "đòn", "def": "đỡ", "spd": "tốc"}
        user = game.get_character(player) or {}
        amount = int(user.get("points") or 0)
        result = game.spend_points(player, value, amount)
        if amount <= 0:
            notice = "Không còn điểm để cộng."
        elif result in (data_store.NOT_FOUND, data_store.FORBIDDEN, None):
            notice = "Không cộng được điểm này."
        else:
            notice = f"Đã cộng hết {amount} điểm vào {names.get(value, value)}."
        reply = menu_reply(player, channel, notice)
    elif cid.startswith("mx:stat:"):
        stat = cid.rsplit(":", 1)[-1]
        names = {"hp": "máu", "atk": "đòn", "def": "đỡ", "spd": "tốc"}
        result = game.spend_points(player, stat, 1)
        if result in (data_store.NOT_FOUND, data_store.FORBIDDEN, None):
            notice = "Không cộng được điểm này."
        else:
            notice = f"Đã cộng 1 điểm vào {names.get(stat, stat)}."
        reply = menu_reply(player, channel, notice)
    elif cid == "mx:daily:done":
        reply = menu_reply(player, channel, "Hôm nay đã xong việc ngày. Mai có việc mới.")
    elif cid == "mx:daily:sell":
        from monster_commands import dispatch
        reply = menu_reply(player, channel, dispatch(player, channel, "sell").text)
    elif cid == "mx:daily:rest":
        result = game.rest_character(player)
        reply = menu_reply(player, channel, result.get("message") or "Không nghỉ được.")
    elif cid == "mx:task:sell":
        from monster_commands import dispatch
        reply = menu_reply(player, channel, dispatch(player, channel, "sell").text)
    elif cid == "mx:task:craft":
        reply = shop_list_reply(player, "craft")
    elif cid == "mx:task:dungeon":
        reply = dungeon_reply(player)
    elif cid == "mx:sell":
        from monster_commands import dispatch
        reply = bag_reply(player, 0, dispatch(player, channel, "sell").text)
    elif cid == "mx:sellmat":
        from monster_commands import dispatch
        reply = bag_reply(player, 0, dispatch(player, channel, "sellmat").text)
    elif cid == "mx:back":
        reply = shop_reply(player)
    elif cid == "mx:nav:bag":
        reply = bag_reply(player)
    elif cid == "mx:nav:shop":
        reply = shop_reply(player)
    elif cid == "mx:nav:map":
        reply = map_reply(player)
    elif cid == "mx:nav:gear":
        reply = gear_reply(player)
    elif cid == "mx:nav:rest":
        result = game.rest_character(player)
        reply = menu_reply(player, channel, result.get("message") or "Không nghỉ được.")
    elif cid == "mx:nav:menu" or cid == "mx:nav:me":
        reply = menu_reply(player, channel)
    elif cid == "mx:nav:event":
        from monster_commands.present import event_reply
        pending = game.get_pending_adventure(player)
        reply = event_reply(pending) if pending else menu_reply(player, channel, "Không có sự kiện đang chờ.")
    elif cid == "mx:nav:dungeon":
        reply = dungeon_reply(player)
    elif cid.startswith("mx:dun:"):
        result = game.start_dungeon(player, cid.split("mx:dun:", 1)[1])
        text = render.render_dungeon_result(result)
        if isinstance(result, dict) and result.get("task_note"):
            text += "\n" + result["task_note"]
        reply = dungeon_reply(player, text)
    elif cid == "mx:dnext":
        result = game.advance_dungeon(player)
        reply = dungeon_reply(player, render.render_dungeon_result(result))
    elif cid.startswith("mx:dact:"):
        result = game.advance_dungeon(player, action_id=cid.split("mx:dact:", 1)[1])
        reply = dungeon_reply(player, render.render_dungeon_result(result))
    elif cid == "mx:dabort":
        result = game.abandon_dungeon(player)
        reply = dungeon_reply(player, render.render_dungeon_result(result))
    elif cid == "mx:nav:party":
        reply = party_menu_reply(player, channel)
    elif cid == "mx:party:new":
        result = game.create_party(channel, player, "Tổ đội")
        reply = party_menu_reply(player, channel, render.render_party_action(result))
    elif cid == "mx:pjoin" and value:
        result = game.join_party(channel, player, int(value))
        reply = party_menu_reply(player, channel, render.render_party_action(result))
    elif cid == "mx:party:leave":
        result = game.leave_party(channel, player)
        reply = party_menu_reply(player, channel, render.render_party_action(result))
    elif cid == "mx:nav:pvp":
        reply = pvp_menu_reply(player, channel)
    elif cid == "mx:pvp:new":
        room = game.create_room(channel, player, "Phòng đấu")
        notice = "Đã tạo phòng." if room else "Không tạo được phòng. Cần vũ khí còn bền và chưa ở phòng khác."
        reply = pvp_menu_reply(player, channel, notice)
    elif cid == "mx:pvpjoin" and value:
        room = game.join_room(channel, player, int(value))
        reply = pvp_menu_reply(player, channel, "Đã vào phòng." if room else "Không vào được phòng.")
    elif cid == "mx:pvp:ready":
        state = game.set_ready(channel, player)
        if state is None:
            notice = "Chỉ người vào sau mới bấm sẵn sàng, khi phòng đã đủ 2 người."
        else:
            notice = "Đã sẵn sàng." if state else "Đã hủy sẵn sàng."
        reply = pvp_menu_reply(player, channel, notice)
    elif cid == "mx:pvp:fight":
        result = game.start_match(channel, player)
        notice = render.render_pvp(result, max_rounds=8) if result else "Chưa đấu được. Chủ phòng bắt đầu khi đối thủ đã sẵn sàng."
        reply = pvp_menu_reply(player, channel, notice[:800])
    elif cid == "mx:pvp:leave":
        ok = game.leave_room(channel, player)
        reply = pvp_menu_reply(player, channel, "Đã rời phòng." if ok else "Không rời được.")
    else:
        await interaction.response.send_message("Nút này chưa gắn.", ephemeral=True)
        return

    await edit_current(interaction, reply, interaction.user.id)


class ActionSelect(Select):
    def __init__(self, spec: dict, owner_id: int):
        options = [
            discord.SelectOption(
                label=opt["label"][:100],
                value=opt["value"][:100],
                description=((opt.get("description") or "")[:100] or None),
            )
            for opt in spec["options"][:25]
        ]
        super().__init__(
            placeholder=(spec.get("placeholder") or "Chọn")[:150],
            options=options,
            custom_id=spec["id"][:100],
            min_values=1,
            max_values=1,
            row=spec.get("row"),
        )
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        await _apply(interaction, self.custom_id, self.values[0], self.owner_id, self.view)


class ActionButton(Button):
    def __init__(self, spec: dict, owner_id: int):
        super().__init__(
            label=spec["label"][:80],
            style=STYLES.get(spec.get("style") or "secondary", discord.ButtonStyle.secondary),
            custom_id=spec["id"][:100],
            row=spec.get("row"),
        )
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        await _apply(interaction, self.custom_id, None, self.owner_id, self.view)
