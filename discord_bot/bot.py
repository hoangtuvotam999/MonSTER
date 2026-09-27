"""
Discord foundation for MonSTER.

Prefix (`!` / `m!`) and slash commands both call `monster_commands.dispatch`.
This process does not implement game rules.

Token: environment variable DISCORD_TOKEN only.
Run:   DISCORD_TOKEN=... python -m discord_bot
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from monster_commands import dispatch, list_commands
from monster_commands.context import Reply
from monster_game import data_store

TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
PREFIXES = ("!", "m!")
MENTION_RE = re.compile(r"<@!?(\d+)>")


def _normalize(content: str) -> str:
    return MENTION_RE.sub(r"\1", content).strip()


def _window(lines: list[str], limit: int = 2200) -> str:
    """Keep the latest beats inside a code block so a long fight stays readable."""
    if not lines:
        return ""
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        extra = len(line) + 1
        if kept and total + extra > limit:
            break
        kept.append(line)
        total += extra
    kept.reverse()
    skipped = len(lines) - len(kept)
    body = "\n".join(kept)
    if skipped:
        body = f"… {skipped} nhịp trước được lược, nếu không khối chữ sẽ vỡ.\n" + body
    return f"```ini\n{body}\n```"


def _one_embed(payload: dict, *, fallback_title: str) -> discord.Embed:
    description = (payload.get("description") or payload.get("header") or "…")[:3500]
    embed = discord.Embed(
        title=(payload.get("title") or fallback_title)[:256],
        description=description or "…",
        color=int(payload.get("color") or 4321431),
        timestamp=datetime.now(timezone.utc),
    )
    author = payload.get("author") or ""
    if author:
        embed.set_author(name=str(author)[:256])
    for field in payload.get("fields") or []:
        value = str(field.get("value") or "").strip()
        if not value:
            continue
        embed.add_field(
            name=str(field.get("name") or "—")[:256],
            value=value[:1024],
            inline=bool(field.get("inline")),
        )
    return embed


def _embed(reply: Reply, shown: list[str], *, final: bool) -> discord.Embed:
    return build_embeds(reply, shown, final=final)[0]


def build_embed(reply: Reply, shown: list[str], *, final: bool) -> discord.Embed:
    return _embed(reply, shown, final=final)


def build_embeds(reply: Reply, shown: list[str], *, final: bool) -> list[discord.Embed]:
    """Combat stays on the first embed. Loot and journey ride in their own embeds."""
    view = reply.view or {}
    header = view.get("header") or reply.text or "…"
    if reply.story:
        block = _window(shown)
        description = f"{header}\n\n{block}".strip() if block else header
    else:
        description = header
    main = _one_embed({
        "title": view.get("title") or "MonSTER",
        "description": description,
        "color": view.get("color"),
        "author": view.get("author"),
        "fields": view.get("fields") or [],
    }, fallback_title="MonSTER")
    embeds = [main]
    if final:
        for extra in view.get("extras") or []:
            embeds.append(_one_embed(extra, fallback_title="Chi tiết"))
    # Discord rejects a message once the combined text passes 6000 characters.
    kept = []
    total = 0
    for embed in embeds:
        weight = len(embed.title or "") + len(embed.description or "")
        weight += sum(len(f.name) + len(f.value) for f in embed.fields)
        if kept and total + weight > 5500:
            break
        total += weight
        kept.append(embed)
    return kept or [discord.Embed(title="MonSTER", description="…")]


async def play_story(edit, reply: Reply, view=None, already: int = 3) -> None:
    """Animate the hunt log. Edits embeds only, so the log button and the choice message stay."""
    del view  # story frames must not replace components; that was wiping the log and the timer
    story = list(reply.story or [])
    if len(story) <= already:
        return
    shown = story[:already]
    steps = 0
    for line in story[already:]:
        shown.append(line)
        due = len(shown) % 3 == 0 or line is story[-1]
        if not due:
            continue
        steps += 1
        if steps > 8 and line is not story[-1]:
            continue
        await asyncio.sleep(1.05)
        try:
            await edit(embeds=build_embeds(reply, shown, final=line is story[-1]))
        except discord.HTTPException as exc:
            print(f"embed edit failed: {exc}", flush=True)
            return


def _prefix_callback(name: str):
    async def _run(ctx: commands.Context, *args: str):
        line = name if not args else name + " " + " ".join(args)
        reply = dispatch(str(ctx.author.id), str(ctx.channel.id), _normalize(line))
        from discord_bot.ui import deliver_prefix
        await deliver_prefix(ctx, reply)

    _run.__name__ = f"prefix_{name}"
    return _run


def _slash_plain(dispatch_name: str):
    async def callback(interaction: discord.Interaction):
        reply = dispatch(str(interaction.user.id), str(interaction.channel_id), dispatch_name)
        from discord_bot.ui import deliver_slash
        await deliver_slash(interaction, reply)

    callback.__name__ = f"slash_{dispatch_name}"
    return callback


def _slash_help():
    async def callback(interaction: discord.Interaction, nhom: str = ""):
        line = "help" if not nhom.strip() else f"help {_normalize(nhom)}"
        reply = dispatch(str(interaction.user.id), str(interaction.channel_id), line)
        from discord_bot.ui import deliver_slash
        await deliver_slash(interaction, reply)

    callback.__name__ = "slash_help"
    return callback


class MonsterBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned_or(*PREFIXES),
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )

    async def setup_hook(self):
        from discord_bot.ui import start_sweeper
        start_sweeper()
        self._bind_prefix()
        self._bind_slash()
        guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        print(f"Synced {len(synced)} slash commands", flush=True)

    def _bind_prefix(self):
        for spec in list_commands():
            self.add_command(commands.Command(
                _prefix_callback(spec.name),
                name=spec.name,
                aliases=list(spec.aliases),
                help=spec.summary,
                brief=spec.usage,
            ))

    def _bind_slash(self):
        shown = (
            ("toi", "me", "Mở menu nhân vật"),
            ("san", "hunt", "Săn một trận ở map hiện tại"),
            ("tui", "bag", "Mở túi đồ"),
            ("cho", "shop", "Mở cửa hàng"),
            ("bando", "map", "Xem và đổi khu vực"),
        )
        help_cb = app_commands.describe(
            nhom="Nhóm lệnh: nhân vật, săn, chợ, đồ, rèn, hầm, đội hoặc đấu",
        )(_slash_help())
        self.tree.add_command(app_commands.command(
            name="trogiup",
            description="Xem cách chơi và tên lệnh",
        )(help_cb))
        for slash_name, dispatch_name, description in shown:
            callback = _slash_plain(dispatch_name)
            self.tree.add_command(app_commands.command(name=slash_name, description=description)(callback))

    async def on_ready(self):
        print(f"Logged in as {self.user} ({self.user.id})", flush=True)
        print(f"Prefix: {' '.join(PREFIXES)}  ·  lệnh: {len(list_commands())}", flush=True)

    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.CommandNotFound):
            await ctx.send("Không có lệnh đó. Gõ `!help`.")
            return
        if isinstance(error, commands.CommandInvokeError):
            await ctx.send(f"Lỗi: {error.original}")
            return
        await ctx.send(f"Lỗi: {error}")


def main() -> None:
    if not TOKEN:
        raise SystemExit("Thiếu DISCORD_TOKEN")
    data_store.reload_catalogs()
    MonsterBot().run(TOKEN)


if __name__ == "__main__":
    main()
