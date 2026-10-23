"""Queue authorization and command payload helpers."""
from __future__ import annotations


class DashboardRequestSupport:

    def note_queue_entry(self, guild, entry):
        """Observe member requests/insertion order; never mutate the playlist."""
        author = getattr(entry, "author", None)
        if (author is not None and getattr(author, "id", None) is not None
                and not getattr(author, "bot", False)
                and not getattr(entry, "from_auto_playlist", False)):
            # Runtime-only identity is never returned to another viewer.
            # Bound the cache and preserve recency of active members.
            self.last_requested_guild.pop(author.id, None)
            self.last_requested_guild[author.id] = guild.id
            while len(self.last_requested_guild) > 5000:
                self.last_requested_guild.pop(next(iter(self.last_requested_guild)))
        player = self.bot.get_player_in(guild)
        entries = list(player.playlist.entries) if player else []
        live = {id(item) for item in entries}
        known = self.queue_arrivals[guild.id]
        known[:] = [key for key in known if key in live and key != id(entry)]
        known_ids = set(known)
        known.extend(id(item) for item in entries
                     if id(item) != id(entry) and id(item) not in known_ids)
        if id(entry) in live:
            known.append(id(entry))

    def channel_for(self, guild, owner):
        from ..web_dashboard import APIError, ChannelType, _web_text
        bound = self.bot.config.bound_channels
        has_bound = any(c.id in bound for c in guild.channels)
        restrict = bool(bound) and (has_bound or not self.bot.config.unbound_servers)
        player = self.bot.get_player_in(guild)
        current = getattr(player, "current_entry", None)
        # Queue order can be moved/shuffled. Object identity insertion order is
        # tracked below, so "latest requested" does not mean "last in queue".
        entries = list(player.playlist.entries) if player else []
        known = self.queue_arrivals[guild.id]
        live = {id(entry) for entry in entries}
        known[:] = [key for key in known if key in live]
        known_ids = set(known)
        known.extend(id(entry) for entry in entries if id(entry) not in known_ids)
        by_id = {id(entry): entry for entry in entries}
        latest = by_id.get(known[-1]) if known else None
        voice = getattr(getattr(owner, "voice", None), "channel", None)
        candidates = ([getattr(current, "channel", None), getattr(latest, "channel", None)]
                      + [self.notification_channel(guild)]
                      + [guild.get_channel(cid) for cid in sorted(bound)]
                      + [guild.system_channel] + list(guild.text_channels) + [voice])
        # An older web request may itself have stored a voice chat as
        # entry.channel. Voice chat remains the last fallback in that case too.
        preferred = [channel for channel in candidates[:-1]
                     if channel is not None
                     and getattr(channel, "type", None) not in (ChannelType.voice, ChannelType.stage_voice)
                     and getattr(channel, "id", None) != getattr(voice, "id", None)]
        candidates = preferred + [voice]
        seen = set()
        for channel in candidates:
            if channel is not None and channel.id in seen:
                continue
            if channel is not None:
                seen.add(channel.id)
            if (channel is None or getattr(channel, "guild", None) != guild
                    or not hasattr(channel, "typing")
                    or (restrict and channel.id not in bound)):
                continue
            member_perms = channel.permissions_for(owner)
            bot_perms = channel.permissions_for(guild.me)
            if (member_perms.view_channel and member_perms.send_messages
                    and bot_perms.view_channel and bot_perms.send_messages):
                return channel
        raise APIError(403, _web_text('m0392'))

    def command_permission(self, member, permissions, command, sub=""):
        from ..web_dashboard import APIError, _web_text
        if (member.id != self.bot.config.owner_id
                and not permissions.can_use_command(command, sub)):
            raise APIError(403, _web_text('m0393'))

    def bot_voice_channel(self, guild):
        voice = getattr(getattr(guild, "me", None), "voice", None)
        if voice and voice.channel:
            return voice.channel
        player = self.bot.get_player_in(guild)
        client = getattr(player, "voice_client", None)
        if client and getattr(client, "is_connected", lambda: True)():
            return client.channel
        return None

    def voice_permission(self, guild, member, permissions, command):
        from ..web_dashboard import APIError, _web_text
        if not member.voice or not member.voice.channel:
            raise APIError(409, _web_text('m0348'))
        bot_channel = self.bot_voice_channel(guild)
        if bot_channel is not None:
            if bot_channel.id != member.voice.channel.id:
                raise APIError(403, _web_text('m0394'))
        elif command not in ("play", "playnext"):
            raise APIError(409, _web_text('m0395'))
        elif not permissions.summonplay:
            raise APIError(403, _web_text('m0396'))

    async def context(self, guild, owner, command, sub=""):
        from ..web_dashboard import APIError, SimpleNamespace, _web_text
        permissions = self.bot.permissions.for_user(owner)
        self.command_permission(owner, permissions, command, sub)
        if self.discord_auth or command in ("seek", "playnext"):
            self.voice_permission(guild, owner, permissions, command)
        elif not owner.voice or not owner.voice.channel:
            raise APIError(409, _web_text('m0397'))
        if permissions.ignore_non_voice and command in permissions.ignore_non_voice:
            await self.bot._check_ignore_non_voice(
                SimpleNamespace(guild=guild, author=owner))
        channel = self.channel_for(guild, owner)
        player = await self.bot.get_player(
            owner.voice.channel, create=permissions.summonplay if command in ("play", "playnext") else False)
        if self.discord_auth:
            # Membership, roles and voice may change while a connection is awaited.
            owner = guild.get_member(owner.id)
            if owner is None:
                raise APIError(403, _web_text('m0369'))
            self.check_blocked(owner)
            permissions = self.bot.permissions.for_user(owner)
            self.command_permission(owner, permissions, command, sub)
            self.voice_permission(guild, owner, permissions, command)
            channel = self.channel_for(guild, owner)
            if not player or not getattr(player, "voice_client", None):
                raise APIError(409, _web_text('m0395'))
        return player, permissions, channel

    @staticmethod
    def repeat_commands(player, mode):
        subs = []
        if player.repeatsong and mode != "song":
            subs.append("off")
        if player.loopqueue and mode != "all":
            subs.append("all")
        if mode == "song" and not player.repeatsong:
            subs.append("on")
        if mode == "all" and not player.loopqueue:
            subs.append("all")
        return subs

    def user_rate_limit(self, member):
        from ..web_dashboard import APIError, _web_text, time
        if not self.discord_auth:
            return
        now = time.monotonic()
        self.rate_limits = {uid: [t for t in times if t > now - 60]
                            for uid, times in self.rate_limits.items()
                            if times and times[-1] > now - 60}
        times = self.rate_limits.setdefault(member.id, [])
        if len(times) >= self.USER_REQUESTS_PER_MINUTE:
            raise APIError(429, _web_text('m0398'))
        times.append(now)

    @staticmethod
    def integer(data, key, minimum, maximum):
        from ..web_dashboard import APIError, _web_text
        value = data.get(key)
        if type(value) is not int or not minimum <= value <= maximum:
            raise APIError(400, _web_text('m0399', p0=key, p1=minimum, p2=maximum))
        return value

    @staticmethod
    async def payload(request):
        from ..web_dashboard import APIError, _web_text, json
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise APIError(400, _web_text('m0400')) from None
        if not isinstance(data, dict):
            raise APIError(400, _web_text('m0401'))
        return data

    @staticmethod
    def query(data):
        from ..web_dashboard import APIError, _web_text
        value = data.get("query")
        if not isinstance(value, str) or not 0 < len(value.strip()) <= 2000:
            raise APIError(400, _web_text('m0402'))
        return value.strip()

    def preview_player(self, guild):
        from ..web_dashboard import SimpleNamespace
        # No get_player/context here: resolving must never summon or join voice.
        return self.bot.get_player_in(guild) or SimpleNamespace(
            karaoke_mode=False, playlist=SimpleNamespace(count_for_user=lambda _: 0))

    def addition_checks(self, player, owner, permissions):
        from ..web_dashboard import APIError, _web_text
        if (not self.discord_auth and owner.id != self.bot.config.owner_id
                and not permissions.can_use_command("play")):
            raise APIError(403, _web_text('m0403'))
        if (permissions.max_songs and
                player.playlist.count_for_user(owner) >= permissions.max_songs):
            raise APIError(403, _web_text('m0341'))
        if player.karaoke_mode and not permissions.bypass_karaoke_mode:
            raise APIError(403, _web_text('m0346'))

    @staticmethod
    def info_duration(info):
        from ..web_dashboard import math
        try:
            value = float(info.get("duration") or 0)
            return max(0, value) if math.isfinite(value) else 0
        except (TypeError, ValueError):
            return 0

    def restriction(self, info, permissions, *, playlist=False, extractor=""):
        from ..web_dashboard import _web_text, exceptions, public_url
        # Same blocklist/extractor gates as _cmd_play and Playlist.import_from_info.
        try:
            self.bot._do_song_blocklist_check(info.url)
            self.bot._do_song_blocklist_check(info.webpage_url or info.get_playable_url())
            self.bot._do_song_blocklist_check(info.title)
        except exceptions.MusicbotException:
            return _web_text('m0404')
        try:
            permissions.can_use_extractor(info.extractor or extractor)
        except exceptions.MusicbotException:
            return _web_text('m0405')
        duration = self.info_duration(info)
        if permissions.max_song_length and duration > permissions.max_song_length:
            return _web_text('m0406', p0=format(duration, 'g'), p1=permissions.max_song_length)
        if playlist and info.title.lower() in ("[private video]", "[deleted video]"):
            return _web_text('m0407')
        if not public_url(info.webpage_url or info.get_playable_url()):
            return _web_text('m0408')
        return ""

    def preview_track(self, info, permissions, *, playlist=False, extractor=""):
        from ..web_dashboard import _web_text, public_url
        reason = self.restriction(info, permissions, playlist=playlist, extractor=extractor)
        return dict(title=info.title, duration=self.info_duration(info),
                    thumbnail=public_url(info.thumbnail_url),
                    url=public_url(info.webpage_url or info.get_playable_url()),
                    allowed=not reason, reason=reason,
                    warning="" if self.info_duration(info) else _web_text('m0409'))
