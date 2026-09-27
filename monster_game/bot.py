"""
Discord front-end for monster_game.

Token is read from the DISCORD_TOKEN environment variable only.
Never store it in this file or commit it.

Run:  DISCORD_TOKEN=... python -m monster_game.bot
"""
from __future__ import annotations

import os

import discord
from discord import app_commands
from discord.ext import commands

from monster_game import data_store, game, render

TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()


def _pid(user: discord.abc.User) -> str:
    return str(user.id)


def _ch(channel_id: int) -> str:
    return str(channel_id)


def _gold(player_id: str) -> int:
    character = game.get_character(player_id)
    return int((character or {}).get("gold", 0))


def _pay(player_id: str, amount: int) -> None:
    if amount:
        data_store.add_gold(player_id, -int(amount))


def _chunks(text: str) -> list[str]:
    return render.split_message(text or "(trống)", 1900)


class MonsterBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user} ({self.user.id})", flush=True)


bot = MonsterBot()


async def _send(target, text: str):
    chunks = _chunks(text)
    first = True
    for chunk in chunks:
        if isinstance(target, discord.Interaction):
            if first and not target.response.is_done():
                await target.response.send_message(chunk)
            else:
                await target.followup.send(chunk)
        else:
            await target.send(chunk)
        first = False


def _need_char(player_id: str) -> str | None:
    if game.get_character(player_id) is None:
        return "Chưa có nhân vật. Dùng /tao tên"
    return None


@bot.tree.command(name="trogiup", description="Danh sách lệnh MonSTER")
async def trogiup(interaction: discord.Interaction):
    await _send(interaction, """**MonSTER**
/tao tên — tạo nhân vật (có sẵn 2.500 vàng)
/toi — trạng thái
/tui — túi đồ
/map — danh sách map
/di số — đến map
/san — săn một mình
/sua — sửa vũ khí
/dap — cường hóa vũ khí đang mặc
/ptao tên — lập tổ đội (tối đa 4)
/pvao số — vào tổ đội
/proi — rời tổ đội
/pdi số — đội trưởng chọn map
/psan — săn chung (HP quái chung, EXP chia đều)
/pdun mã — vào dungeon theo đội (cong_tan_thu, ham_pho_dem)
/ptiep [hành_động] — đội trưởng đi tiếp phòng
""")


@bot.tree.command(name="tao", description="Tạo nhân vật")
@app_commands.describe(ten="Tên thợ săn")
async def tao(interaction: discord.Interaction, ten: str):
    created = game.create_character(_pid(interaction.user), ten[:32])
    if created is None:
        await _send(interaction, "Bạn đã có nhân vật.")
        return
    await _send(interaction, render.render_character(game.character_summary(_pid(interaction.user))))


@bot.tree.command(name="toi", description="Xem trạng thái")
async def toi(interaction: discord.Interaction):
    pid = _pid(interaction.user)
    err = _need_char(pid)
    if err:
        await _send(interaction, err)
        return
    summary = game.character_summary(pid)
    text = render.render_character(summary)
    text += f"\n💰 Vàng: {render.fmt(_gold(pid))}"
    await _send(interaction, text)


@bot.tree.command(name="tui", description="Xem túi đồ")
async def tui(interaction: discord.Interaction):
    pid = _pid(interaction.user)
    err = _need_char(pid)
    if err:
        await _send(interaction, err)
        return
    await _send(interaction, render.render_bag(game.get_character(pid)))


@bot.tree.command(name="map", description="Danh sách khu vực")
async def map_cmd(interaction: discord.Interaction):
    pid = _pid(interaction.user)
    await _send(interaction, render.render_locations(game.list_locations(), game.get_character(pid)))


@bot.tree.command(name="di", description="Đến một khu vực")
@app_commands.describe(so="Số thứ tự map")
async def di(interaction: discord.Interaction, so: int):
    pid = _pid(interaction.user)
    err = _need_char(pid)
    if err:
        await _send(interaction, err)
        return
    loc = game.set_location(pid, so)
    if loc is None:
        await _send(interaction, "Không có map này.")
        return
    await _send(interaction, f"Đã đến {loc['name']}.")


@bot.tree.command(name="san", description="Săn quái ở map hiện tại")
async def san(interaction: discord.Interaction):
    pid = _pid(interaction.user)
    err = _need_char(pid)
    if err:
        await _send(interaction, err)
        return
    outcome = game.encounter_and_fight(pid)
    await _send(interaction, render.render_hunt(outcome))
    if outcome.get("adventure"):
        # auto-pick the first action so the chat flow doesn't stall
        action = outcome["adventure"]["actions"][0]["id"]
        result = game.resolve_adventure(pid, action)
        _pay(pid, -int(result.get("gold_delta") or 0))  # gold_delta positive means gain
        await _send(interaction, render.render_adventure_result(result))


@bot.tree.command(name="sua", description="Sửa vũ khí đang trang bị")
async def sua(interaction: discord.Interaction):
    pid = _pid(interaction.user)
    err = _need_char(pid)
    if err:
        await _send(interaction, err)
        return
    result = game.repair_weapon(pid, _gold(pid))
    if result.get("ok"):
        _pay(pid, result["cost"])
    await _send(interaction, render.render_repair(result))


@bot.tree.command(name="dap", description="Cường hóa vũ khí đang mặc")
async def dap(interaction: discord.Interaction):
    pid = _pid(interaction.user)
    err = _need_char(pid)
    if err:
        await _send(interaction, err)
        return
    quote = game.enhance_quote(pid, "weapon")
    if not quote.get("ok"):
        await _send(interaction, render.render_enhance_quote(quote))
        return
    result = game.enhance_item(pid, "weapon", balance=_gold(pid))
    if result.get("ok"):
        _pay(pid, result["gold_cost"])
    await _send(interaction, render.render_enhance_quote(quote) + "\n" + render.render_enhance_result(result))


@bot.tree.command(name="ptao", description="Lập tổ đội")
@app_commands.describe(ten="Tên tổ đội")
async def ptao(interaction: discord.Interaction, ten: str = "Tổ đội"):
    pid = _pid(interaction.user)
    err = _need_char(pid)
    if err:
        await _send(interaction, err)
        return
    result = game.create_party(_ch(interaction.channel_id), pid, ten[:40])
    await _send(interaction, render.render_party_action(result))


@bot.tree.command(name="pvao", description="Vào tổ đội")
@app_commands.describe(so="Số tổ đội")
async def pvao(interaction: discord.Interaction, so: int):
    pid = _pid(interaction.user)
    err = _need_char(pid)
    if err:
        await _send(interaction, err)
        return
    result = game.join_party(_ch(interaction.channel_id), pid, so)
    await _send(interaction, render.render_party_action(result))


@bot.tree.command(name="proi", description="Rời tổ đội")
async def proi(interaction: discord.Interaction):
    result = game.leave_party(_ch(interaction.channel_id), _pid(interaction.user))
    await _send(interaction, render.render_party_action(result))


@bot.tree.command(name="pds", description="Xem các tổ đội trong kênh")
async def pds(interaction: discord.Interaction):
    await _send(interaction, render.render_party_list(_ch(interaction.channel_id)))


@bot.tree.command(name="pdi", description="Đội trưởng chọn map cho cả đội")
@app_commands.describe(so="Số map")
async def pdi(interaction: discord.Interaction, so: int):
    result = game.set_party_location(_ch(interaction.channel_id), _pid(interaction.user), so)
    if not result.get("ok"):
        await _send(interaction, render.render_party_action(result))
        return
    await _send(interaction, f"Tổ đội đến {result['location']['name']}.\n"
                + render.render_party(result["party"]))


@bot.tree.command(name="psan", description="Săn theo tổ đội")
async def psan(interaction: discord.Interaction):
    result = game.party_hunt(_ch(interaction.channel_id), _pid(interaction.user))
    await _send(interaction, render.render_party_hunt(result))


@bot.tree.command(name="pdun", description="Cả đội vào dungeon")
@app_commands.describe(ma="cong_tan_thu hoặc ham_pho_dem")
async def pdun(interaction: discord.Interaction, ma: str):
    result = game.party_start_dungeon(_ch(interaction.channel_id), _pid(interaction.user), ma.strip())
    if not result.get("ok"):
        await _send(interaction, render.render_dungeon_result(result))
        return
    await _send(interaction, f"🏰 {result.get('party')} vào {result.get('dungeon')}.\nDùng /ptiep để đi tiếp.")


@bot.tree.command(name="ptiep", description="Đội trưởng đi tiếp một phòng dungeon")
@app_commands.describe(hanh_dong="Mã lựa chọn nếu phòng đang hỏi")
async def ptiep(interaction: discord.Interaction, hanh_dong: str = ""):
    pid = _pid(interaction.user)
    result = game.party_advance_dungeon(
        _ch(interaction.channel_id), pid, action_id=hanh_dong.strip() or None,
    )
    shares = result.get("gold_shares")
    if shares:
        for mid, amount in shares.items():
            data_store.add_gold(mid, int(amount))
    elif result.get("gold_delta"):
        data_store.add_gold(pid, int(result["gold_delta"]))
    await _send(interaction, render.render_dungeon_result(result))


def main() -> None:
    if not TOKEN:
        raise SystemExit("Thiếu DISCORD_TOKEN")
    data_store.reload_catalogs()
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
