"""
musicbot/slash_commands.py
--------------------------
Slash command wrappers for MusicBot.

All 53 user-facing commands covered across 6 batches:

  Batch 1 — resetplaylist, help, blockuser (group), blocksong (group),
             autoplaylist (group), joinserver, karaoke, play, shuffleplay, playnext
  Batch 2 — playnow, seek, repeat, move, stream, search, np, summon, follow, pause
  Batch 3 — resume, shuffle, clear, remove, skip, volume, speed,
             setalias (group), config (group), option
  Batch 4 — cache (group), queue, clean, pldump, id, listids, perms
  Batch 5 — setperms (group), setname, setnick, setprefix, language (group),
             setavatar, disconnect, restart (group), shutdown, leaveserver
  Batch 6 — checkupdates, uptime, botlatency, latency, botversion, setcookies

Dev-only commands intentionally excluded:
  testready, breakpoint, objgraph, debug, makemarkdown, makeini

Strategy
--------
* Each slash handler defers the interaction, resolves the same context objects
  that on_message normally injects (player, ssd_, permissions, …), then calls
  the existing cmd_* method directly. Zero business-logic duplication.
* The custom permissions system is preserved via _check_perms().
* A shared _send() helper converts Response/ErrorResponse → interaction reply.
* SearchView and QueueView provide interactive UI for /search and /queue.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from . import exceptions
from .constructs import GuildSpecificData, MusicBotResponse

if TYPE_CHECKING:
    from .bot import MusicBot
    from .permissions import PermissionGroup
    from .player import MusicPlayer

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: flatten a Response content field for an interaction reply
# ---------------------------------------------------------------------------

def _content(resp: Optional[MusicBotResponse]) -> str:
    if resp is None:
        return "✅"
    text = getattr(resp, "content", None) or "✅"
    # Discord followup limit is 2 000 chars
    return text[:1997] + "…" if len(text) > 2000 else text


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SearchView — interactive Select-based search picker for /search
# ---------------------------------------------------------------------------

class SearchView(discord.ui.View):
    """
    Presents yt-dlp search results as a Select dropdown.
    Only the user who ran /search can interact with it.
    Auto-disables after 60 seconds.
    """

    SERVICES = {
        "yt": "ytsearch", "youtube": "ytsearch",
        "sc": "scsearch", "soundcloud": "scsearch",
        "yh": "yvsearch", "yahoo": "yvsearch",
        "gv": "gvsearch", "google": "gvsearch",
        "nv": "nicosearch", "nico": "nicosearch",
        "bb": "bilisearch", "bili": "bilisearch",
    }

    def __init__(
        self,
        *,
        bot: "MusicBot",
        entries: list,
        author: discord.Member,
        guild: discord.Guild,
        channel,
        player: "MusicPlayer",
        permissions: "PermissionGroup",
        service_label: str,
    ) -> None:
        super().__init__(timeout=60)
        self.bot = bot
        self.entries = entries
        self.author = author
        self.guild = guild
        self.channel = channel
        self.player = player
        self.permissions = permissions
        self.service_label = service_label
        self.queued: bool = False

        # Build the Select options — Discord caps labels at 100 chars,
        # descriptions at 100 chars, and total options at 25.
        options = []
        for i, entry in enumerate(entries[:25]):
            title = entry["title"] or "未知標題"
            url = entry["url"]
            duration = ""
            try:
                from .utils import format_song_duration
                duration = format_song_duration(entry.duration_td)
            except Exception:
                pass

            label = title[:97] + "…" if len(title) > 100 else title
            desc = duration[:97] + "…" if len(duration) > 100 else duration

            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(i),
                    description=desc or None,
                )
            )

        select = discord.ui.Select(
            placeholder="選一個結果加入播放佇列…",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

        cancel = discord.ui.Button(
            label="取消",
            style=discord.ButtonStyle.secondary,
        )
        cancel.callback = self._on_cancel
        self.add_item(cancel)

    def _label(self) -> str:
        return f"來自 **{self.service_label}** 的搜尋結果"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "只有下 `/search` 指令的人可以選擇結果。", ephemeral=True
            )
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        idx = int(interaction.data["values"][0])  # type: ignore[index]
        entry = self.entries[idx]
        url = entry["url"]
        title = entry["title"] or url

        self._disable_all()
        await interaction.edit_original_response(
            content=f"⏳ 正在加入 **{title}**…", view=self
        )

        try:
            resp = await self.bot.cmd_play(
                message=None,
                player=self.player,
                channel=self.channel,
                guild=self.guild,
                author=self.author,
                permissions=self.permissions,
                leftover_args=[],
                song_url=url,
            )
            content = _content(resp) if resp else f"✅ **{title}** 已加入播放佇列。"
        except Exception as e:
            msg = getattr(e, "message", str(e))
            fmt = getattr(e, "fmt_args", {})
            if fmt:
                try:
                    msg = msg % fmt
                except Exception:
                    pass
            content = f"❌ {msg}"

        self.queued = True
        self.stop()
        await interaction.edit_original_response(content=content, view=None)

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        self._disable_all()
        self.stop()
        await interaction.response.edit_message(content="已取消搜尋。", view=None)

    def _disable_all(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    async def on_timeout(self) -> None:
        # We don't have the original interaction here to edit, but the view
        # components will be visually greyed out once disabled on next render.
        self._disable_all()



# ---------------------------------------------------------------------------
# QueueView — paginated queue display for /queue
# ---------------------------------------------------------------------------

class QueueView(discord.ui.View):
    """
    Prev / Next / Close pagination for the /queue command.
    Any user in the guild can flip pages.
    Auto-disables after the bot's configured delete_delay_long timeout.
    """

    def __init__(
        self,
        *,
        bot: "MusicBot",
        player: "MusicPlayer",
        guild: discord.Guild,
        channel,
        ssd,
        start_page: int = 0,
    ) -> None:
        super().__init__(timeout=bot.config.delete_delay_long)
        self.bot = bot
        self.player = player
        self.guild = guild
        self.channel = channel
        self.ssd = ssd
        self.page = start_page
        self.message: Optional[discord.Message] = None

    @property
    def pages_total(self) -> int:
        import math
        total = len(self.player.playlist.entries)
        if not total:
            return 1
        return math.ceil(total / self.bot.config.queue_length)

    async def build_page(self) -> str:
        """Build the text content for the current page."""
        from .utils import format_song_duration

        player = self.player
        ssd = self.ssd
        total_entry_count = len(player.playlist.entries)

        if not total_entry_count:
            return "目前佇列是空的！用播放指令加點歌曲吧。"

        current_progress = ""
        if player.is_playing and player.current_entry:
            song_progress = format_song_duration(player.progress)
            song_total = (
                format_song_duration(player.current_entry.duration_td)
                if player.current_entry.duration is not None
                else "（未知長度）"
            )
            added_by = "〔自動播放清單〕"
            if player.current_entry.channel and player.current_entry.author:
                added_by = player.current_entry.author.name
            current_progress = (
                f"正在播放：`{player.current_entry.title}`\n"
                f"加入者：`{added_by}`\n"
                f"進度：`[{song_progress}/{song_total}]`\n\n"
            )

        start_index = self.bot.config.queue_length * self.page
        end_index = start_index + self.bot.config.queue_length
        starting_at = start_index + 1

        tracks_list = ""
        queue_segment = list(player.playlist.entries)[start_index:end_index]
        for idx, item in enumerate(queue_segment, starting_at):
            if item == player.current_entry:
                continue
            added_by = "〔自動播放清單〕"
            if item.channel and item.author:
                added_by = item.author.name
            title = item.title[:40] + " ..." if len(item.title) > 40 else item.title
            entry_str = f"**#{idx}:** `{title}` — 加入者 `{added_by}`\n"
            if len(tracks_list) + len(entry_str) < 1800:
                tracks_list += entry_str

        page_info = f"第 **{self.page + 1}/{self.pages_total}** 頁"
        return (
            f"**佇列中的歌曲** — {page_info}\n\n"
            f"{current_progress}"
            f"共 `{total_entry_count}` 首。\n\n"
            f"{tracks_list}"
        )

    def _update_buttons(self) -> None:
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.pages_total - 1

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.page = max(0, self.page - 1)
        self._update_buttons()
        content = await self.build_page()
        await interaction.response.edit_message(content=content, view=self)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.page = min(self.pages_total - 1, self.page + 1)
        self._update_buttons()
        content = await self.build_page()
        await interaction.response.edit_message(content=content, view=self)

    @discord.ui.button(emoji="✖️", style=discord.ButtonStyle.danger)
    async def close_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await interaction.response.edit_message(content="佇列顯示已關閉。", view=None)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

class SlashCommands(commands.Cog):
    """Slash command surface for MusicBot."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """
        Slash command callbacks run through discord.py's app_commands error
        path, which never reaches Client.on_error. Without this, the
        RestartSignal/TerminateSignal that _restart()/slash_shutdown() raise
        would just be logged and swallowed here, leaving the bot running.
        Mirror on_error's signal handling (see MusicBot.on_error in bot.py).
        """
        original = getattr(error, "original", error)
        if isinstance(original, (exceptions.RestartSignal, exceptions.TerminateSignal)):
            self.bot.exit_signal = original
            await self.bot.logout()
            return
        log.error(
            "Error in slash command %s",
            interaction.command.name if interaction.command else "?",
            exc_info=original,
        )

    # -----------------------------------------------------------------------
    # Shared context helpers  (mirror on_message kwarg injection)
    # -----------------------------------------------------------------------

    async def _check_perms(
        self,
        interaction: discord.Interaction,
        command_name: str,
        sub_cmd: str = "",
    ) -> bool:
        """
        Replicates the permission gate in on_message.
        Returns True if allowed, sends ephemeral error and returns False otherwise.
        """
        if not isinstance(interaction.user, discord.Member):
            await self._reply(
                interaction, "這個指令只能在伺服器中使用。", ephemeral=True
            )
            return False
        perms: PermissionGroup = self.bot.permissions.for_user(interaction.user)
        if (
            interaction.user.id != self.bot.config.owner_id
            and not perms.can_use_command(command_name, sub_cmd)
        ):
            await self._reply(
                interaction,
                f"你的權限群組（`{perms.name}`）不能使用 `/{command_name}`。",
                ephemeral=True,
            )
            return False
        return True

    async def _get_player(self, interaction: discord.Interaction) -> MusicPlayer:
        """
        Resolve a MusicPlayer from an Interaction.
        Mirrors the 'player' kwarg branch in on_message; auto-summons if
        the user has summonplay permission.
        Raises CommandError on failure.
        """
        user = interaction.user
        if not isinstance(user, discord.Member) or not interaction.guild:
            raise exceptions.CommandError("這個指令必須在伺服器中使用。")
        if not user.voice or not user.voice.channel:
            raise exceptions.CommandError(
                "使用這個指令前，你必須先加入一個語音頻道。"
            )
        perms: PermissionGroup = self.bot.permissions.for_user(user)
        return await self.bot.get_player(
            user.voice.channel, create=perms.summonplay
        )

    def _ssd(self, interaction: discord.Interaction) -> Optional[GuildSpecificData]:
        if interaction.guild:
            return self.bot.server_data[interaction.guild.id]
        return None

    async def _reply(
        self,
        interaction: discord.Interaction,
        content: str,
        *,
        ephemeral: bool = False,
        view: Optional[discord.ui.View] = None,
    ) -> None:
        kwargs: dict = {}
        if view is not None:
            kwargs["view"] = view
        if interaction.response.is_done():
            try:
                await interaction.followup.send(content, ephemeral=ephemeral, **kwargs)
            except discord.HTTPException:
                # If Discord rejects ephemeral=True due to non-ephemeral defer(), fallback to non-ephemeral followup
                await interaction.followup.send(content, **kwargs)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral, **kwargs)

    async def _send(
        self,
        interaction: discord.Interaction,
        resp: Optional[MusicBotResponse],
        *,
        ephemeral: bool = False,
    ) -> None:
        await self._reply(interaction, _content(resp), ephemeral=ephemeral)

    async def _err(self, interaction: discord.Interaction, exc: Exception) -> None:
        msg = getattr(exc, "message", str(exc))
        fmt = getattr(exc, "fmt_args", {})
        if fmt:
            try:
                msg = msg % fmt
            except Exception:
                pass
        await self._reply(interaction, f"❌ {msg}", ephemeral=True)


    # -----------------------------------------------------------------------
    # /resetplaylist
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="resetplaylist",
        description="重新載入這個伺服器的自動播放清單。",
    )
    async def slash_resetplaylist(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "resetplaylist"):
            return
        try:
            if not interaction.guild:
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_resetplaylist(
                ssd_=self._ssd(interaction),
                guild=interaction.guild,
                player=player,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /help
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="help",
        description="顯示機器人指令列表，或查詢特定指令的詳細說明。",
    )
    @app_commands.describe(command="要查詢的指令名稱，或輸入 'all' 顯示完整列表。")
    async def slash_help(
        self,
        interaction: discord.Interaction,
        command: Optional[str] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            guild = interaction.guild
            if command:
                cmd_name = command.lower()
                cmd_fn = getattr(self.bot, f"cmd_{cmd_name}", None)
                uid = interaction.user.id
                is_dev_or_owner = (
                    uid == self.bot.config.owner_id or uid in self.bot.config.dev_ids
                )
                # Mirror cmd_help's gate: dev-only commands are treated as
                # nonexistent for anyone who isn't owner/dev, so their
                # existence/usage isn't leaked to regular users either.
                if not cmd_fn or (hasattr(cmd_fn, "dev_cmd") and not is_dev_or_owner):
                    await interaction.followup.send(
                        f"沒有名為 `{cmd_name}` 的指令。", ephemeral=True
                    )
                    return
                help_text = await self.bot.gen_cmd_help(cmd_name, guild)
                await interaction.followup.send(help_text, ephemeral=True)
            else:
                # Exclude @dev_cmd-marked commands, same as gen_cmd_list().
                nat_cmds = sorted(
                    c.replace("cmd_", "")
                    for c in dir(self.bot)
                    if c.startswith("cmd_")
                    and not c.startswith("cmd__")
                    and not hasattr(getattr(self.bot, c), "dev_cmd")
                )
                prefix = self.bot.config.command_prefix
                body = (
                    f"**可用指令** *（前綴：`{prefix}`）*\n"
                    f"```{', '.join(nat_cmds)}```\n"
                    f"查看詳細說明：`/help command:<指令名稱>`"
                )
                await interaction.followup.send(body, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /blockuser  (group)
    # -----------------------------------------------------------------------

    blockuser = app_commands.Group(
        name="blockuser",
        description="管理使用者封鎖名單。",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @blockuser.command(name="add", description="封鎖某位使用者，禁止其使用機器人。")
    @app_commands.describe(user="要封鎖的成員。")
    async def slash_blockuser_add(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "blockuser", "add"):
            return
        try:
            resp = await self.bot.cmd_blockuser(
                ssd_=self._ssd(interaction),
                user_mentions=[user],
                option="add",
                leftover_args=[],
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    @blockuser.command(name="remove", description="解除封鎖某位使用者。")
    @app_commands.describe(user="要解除封鎖的成員。")
    async def slash_blockuser_remove(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "blockuser", "remove"):
            return
        try:
            resp = await self.bot.cmd_blockuser(
                ssd_=self._ssd(interaction),
                user_mentions=[user],
                option="remove",
                leftover_args=[],
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    @blockuser.command(name="status", description="查詢某位使用者是否被封鎖。")
    @app_commands.describe(user="要查詢的成員。")
    async def slash_blockuser_status(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_perms(interaction, "blockuser", "status"):
            return
        try:
            resp = await self.bot.cmd_blockuser(
                ssd_=self._ssd(interaction),
                user_mentions=[user],
                option="status",
                leftover_args=[],
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /blocksong  (group)
    # -----------------------------------------------------------------------

    blocksong = app_commands.Group(
        name="blocksong",
        description="管理歌曲封鎖名單。",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @blocksong.command(name="add", description="用網址或關鍵字封鎖一首歌曲。")
    @app_commands.describe(
        subject="要封鎖的網址或字詞。留空則封鎖目前正在播放的歌曲。"
    )
    async def slash_blocksong_add(
        self,
        interaction: discord.Interaction,
        subject: Optional[str] = None,
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "blocksong", "add"):
            return
        try:
            guild = interaction.guild
            _player = self.bot.get_player_in(guild) if guild else None
            resp = await self.bot.cmd_blocksong(
                ssd_=self._ssd(interaction),
                guild=guild,
                _player=_player,
                option="add",
                leftover_args=[],
                song_subject=subject or "",
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    @blocksong.command(name="remove", description="用網址或關鍵字解除封鎖一首歌曲。")
    @app_commands.describe(subject="要從封鎖名單移除的網址或字詞。")
    async def slash_blocksong_remove(
        self,
        interaction: discord.Interaction,
        subject: str,
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "blocksong", "remove"):
            return
        try:
            guild = interaction.guild
            _player = self.bot.get_player_in(guild) if guild else None
            resp = await self.bot.cmd_blocksong(
                ssd_=self._ssd(interaction),
                guild=guild,
                _player=_player,
                option="remove",
                leftover_args=[],
                song_subject=subject,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /autoplaylist  (group — 8 subcommands)
    # -----------------------------------------------------------------------

    autoplaylist = app_commands.Group(
        name="autoplaylist",
        description="管理伺服器的自動播放清單。",
    )

    async def _ap(
        self,
        interaction: discord.Interaction,
        option: str,
        opt_url: str = "",
    ) -> None:
        """Shared dispatcher for all /autoplaylist subcommands."""
        if not await self._check_perms(interaction, "autoplaylist", option):
            return
        try:
            guild = interaction.guild
            user = interaction.user
            if not guild or not isinstance(user, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            _player = self.bot.get_player_in(guild)
            voice_channel = user.voice.channel if user.voice else None
            resp = await self.bot.cmd_autoplaylist(
                ssd_=self._ssd(interaction),
                guild=guild,
                author=user,
                channel=interaction.channel,
                voice_channel=voice_channel,
                message=None,   # guarded in _do_cmd_unpause_check — see module docstring
                _player=_player,
                player=player,
                option=option,
                opt_url=opt_url,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    @autoplaylist.command(name="add", description="把一首歌加入自動播放清單。")
    @app_commands.describe(url="歌曲網址。留空則加入目前正在播放的歌曲。")
    async def slash_ap_add(self, interaction: discord.Interaction, url: Optional[str] = None) -> None:
        await interaction.response.defer()
        await self._ap(interaction, "add", url or "")

    @autoplaylist.command(name="remove", description="從自動播放清單移除一首歌。")
    @app_commands.describe(url="歌曲網址。留空則移除目前正在播放的歌曲。")
    async def slash_ap_remove(self, interaction: discord.Interaction, url: Optional[str] = None) -> None:
        await interaction.response.defer()
        await self._ap(interaction, "remove", url or "")

    @autoplaylist.command(name="restart", description="從硬碟重新載入自動播放清單。")
    async def slash_ap_restart(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self._ap(interaction, "restart")

    @autoplaylist.command(name="show", description="列出這個伺服器可用的自動播放清單檔案。")
    async def slash_ap_show(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._ap(interaction, "show")

    @autoplaylist.command(name="set", description="切換伺服器使用的自動播放清單檔案。")
    @app_commands.describe(filename="播放清單檔名，例如 mylist.txt")
    async def slash_ap_set(self, interaction: discord.Interaction, filename: str) -> None:
        await interaction.response.defer()
        await self._ap(interaction, "set", filename)

    @autoplaylist.command(name="clear", description="清空某個播放清單檔案裡的所有曲目。")
    @app_commands.describe(filename="播放清單檔名。留空則清空目前伺服器使用的清單。")
    async def slash_ap_clear(self, interaction: discord.Interaction, filename: Optional[str] = None) -> None:
        await interaction.response.defer()
        await self._ap(interaction, "clear", filename or "")

    @autoplaylist.command(name="queue", description="把播放清單裡的所有曲目倒進播放佇列。")
    @app_commands.describe(filename="播放清單檔名。留空則使用目前伺服器使用的清單。")
    async def slash_ap_queue(self, interaction: discord.Interaction, filename: Optional[str] = None) -> None:
        await interaction.response.defer()
        await self._ap(interaction, "queue", filename or "")

    @autoplaylist.command(name="reload", description="從硬碟熱重載播放清單檔案。")
    @app_commands.describe(filename="播放清單檔名。留空則重載目前伺服器使用的清單。")
    async def slash_ap_reload(self, interaction: discord.Interaction, filename: Optional[str] = None) -> None:
        await interaction.response.defer()
        await self._ap(interaction, "reload", filename or "")

    # -----------------------------------------------------------------------
    # /joinserver  (owner-only)
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="joinserver",
        description="產生這個機器人的 OAuth 邀請連結。（僅限擁有者）",
    )
    async def slash_joinserver(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id != self.bot.config.owner_id:
            await interaction.followup.send("這個指令僅限機器人擁有者使用。", ephemeral=True)
            return
        try:
            resp = await self.bot.cmd_joinserver(ssd_=self._ssd(interaction))
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /karaoke
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="karaoke",
        description="切換卡拉OK模式——開啟時只有具備卡拉OK權限的成員可以加歌。",
    )
    async def slash_karaoke(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "karaoke"):
            return
        try:
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_karaoke(
                ssd_=self._ssd(interaction),
                player=player,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /play
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="play",
        description="把一首歌加入播放佇列。可以是網址或搜尋字詞。",
    )
    @app_commands.describe(
        query="YouTube/Spotify 網址、任何 yt-dlp 支援的網址，或搜尋字詞。"
    )
    async def slash_play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "play"):
            return
        try:
            guild = interaction.guild
            user = interaction.user
            if not guild or not isinstance(user, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_play(
                message=None,           # guarded in _do_cmd_unpause_check
                player=player,
                channel=interaction.channel,
                guild=guild,
                author=user,
                permissions=self.bot.permissions.for_user(user),
                leftover_args=[],
                song_url=query,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /shuffleplay
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="shuffleplay",
        description="把一個播放清單洗牌後加入播放佇列。",
    )
    @app_commands.describe(url="要洗牌加入佇列的播放清單網址。")
    async def slash_shuffleplay(self, interaction: discord.Interaction, url: str) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "shuffleplay"):
            return
        try:
            guild = interaction.guild
            user = interaction.user
            if not guild or not isinstance(user, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_shuffleplay(
                ssd_=self._ssd(interaction),
                message=None,           # guarded in _do_cmd_unpause_check
                player=player,
                channel=interaction.channel,
                guild=guild,
                author=user,
                permissions=self.bot.permissions.for_user(user),
                leftover_args=[],
                song_url=url,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /playnext
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="playnext",
        description="把一首歌插入佇列，緊接在目前歌曲之後播放。",
    )
    @app_commands.describe(query="網址或搜尋字詞。")
    async def slash_playnext(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "playnext"):
            return
        try:
            guild = interaction.guild
            user = interaction.user
            if not guild or not isinstance(user, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_playnext(
                message=None,           # guarded in _do_cmd_unpause_check
                player=player,
                channel=interaction.channel,
                guild=guild,
                author=user,
                permissions=self.bot.permissions.for_user(user),
                leftover_args=[],
                song_url=query,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # =======================================================================
    # BATCH 2
    # playnow, seek, repeat, move, stream, search, np, summon, follow, pause
    # =======================================================================

    # -----------------------------------------------------------------------
    # /playnow
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="playnow",
        description="跳過目前歌曲，立刻播放這首。",
    )
    @app_commands.describe(query="網址或搜尋字詞。")
    async def slash_playnow(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "playnow"):
            return
        try:
            guild = interaction.guild
            user = interaction.user
            if not guild or not isinstance(user, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_playnow(
                message=None,
                player=player,
                channel=interaction.channel,
                guild=guild,
                author=user,
                permissions=self.bot.permissions.for_user(user),
                leftover_args=[],
                song_url=query,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /seek
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="seek",
        description="跳到目前歌曲的指定時間點。前面加 + 或 - 可做相對跳轉。",
    )
    @app_commands.describe(time="以秒為單位的時間，例如 90、1:30、+30、-15")
    async def slash_seek(self, interaction: discord.Interaction, time: str) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "seek"):
            return
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_seek(
                ssd_=self._ssd(interaction),
                guild=guild,
                player=player,
                leftover_args=[],
                seek_time=time,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /repeat
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="repeat",
        description="切換循環播放模式。不帶參數 = 依序切換各模式。",
    )
    @app_commands.describe(
        mode="song = 循環目前歌曲 | playlist = 循環整個佇列 | on/off = 直接開關"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="單曲循環",   value="song"),
        app_commands.Choice(name="佇列循環", value="playlist"),
        app_commands.Choice(name="開啟",       value="on"),
        app_commands.Choice(name="關閉",      value="off"),
    ])
    async def slash_repeat(
        self,
        interaction: discord.Interaction,
        mode: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "repeat"):
            return
        try:
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_repeat(
                ssd_=self._ssd(interaction),
                player=player,
                option=mode.value if mode else "",
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /move
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="move",
        description="把一首歌從佇列中的一個位置移到另一個位置。用 /queue 查看位置編號。",
    )
    @app_commands.describe(
        from_pos="歌曲目前在佇列中的位置。",
        to_pos="要移到的目標位置。",
    )
    async def slash_move(
        self,
        interaction: discord.Interaction,
        from_pos: int,
        to_pos: int,
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "move"):
            return
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_move(
                ssd_=self._ssd(interaction),
                player=player,
                guild=guild,
                channel=interaction.channel,
                command=str(from_pos),
                leftover_args=[str(to_pos)],
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /stream
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="stream",
        description="把一個網址加入佇列，以直播串流方式播放（不下載）。",
    )
    @app_commands.describe(url="直接串流網址（Twitch、YouTube 直播、shoutcast 等）")
    async def slash_stream(self, interaction: discord.Interaction, url: str) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "stream"):
            return
        try:
            guild = interaction.guild
            user = interaction.user
            if not guild or not isinstance(user, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_stream(
                ssd_=self._ssd(interaction),
                player=player,
                channel=interaction.channel,
                author=user,
                permissions=self.bot.permissions.for_user(user),
                message=None,
                song_url=url,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /search  — full interactive picker via discord.ui.Select
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="search",
        description="搜尋歌曲，從結果下拉選單中選一首。",
    )
    @app_commands.describe(
        query="搜尋字詞。",
        service="要搜尋的服務（yt、sc、yh、gv、nv、bb）。預設依照機器人設定。",
        results="要顯示的結果數量（預設 5，上限依你的權限而定）。",
    )
    @app_commands.choices(service=[
        app_commands.Choice(name="YouTube（預設）", value="yt"),
        app_commands.Choice(name="SoundCloud",        value="sc"),
        app_commands.Choice(name="Yahoo Video",       value="yh"),
        app_commands.Choice(name="Google Video",      value="gv"),
        app_commands.Choice(name="NicoNico",          value="nv"),
        app_commands.Choice(name="Bilibili",          value="bb"),
    ])
    async def slash_search(
        self,
        interaction: discord.Interaction,
        query: str,
        service: Optional[app_commands.Choice[str]] = None,
        results: Optional[int] = None,
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "search"):
            return

        guild = interaction.guild
        user = interaction.user
        if not guild or not isinstance(user, discord.Member):
            await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
            return

        try:
            player = await self._get_player(interaction)
        except Exception as e:
            await self._err(interaction, e)
            return

        perms = self.bot.permissions.for_user(user)

        if perms.max_songs and player.playlist.count_for_user(user) > perms.max_songs:
            await interaction.followup.send(
                f"❌ 你已達到播放清單項目上限（{perms.max_songs}）。",
                ephemeral=True,
            )
            return

        if player.karaoke_mode and not perms.bypass_karaoke_mode:
            await interaction.followup.send(
                "❌ 卡拉OK模式目前是開啟的。", ephemeral=True
            )
            return

        # Resolve service and result count
        svc_key = service.value if service else self.bot.config.default_search_service
        svc_label = service.name if service else svc_key
        srvc = SearchView.SERVICES.get(svc_key, svc_key)

        max_items = perms.max_search_items
        n = results if results is not None else self.bot.config.defaultsearchresults
        n = max(1, min(n, max_items, 25))  # clamp: at least 1, at most 25 or perms limit

        search_query = f"{srvc}{n}:{query}"

        try:
            self.bot._do_song_blocklist_check(query)
        except Exception as e:
            await self._err(interaction, e)
            return

        await interaction.followup.send(f"🔍 正在 **{svc_label}** 搜尋 `{query}`…")

        try:
            info = await self.bot.downloader.extract_info(
                search_query, download=False, process=True
            )
        except Exception as e:
            await self._err(interaction, e)
            return

        if not info:
            await interaction.edit_original_response(content="沒有找到結果。")
            return

        entries = info.get_entries_objects()
        if not entries:
            await interaction.edit_original_response(content="沒有找到結果。")
            return

        view = SearchView(
            bot=self.bot,
            entries=entries,
            author=user,
            guild=guild,
            channel=interaction.channel,
            player=player,
            permissions=perms,
            service_label=svc_label,
        )

        await interaction.edit_original_response(
            content=f"**來自 {svc_label} 的搜尋結果** — 選一首加入佇列：",
            view=view,
        )

    # -----------------------------------------------------------------------
    # /np  (now playing)
    # cmd_np sends its own embed via safe_send_message and returns None.
    # We just trigger it and send a lightweight ephemeral ack so Discord
    # doesn't show "interaction failed".
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="np",
        description="顯示目前正在播放的歌曲。",
    )
    async def slash_np(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_perms(interaction, "np"):
            return
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            await self.bot.cmd_np(
                ssd_=self._ssd(interaction),
                player=player,
                channel=interaction.channel,
                guild=guild,
            )
            await interaction.followup.send("⬆️", ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /summon
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="summon",
        description="叫機器人加入你目前所在的語音頻道。",
    )
    async def slash_summon(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "summon"):
            return
        try:
            guild = interaction.guild
            user = interaction.user
            if not guild or not isinstance(user, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            resp = await self.bot.cmd_summon(
                ssd_=self._ssd(interaction),
                guild=guild,
                author=user,
                message=None,   # guarded in cmd_summon
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /follow
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="follow",
        description="讓機器人跟著你在語音頻道間移動。再打一次可取消跟隨。",
    )
    @app_commands.describe(user="僅限擁有者：跟隨指定成員而非自己。")
    async def slash_follow(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "follow"):
            return
        try:
            guild = interaction.guild
            author = interaction.user
            if not guild or not isinstance(author, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            mentions = [user] if user else []
            resp = await self.bot.cmd_follow(
                ssd_=self._ssd(interaction),
                guild=guild,
                author=author,
                user_mentions=mentions,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /pause
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="pause",
        description="暫停目前播放的曲目。",
    )
    async def slash_pause(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "pause"):
            return
        try:
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_pause(
                ssd_=self._ssd(interaction),
                player=player,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # =======================================================================
    # BATCH 3
    # resume, shuffle, clear, remove, skip, volume, speed,
    # setalias (group), config (group), option
    # =======================================================================

    # -----------------------------------------------------------------------
    # /resume
    # -----------------------------------------------------------------------

    @app_commands.command(name="resume", description="繼續播放已暫停的曲目。")
    async def slash_resume(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "resume"):
            return
        try:
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_resume(
                ssd_=self._ssd(interaction),
                player=player,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /shuffle
    # -----------------------------------------------------------------------

    @app_commands.command(name="shuffle", description="把目前佇列裡的所有曲目洗牌。")
    async def slash_shuffle(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "shuffle"):
            return
        try:
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_shuffle(
                ssd_=self._ssd(interaction),
                channel=interaction.channel,
                player=player,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /clear
    # -----------------------------------------------------------------------

    @app_commands.command(name="clear", description="清空佇列裡的所有歌曲。")
    async def slash_clear(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "clear"):
            return
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            _player = self.bot.get_player_in(guild)
            resp = await self.bot.cmd_clear(
                ssd_=self._ssd(interaction),
                _player=_player,
                guild=guild,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /remove
    # Three modes: by position, by range (from+to), by user mention.
    # Omitting all args removes the last item in the queue.
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="remove",
        description="依位置、範圍或使用者，從佇列移除歌曲。",
    )
    @app_commands.describe(
        position="要移除的佇列位置（留空則移除最後一項）。",
        to_position="範圍結尾——會移除從 position 到這個位置之間的所有歌曲。",
        user="移除這位成員加入的所有歌曲。",
    )
    async def slash_remove(
        self,
        interaction: discord.Interaction,
        position: Optional[int] = None,
        to_position: Optional[int] = None,
        user: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "remove"):
            return
        try:
            author = interaction.user
            if not isinstance(author, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            perms = self.bot.permissions.for_user(author)

            # Map slash args back to what cmd_remove expects:
            # position=""  leftover_args=[]           → remove last
            # position="N" leftover_args=[]           → remove at N
            # position="N" leftover_args=["M"]        → remove range N-M
            # user_mentions=[user]                    → remove by user
            pos_str = str(position) if position is not None else ""
            leftover = [str(to_position)] if to_position is not None else []

            resp = await self.bot.cmd_remove(
                ssd_=self._ssd(interaction),
                user_mentions=[user] if user else [],
                author=author,
                permissions=perms,
                player=player,
                leftover_args=leftover,
                position=pos_str,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /skip
    # NOTE: Vote-skip via slash passes message=None, so add_skipper is skipped
    # (guarded in bot.py). Vote tallying is based on existing skip state only.
    # Force skip works fully.
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="skip",
        description="跳過目前歌曲，或發起投票跳過。",
    )
    @app_commands.describe(force="強制跳過——需要 InstaSkip 權限。")
    async def slash_skip(
        self,
        interaction: discord.Interaction,
        force: Optional[bool] = None,
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "skip"):
            return
        try:
            guild = interaction.guild
            user = interaction.user
            if not guild or not isinstance(user, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            voice_channel = user.voice.channel if user.voice else None
            param = "force" if force else ""
            resp = await self.bot.cmd_skip(
                ssd_=self._ssd(interaction),
                guild=guild,
                player=player,
                author=user,
                message=None,       # guarded in bot.py — vote-skip add_skipper skipped
                permissions=self.bot.permissions.for_user(user),
                voice_channel=voice_channel,
                param=param,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /volume
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="volume",
        description="設定或顯示播放音量（1–100）。前面加 + 或 - 可做相對調整。",
    )
    @app_commands.describe(level="音量大小 1–100。用 +10 或 -10 做相對調整。")
    async def slash_volume(
        self,
        interaction: discord.Interaction,
        level: Optional[str] = None,
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "volume"):
            return
        try:
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_volume(
                ssd_=self._ssd(interaction),
                player=player,
                new_volume=level or "",
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /speed
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="speed",
        description="調整目前曲目的播放速度（0.5–100.0）。",
    )
    @app_commands.describe(rate="播放速率，例如 1.5 代表快 50%，0.75 代表變慢。")
    async def slash_speed(
        self,
        interaction: discord.Interaction,
        rate: str,
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "speed"):
            return
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            resp = await self.bot.cmd_speed(
                ssd_=self._ssd(interaction),
                guild=guild,
                player=player,
                new_speed=rate,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /setalias  (owner-only group)
    # -----------------------------------------------------------------------

    setalias = app_commands.Group(
        name="setalias",
        description="管理機器人指令別名。僅限擁有者。",
        default_permissions=discord.Permissions(administrator=True),
    )

    async def _owner_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.bot.config.owner_id:
            await interaction.followup.send(
                "這個指令僅限機器人擁有者使用。", ephemeral=True
            )
            return False
        return True

    @setalias.command(name="add", description="為指令新增一個別名。")
    @app_commands.describe(
        alias="要建立的別名名稱。",
        command="這個別名對應到的指令。",
        args="要內建進別名的參數（選填）。",
    )
    async def slash_setalias_add(
        self,
        interaction: discord.Interaction,
        alias: str,
        command: str,
        args: Optional[str] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_setalias(
                ssd_=self._ssd(interaction),
                opt="add",
                leftover_args=args.split() if args else [],
                alias=alias,
                cmd=command,
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @setalias.command(name="remove", description="移除一個現有的別名。")
    @app_commands.describe(alias="要移除的別名名稱。")
    async def slash_setalias_remove(
        self,
        interaction: discord.Interaction,
        alias: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_setalias(
                ssd_=self._ssd(interaction),
                opt="remove",
                leftover_args=[],
                alias=alias,
                cmd="",
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @setalias.command(name="save", description="把目前的別名儲存到設定檔。")
    async def slash_setalias_save(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_setalias(
                ssd_=self._ssd(interaction),
                opt="save",
                leftover_args=[],
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @setalias.command(name="load", description="從設定檔重新載入別名。")
    async def slash_setalias_load(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_setalias(
                ssd_=self._ssd(interaction),
                opt="load",
                leftover_args=[],
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /config  (owner-only group)
    # -----------------------------------------------------------------------

    config = app_commands.Group(
        name="config",
        description="管理機器人設定。僅限擁有者。",
        default_permissions=discord.Permissions(administrator=True),
    )

    @config.command(name="missing", description="顯示缺少的設定選項。")
    async def slash_config_missing(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_config(
                ssd_=self._ssd(interaction),
                user_mentions=[], channel_mentions=[],
                option="missing", leftover_args=[],
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @config.command(name="diff", description="列出自上次載入設定以來變更過的選項。")
    async def slash_config_diff(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_config(
                ssd_=self._ssd(interaction),
                user_mentions=[], channel_mentions=[],
                option="diff", leftover_args=[],
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @config.command(name="list", description="列出所有可用的設定選項。")
    async def slash_config_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_config(
                ssd_=self._ssd(interaction),
                user_mentions=[], channel_mentions=[],
                option="list", leftover_args=[],
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @config.command(name="reload", description="從硬碟重新載入 options.ini。")
    async def slash_config_reload(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_config(
                ssd_=self._ssd(interaction),
                user_mentions=[], channel_mentions=[],
                option="reload", leftover_args=[],
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @config.command(name="help", description="顯示特定設定選項的說明文字。")
    @app_commands.describe(option="選項名稱（若不會混淆可省略區段名）。")
    async def slash_config_help(self, interaction: discord.Interaction, option: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_config(
                ssd_=self._ssd(interaction),
                user_mentions=[], channel_mentions=[],
                option="help", leftover_args=option.split(),
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @config.command(name="show", description="顯示某個設定選項目前的值。")
    @app_commands.describe(option="選項名稱（若不會混淆可省略區段名）。")
    async def slash_config_show(self, interaction: discord.Interaction, option: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_config(
                ssd_=self._ssd(interaction),
                user_mentions=[], channel_mentions=[],
                option="show", leftover_args=option.split(),
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @config.command(name="set", description="設定一個選項的值，僅在本次執行期間生效（不寫入檔案）。")
    @app_commands.describe(
        option="選項名稱（若不會混淆可省略區段名）。",
        value="要設定的新值。",
    )
    async def slash_config_set(
        self, interaction: discord.Interaction, option: str, value: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_config(
                ssd_=self._ssd(interaction),
                user_mentions=[], channel_mentions=[],
                option="set", leftover_args=[*option.split(), value],
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @config.command(name="save", description="把某個設定選項目前的值寫入硬碟。")
    @app_commands.describe(option="選項名稱（若不會混淆可省略區段名）。")
    async def slash_config_save(self, interaction: discord.Interaction, option: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_config(
                ssd_=self._ssd(interaction),
                user_mentions=[], channel_mentions=[],
                option="save", leftover_args=option.split(),
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @config.command(name="reset", description="把某個設定選項重設為預設值。")
    @app_commands.describe(option="選項名稱（若不會混淆可省略區段名）。")
    async def slash_config_reset(self, interaction: discord.Interaction, option: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_config(
                ssd_=self._ssd(interaction),
                user_mentions=[], channel_mentions=[],
                option="reset", leftover_args=option.split(),
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /option  (deprecated — just surfaces the error message)
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="option",
        description="已淘汰，請改用 /config。",
    )
    async def slash_option(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            "❌ `option` 指令已淘汰，請改用 `/config`。",
            ephemeral=True,
        )

    # =======================================================================
    # BATCH 4
    # cache (group), queue, clean, pldump, id, listids, perms
    # + QueueView helper class (defined below SlashCommands — see bottom)
    # =======================================================================

    # -----------------------------------------------------------------------
    # /cache  (owner-only group)
    # -----------------------------------------------------------------------

    cache = app_commands.Group(
        name="cache",
        description="管理音訊檔案快取。僅限擁有者。",
        default_permissions=discord.Permissions(administrator=True),
    )

    @cache.command(name="info", description="顯示目前快取大小與設定。")
    async def slash_cache_info(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_cache(ssd_=self._ssd(interaction), opt="info")
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @cache.command(name="update", description="掃描快取資料夾後顯示資訊。")
    async def slash_cache_update(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_cache(ssd_=self._ssd(interaction), opt="update")
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @cache.command(name="clear", description="依照設定的上限清理音訊快取。")
    async def slash_cache_clear(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_cache(ssd_=self._ssd(interaction), opt="clear")
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /queue
    # Pagination is handled by QueueView (defined after SlashCommands).
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="queue",
        description="顯示目前的播放佇列，支援分頁瀏覽。",
    )
    @app_commands.describe(page="要從第幾頁開始顯示。")
    async def slash_queue(
        self,
        interaction: discord.Interaction,
        page: Optional[int] = None,
    ) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "queue"):
            return
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            player = await self._get_player(interaction)
            ssd = self._ssd(interaction)

            import math
            total = len(player.playlist.entries)
            pages_total = math.ceil(total / self.bot.config.queue_length) if total else 1
            start_page = min(max(0, (page or 1) - 1), pages_total - 1)

            view = QueueView(
                bot=self.bot,
                player=player,
                guild=guild,
                channel=interaction.channel,
                ssd=ssd,
                start_page=start_page,
            )
            content = await view.build_page()

            # Mirror original behaviour: no pagination UI when everything fits on one page.
            if pages_total <= 1:
                await interaction.followup.send(content=content)
            else:
                await interaction.followup.send(content=content, view=view)
                view.message = await interaction.original_response()
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /clean
    # NOTE: Without a triggering message, purge runs against the most recent
    # messages (before=utcnow()) rather than stopping before the command msg.
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="clean",
        description="刪除這個頻道裡機器人的訊息與指令呼叫紀錄。",
    )
    @app_commands.describe(range="要搜尋的訊息數量（預設 50，上限 500）。")
    async def slash_clean(
        self,
        interaction: discord.Interaction,
        range: Optional[int] = 50,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_perms(interaction, "clean"):
            return
        try:
            guild = interaction.guild
            user = interaction.user
            if not guild or not isinstance(user, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            resp = await self.bot.cmd_clean(
                ssd_=self._ssd(interaction),
                message=None,           # guarded in bot.py — purge uses utcnow() instead
                channel=interaction.channel,
                guild=guild,
                author=user,
                search_range_str=str(range),
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /pldump
    # Original sends the file as a DM. Slash version sends it as an
    # ephemeral file attachment in-channel instead.
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="pldump",
        description="把播放清單裡的所有網址匯出成文字檔。",
    )
    @app_commands.describe(url="要匯出的播放清單網址。")
    async def slash_pldump(self, interaction: discord.Interaction, url: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_perms(interaction, "pldump"):
            return
        try:
            user = interaction.user
            if not isinstance(user, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            resp = await self.bot.cmd_pldump(
                ssd_=self._ssd(interaction),
                author=user,
                song_subject=url,
            )
            if resp and getattr(resp, "files", None):
                await interaction.followup.send(
                    _content(resp), files=resp.files, ephemeral=True
                )
            else:
                await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /id
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="id",
        description="顯示你的 Discord 使用者 ID，或其他成員的 ID。",
    )
    @app_commands.describe(user="要查詢的成員（留空則顯示你自己的 ID）。")
    async def slash_id(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_perms(interaction, "id"):
            return
        try:
            author = interaction.user
            if not isinstance(author, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            resp = await self.bot.cmd_id(
                ssd_=self._ssd(interaction),
                author=author,
                user_mentions=[user] if user else [],
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /listids
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="listids",
        description="把這個伺服器的使用者、身分組、頻道 ID 匯出成檔案。",
    )
    @app_commands.describe(category="要包含哪些類型的 ID（預設：全部）。")
    @app_commands.choices(category=[
        app_commands.Choice(name="全部",   value="all"),
        app_commands.Choice(name="使用者", value="users"),
        app_commands.Choice(name="身分組", value="roles"),
        app_commands.Choice(name="頻道",   value="channels"),
    ])
    async def slash_listids(
        self,
        interaction: discord.Interaction,
        category: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_perms(interaction, "listids"):
            return
        try:
            guild = interaction.guild
            user = interaction.user
            if not guild or not isinstance(user, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            cat = category.value if category else "all"
            resp = await self.bot.cmd_listids(
                ssd_=self._ssd(interaction),
                guild=guild,
                author=user,
                leftover_args=[],
                cat=cat,
            )
            if resp and getattr(resp, "files", None):
                await interaction.followup.send(
                    _content(resp), files=resp.files, ephemeral=True
                )
            else:
                await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /perms
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="perms",
        description="顯示你的 MusicBot 權限，或其他成員的權限。",
    )
    @app_commands.describe(user="要查詢的成員（留空則查詢你自己的權限）。")
    async def slash_perms(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_perms(interaction, "perms"):
            return
        try:
            guild = interaction.guild
            author = interaction.user
            if not guild or not isinstance(author, discord.Member):
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            resp = await self.bot.cmd_perms(
                ssd_=self._ssd(interaction),
                author=author,
                user_mentions=[user] if user else [],
                guild=guild,
                permissions=self.bot.permissions.for_user(author),
                target=str(user.id) if user else "",
            )
            # cmd_perms sends to DM via send_to=author — extract content and
            # send as ephemeral instead so it stays in-channel for slash.
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # =======================================================================
    # BATCH 5
    # setperms (group), setname, setnick, setprefix, language (group),
    # setavatar, disconnect, restart (group), shutdown, leaveserver
    # =======================================================================

    # -----------------------------------------------------------------------
    # /setperms  (owner-only group)
    # -----------------------------------------------------------------------

    setperms = app_commands.Group(
        name="setperms",
        description="管理 permissions.ini 設定。僅限擁有者。",
        default_permissions=discord.Permissions(administrator=True),
    )

    async def _sp(
        self,
        interaction: discord.Interaction,
        option: str,
        leftover_args: Optional[list] = None,
    ) -> None:
        """Shared dispatcher for /setperms subcommands."""
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_setperms(
                ssd_=self._ssd(interaction),
                user_mentions=[],
                leftover_args=leftover_args or [],
                option=option,
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @setperms.command(name="list", description="顯示已載入的群組與可用的權限選項。")
    async def slash_setperms_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._sp(interaction, "list")

    @setperms.command(name="reload", description="從 permissions.ini 重新載入權限設定。")
    async def slash_setperms_reload(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._sp(interaction, "reload")

    @setperms.command(name="add", description="新增一個使用預設值的權限群組。")
    @app_commands.describe(group="要建立的新群組名稱。")
    async def slash_setperms_add(self, interaction: discord.Interaction, group: str) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._sp(interaction, "add", [group])

    @setperms.command(name="remove", description="移除一個現有的權限群組。")
    @app_commands.describe(group="要移除的群組名稱。")
    async def slash_setperms_remove(self, interaction: discord.Interaction, group: str) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._sp(interaction, "remove", [group])

    @setperms.command(name="save", description="把某個權限群組儲存到檔案。")
    @app_commands.describe(group="要儲存的群組名稱。")
    async def slash_setperms_save(self, interaction: discord.Interaction, group: str) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._sp(interaction, "save", [group])

    @setperms.command(name="help", description="顯示某個權限選項的說明文字。")
    @app_commands.describe(permission="權限選項名稱。")
    async def slash_setperms_help(self, interaction: discord.Interaction, permission: str) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._sp(interaction, "help", [permission])

    @setperms.command(name="show", description="顯示某個群組的權限目前的值。")
    @app_commands.describe(group="群組名稱。", permission="權限選項名稱。")
    async def slash_setperms_show(
        self, interaction: discord.Interaction, group: str, permission: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._sp(interaction, "show", [group, permission])

    @setperms.command(name="set", description="設定某個群組的權限值。")
    @app_commands.describe(
        group="群組名稱。",
        permission="權限選項名稱。",
        value="要設定的值。",
    )
    async def slash_setperms_set(
        self, interaction: discord.Interaction, group: str, permission: str, value: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._sp(interaction, "set", [group, permission, value])

    # -----------------------------------------------------------------------
    # /setname  (owner-only)
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="setname",
        description="更改機器人的 Discord 使用者名稱。每小時最多改兩次。",
    )
    @app_commands.describe(name="機器人的新使用者名稱。")
    async def slash_setname(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_setname(
                ssd_=self._ssd(interaction),
                leftover_args=[],
                name=name,
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /setnick
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="setnick",
        description="更改機器人在這個伺服器裡的暱稱。",
    )
    @app_commands.describe(nick="機器人的新暱稱。")
    async def slash_setnick(self, interaction: discord.Interaction, nick: str) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "setnick"):
            return
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            resp = await self.bot.cmd_setnick(
                ssd_=self._ssd(interaction),
                guild=guild,
                channel=interaction.channel,
                leftover_args=[],
                nick=nick,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /setprefix
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="setprefix",
        description="設定或清除這個伺服器專屬的指令前綴。需要開啟 EnablePrefixPerGuild。",
    )
    @app_commands.describe(prefix="新的前綴，或輸入 'clear' 移除伺服器專屬前綴。")
    async def slash_setprefix(self, interaction: discord.Interaction, prefix: str) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "setprefix"):
            return
        try:
            resp = await self.bot.cmd_setprefix(
                ssd_=self._ssd(interaction),
                prefix=prefix,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /language  (group)
    # -----------------------------------------------------------------------

    language = app_commands.Group(
        name="language",
        description="管理機器人在這個伺服器使用的語言。",
    )

    @language.command(name="show", description="顯示目前語言與可用的選項。")
    async def slash_language_show(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_perms(interaction, "language"):
            return
        try:
            resp = await self.bot.cmd_language(
                ssd_=self._ssd(interaction),
                subcmd="show",
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @language.command(name="set", description="設定這個伺服器使用的語言。")
    @app_commands.describe(locale="語言代碼，例如 en_US、zh_TW。")
    async def slash_language_set(self, interaction: discord.Interaction, locale: str) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "language"):
            return
        try:
            resp = await self.bot.cmd_language(
                ssd_=self._ssd(interaction),
                subcmd="set",
                lang_code=locale,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    @language.command(name="reset", description="把這個伺服器的語言重設為機器人預設語言。")
    async def slash_language_reset(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "language"):
            return
        try:
            resp = await self.bot.cmd_language(
                ssd_=self._ssd(interaction),
                subcmd="reset",
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /setavatar  (owner-only)
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="setavatar",
        description="更改機器人的頭像。提供網址或附加一張圖片。",
    )
    @app_commands.describe(
        url="直接的圖片網址。",
        attachment="直接上傳一個圖片檔案。",
    )
    async def slash_setavatar(
        self,
        interaction: discord.Interaction,
        url: Optional[str] = None,
        attachment: Optional[discord.Attachment] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        if not url and not attachment:
            await interaction.followup.send(
                "❌ 你必須提供網址或附加一張圖片。", ephemeral=True
            )
            return
        try:
            import aiohttp
            thing = attachment.url if attachment else url
            timeout = aiohttp.ClientTimeout(total=10)
            if self.bot.user and self.bot.session:
                async with self.bot.session.get(thing, timeout=timeout) as res:
                    await self.bot.user.edit(avatar=await res.read())
            await interaction.followup.send(
                "已更改機器人的頭像。", ephemeral=True
            )
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /disconnect
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="disconnect",
        description="強制讓機器人斷開這個伺服器的語音連線。",
    )
    async def slash_disconnect(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "disconnect"):
            return
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            resp = await self.bot.cmd_disconnect(guild=guild)
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /restart  (owner-only group)
    # -----------------------------------------------------------------------

    restart = app_commands.Group(
        name="restart",
        description="以不同方式重啟機器人。僅限擁有者。",
        default_permissions=discord.Permissions(administrator=True),
    )

    async def _restart(self, interaction: discord.Interaction, opt: str) -> None:
        if not await self._owner_check(interaction):
            return
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
            return
        _player = self.bot.get_player_in(guild)
        try:
            await self.bot.cmd_restart(
                _player=_player,
                guild=guild,
                channel=interaction.channel,
                opt=opt,
            )
        except (exceptions.RestartSignal, exceptions.TerminateSignal):
            raise
        except Exception as e:
            await self._err(interaction, e)

    @restart.command(name="soft", description="重新載入機器人，不做完整的程序重啟。")
    async def slash_restart_soft(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("♻️ 重啟中（軟重啟）…", ephemeral=True)
        await self._restart(interaction, "soft")

    @restart.command(name="full", description="完整重啟機器人程序。")
    async def slash_restart_full(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("♻️ 重啟中（完整重啟）…", ephemeral=True)
        await self._restart(interaction, "full")

    @restart.command(name="uppip", description="更新 pip 套件後完整重啟。")
    async def slash_restart_uppip(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("📦 正在更新 pip 並重啟…", ephemeral=True)
        await self._restart(interaction, "uppip")

    @restart.command(name="upgit", description="用 git 更新機器人程式碼後完整重啟。")
    async def slash_restart_upgit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("🔄 正在透過 git 更新並重啟…", ephemeral=True)
        await self._restart(interaction, "upgit")

    @restart.command(name="upgrade", description="更新所有東西（pip + git）後完整重啟。")
    async def slash_restart_upgrade(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("⬆️ 正在升級所有東西並重啟…", ephemeral=True)
        await self._restart(interaction, "upgrade")

    # -----------------------------------------------------------------------
    # /shutdown  (owner-only)
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="shutdown",
        description="斷開所有語音頻道連線並關閉機器人。",
    )
    async def slash_shutdown(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
            return
        await interaction.followup.send("👋 關閉中…", ephemeral=True)
        try:
            await self.bot.cmd_shutdown(guild=guild, channel=interaction.channel)
        except exceptions.TerminateSignal:
            raise

    # -----------------------------------------------------------------------
    # /leaveserver  (owner-only)
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="leaveserver",
        description="用名稱或 ID 強制讓機器人離開某個伺服器。",
    )
    @app_commands.describe(server="伺服器 ID（建議）或完整的伺服器名稱。")
    async def slash_leaveserver(self, interaction: discord.Interaction, server: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_leaveserver(
                ssd_=self._ssd(interaction),
                val=server,
                leftover_args=[],
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # =======================================================================
    # BATCH 6  (final)
    # checkupdates, uptime, botlatency, latency, botversion, setcookies
    # Dev-only commands excluded: testready, breakpoint, objgraph, debug,
    #                             makemarkdown, makeini
    # =======================================================================

    # -----------------------------------------------------------------------
    # /checkupdates  (owner-only)
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="checkupdates",
        description="檢查 MusicBot 原始碼與相依套件是否有更新。",
    )
    async def slash_checkupdates(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_checkupdates(
                ssd_=self._ssd(interaction),
                channel=interaction.channel,
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /uptime
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="uptime",
        description="顯示 MusicBot 自上次啟動以來上線了多久。",
    )
    async def slash_uptime(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "uptime"):
            return
        try:
            resp = await self.bot.cmd_uptime(ssd_=self._ssd(interaction))
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /botlatency  (owner-only — all voice clients)
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="botlatency",
        description="顯示所有已連線伺服器的 API 與語音延遲。",
    )
    async def slash_botlatency(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_botlatency(ssd_=self._ssd(interaction))
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /latency  (this guild only)
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="latency",
        description="顯示這個伺服器的 API 與語音延遲。",
    )
    async def slash_latency(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not await self._check_perms(interaction, "latency"):
            return
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("這個指令只能在伺服器中使用。", ephemeral=True)
                return
            resp = await self.bot.cmd_latency(
                ssd_=self._ssd(interaction),
                guild=guild,
            )
            await self._send(interaction, resp)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /botversion
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="botversion",
        description="顯示目前的 MusicBot 版本。",
    )
    async def slash_botversion(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._check_perms(interaction, "botversion"):
            return
        try:
            resp = await self.bot.cmd_botversion(ssd_=self._ssd(interaction))
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    # -----------------------------------------------------------------------
    # /setcookies  (owner-only)
    # Original relies on message.attachments. Slash version accepts a
    # discord.Attachment directly and bypasses cmd_setcookies for uploads,
    # handling the file save inline. on/off subcommands call cmd_setcookies.
    # -----------------------------------------------------------------------

    setcookies = app_commands.Group(
        name="setcookies",
        description="管理 yt-dlp 使用的 cookies。僅限擁有者。",
        default_permissions=discord.Permissions(administrator=True),
    )

    @setcookies.command(name="on", description="啟用先前上傳過的 cookies.txt。")
    async def slash_setcookies_on(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_setcookies(
                ssd_=self._ssd(interaction),
                message=None,
                opt="on",
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @setcookies.command(name="off", description="停用 cookies，但不刪除檔案。")
    async def slash_setcookies_off(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            resp = await self.bot.cmd_setcookies(
                ssd_=self._ssd(interaction),
                message=None,
                opt="off",
            )
            await self._send(interaction, resp, ephemeral=True)
        except Exception as e:
            await self._err(interaction, e)

    @setcookies.command(
        name="upload",
        description="上傳新的 cookies.txt 檔案。警告：風險請見 /help setcookies。",
    )
    @app_commands.describe(file="從瀏覽器匯出的 cookies.txt 檔案。")
    async def slash_setcookies_upload(
        self, interaction: discord.Interaction, file: discord.Attachment
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._owner_check(interaction):
            return
        try:
            # Remove any existing disabled cookies file first.
            if self.bot.config.disabled_cookies_path.is_file():
                try:
                    self.bot.config.disabled_cookies_path.unlink()
                except OSError as e:
                    log.warning("Could not remove old disabled cookies file: %s", e)

            # Download and save the attachment to cookies_path.
            try:
                await file.save(self.bot.config.cookies_path)
            except discord.HTTPException as e:
                raise exceptions.CommandError(
                    "從 Discord 下載 cookies 檔案時發生錯誤：%(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e
            except OSError as e:
                raise exceptions.CommandError(
                    "無法把 cookies 存到硬碟：%(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e

            if not self.bot.downloader.cookies_enabled:
                self.bot.downloader.enable_ytdl_cookies()

            await interaction.followup.send(
                "Cookies 已上傳並啟用。",
                ephemeral=True,
            )
        except Exception as e:
            await self._err(interaction, e)
