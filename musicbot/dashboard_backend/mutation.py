"""Queue mutation routes and web command responses."""
from __future__ import annotations


class DashboardMutationRoutes:

    async def play_selection(self, request, data, preview, guild, owner):
        from ..web_dashboard import APIError, CONFIRMED_ENTRY_CHECK, ConfirmedEntryCheck, ErrorResponse, _web_text, asyncio, denial_text, exceptions, log, normalize_query, time, urlsplit
        permissions = self.bot.permissions.for_user(owner)
        reason = self.playlist_restriction(permissions, preview["count"])
        if reason:
            raise APIError(403, reason)
        # Validate the entire selection before any provider work or queue change,
        # including saved tracks written by older dashboard versions.
        chosen = [dict(item, url=normalize_query(item["url"]))
                  for item in preview["entries"]
                  if item["item_id"] in data["selected_items"]]
        preview["status"], preview["selection"] = "submitted", data["selected_items"]
        results = []
        first_response = None
        deadline = time.monotonic() + self.BATCH_TIMEOUT
        for item in chosen:
            error = ""
            success = False
            def validate(info):
                # Called inside _cmd_play AFTER extraction and before queue mutation.
                candidate = info
                if info.has_entries:
                    # Native Spotify processing searches for one matching video.
                    # Downloader merges that video into the parent but retains
                    # the one-child search entries. Accept only its already
                    # flattened video shape; genuine/nested playlists still fail.
                    source = urlsplit(item["url"])
                    parts = source.path.strip("/").split("/")
                    children = info.get_entries_objects()
                    spotify_single = (
                        source.hostname == "open.spotify.com" and len(parts) == 2
                        and parts[0] == "track" and info.ytdl_type in ("video", "url", "")
                        and len(children) == 1 and not children[0].has_entries
                        and children[0].extractor == info.extractor
                        and info.extractor == "youtube"
                        and info.video_id == children[0].video_id
                        and info.webpage_url == children[0].webpage_url
                    )
                    if not spotify_single:
                        raise APIError(403, _web_text('m0438'))
                    candidate = children[0]
                if self.discord_auth:
                    self.authenticate(request)
                current_guild, member = self.guild_owner(request)
                perms = self.bot.permissions.for_user(member)
                self.command_permission(member, perms, "play", item["url"])
                if self.discord_auth:
                    self.voice_permission(current_guild, member, perms, "play")
                why = self.playlist_restriction(perms, preview["count"])
                player = self.bot.get_player_in(current_guild)
                self.addition_checks(player, member, perms)
                why = (why or self.restriction(info, perms, playlist=True)
                       or self.restriction(candidate, perms, playlist=True))
                if why:
                    raise APIError(403, why)
                return perms
            check = ConfirmedEntryCheck(validate)
            try:
                if not item.get("allowed", True):
                    raise APIError(403, item.get("reason") or _web_text('m0439'))
                if preview.get("fresh_reason"):
                    raise APIError(403, preview["fresh_reason"])
                if self.discord_auth:
                    self.authenticate(request)
                guild, owner = self.guild_owner(request)
                player, permissions, channel = await self.context(
                    guild, owner, "play", item["url"])
                reason = self.playlist_restriction(permissions, preview["count"])
                if reason:
                    raise APIError(403, reason)
                self.addition_checks(player, owner, permissions)
                self.bot._do_song_blocklist_check(preview["url"])
                self.bot._do_song_blocklist_check(item["url"])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                token = CONFIRMED_ENTRY_CHECK.set(check)
                try:
                    response = await self.run_resolution(guild, self.bot.cmd_play(
                        message=None, player=player, channel=channel, guild=guild,
                        author=owner, permissions=permissions, leftover_args=[],
                        song_url=item["url"]), owner=owner, priority="add", request=request,
                        timeout=min(self.SONG_TIMEOUT, remaining))
                finally:
                    CONFIRMED_ENTRY_CHECK.reset(token)
                if isinstance(response, ErrorResponse):
                    raise APIError(409, denial_text(response.description or ""))
                if first_response is None:
                    first_response = response
                success = True
            except APIError as exc:
                # A revoked session is an HTTP authentication failure, including
                # personal-library playback; never hide it in a skipped summary.
                if exc.status == 401:
                    raise
                error = str(exc)
            except exceptions.MusicbotException as exc:
                error = denial_text(exc.message % exc.fmt_args)
            except asyncio.TimeoutError:
                error = _web_text('m0440')
            except Exception as exc:
                log.warning("Dashboard selected play failed (%s)", type(exc).__name__)
                error = _web_text('m0441')
            # The command records the actual enqueue before preparing its response.
            # Other Discord/web requests cannot be mistaken for this selection.
            added = success or check.enqueued
            results.append({"item_id": item["item_id"], "title": item["title"],
                            "added": bool(added), "reason": error})
        added = sum(item["added"] for item in results)
        summary = {"added": added, "skipped": len(results) - added, "results": results}
        preview["summary"], preview["status"] = summary, "done"
        if added and first_response is not None:
            from ..bot import build_play_response
            response = build_play_response(
                self.bot.server_data[guild.id], number=added, track="",
                position=getattr(first_response, "queue_position_text", ""), playlist=True)
            await self.send_web_response(request, guild, owner, response, "play")
        return summary

    async def send_web_response(self, request, guild, owner, response, command):
        """Reuse the native Response and safe sender, including auto deletion."""
        from ..web_dashboard import Response, _D, asyncio, log
        if not hasattr(self.bot, "safe_send_message"):
            return
        try:
            if self.discord_auth:
                self.authenticate(request)
                guild, owner = self.guild_owner(request)
            channel = self.channel_for(guild, owner)
            import discord
            name = str(getattr(owner, "display_name", None) or owner.name).replace("\n", " ").replace("\r", " ")[:128]
            name = discord.utils.escape_mentions(discord.utils.escape_markdown(name))
            ssd = self.bot.server_data[guild.id]
            prefix = _D("%(name)s requested music via the web dashboard" if command in ("play", "playnext")
                        else "%(name)s used the web dashboard", ssd) % {"name": name}
            plain = Response("-# " + prefix + "\n" + response.content,
                             force_text=True, delete_after=response.delete_after)
            plain.dashboard_no_mentions = True
            await asyncio.wait_for(self.bot.safe_send_message(channel, plain), 10)
        except Exception as exc:
            log.warning("Dashboard Discord response failed (%s)", type(exc).__name__)

    async def mutate(self, request):
        from ..web_dashboard import APIError, _web_text, asyncio
        data = await self.payload(request)
        guild, owner = self.guild_owner(request)
        if request.path.rsplit("/", 1)[-1] in ("play", "playnext"):
            self.user_rate_limit(owner)
        token = data.get("preview_id")
        preview = self.previews.get(token) if isinstance(token, str) else None
        if (request.path.rsplit("/", 1)[-1] in ("play", "playnext") and preview
                and preview["guild_id"] == guild.id and preview["owner_id"] == owner.id):
            # Idempotent confirmation/expiry renewal is serialized only for this
            # exact preview. Unrelated people and playback controls remain free.
            lock = preview.setdefault("confirmation_lock", asyncio.Lock())
            try:
                await asyncio.wait_for(lock.acquire(), self.RESOLVE_QUEUE_TIMEOUT)
            except asyncio.TimeoutError:
                raise APIError(429, _web_text('resolve.queueTimeout')) from None
            try:
                return await self._mutate(request, data)
            finally:
                lock.release()
        return await self._mutate(request, data)

    async def _mutate(self, request, data):
        from ..web_dashboard import ACTIVITY_KEY, APIError, CONFIRMED_ENTRY_CHECK, ConfirmedEntryCheck, ErrorResponse, Response, _D, _web_text, capture, denial_text, math, normalize_query, revision, web
        guild, owner = self.guild_owner(request)
        action = request.path.rsplit("/", 1)[-1]
        if request.method == "DELETE":
            action = "remove"
        if action in ("play", "playnext"):
            if "selected_items" in data and "preview_id" not in data:
                raise APIError(400, _web_text('m0445'))
            query = normalize_query(self.query(data))
            data["query"] = query
        elif action == "seek":
            position = data.get("position")
            try:
                valid = (not isinstance(position, bool) and isinstance(position, (int, float))
                         and math.isfinite(float(position)) and position >= 0)
            except (ValueError, TypeError, OverflowError):
                valid = False
            if not valid:
                raise APIError(400, _web_text('m0446'))
            # Normalize once before permissions, queue mutation and reporting.
            # Non-negative values use conventional half-up rather than bankers rounding.
            data["position"] = math.floor(float(position) + 0.5)
            # Capture before the guild lock: native Discord playback is not
            # serialized by this lock, and context() may await a voice lookup.
            seek_player = self.bot.get_player_in(guild)
            seek_entry = getattr(seek_player, "current_entry", None)
            if ("track_token" in data
                    and data["track_token"] != self.track_token(seek_player)):
                raise APIError(409, _web_text('m0447'))
        elif action == "volume":
            self.integer(data, "volume", 1, 100)
        elif action == "repeat" and data.get("mode") not in ("off", "song", "all"):
            raise APIError(400, _web_text('m0448'))

        from contextlib import nullcontext
        # Provider waits must not hold the guild control lock. Fresh confirmed
        # checks still run immediately before native enqueue (no await in between).
        async with (nullcontext() if action in ("play", "playnext") else self.locks[guild.id]):
            request[ACTIVITY_KEY] = capture(self, guild, owner, action, "web")
            if action == "seek" and request[ACTIVITY_KEY] is not None:
                request[ACTIVITY_KEY].target_position = data["position"]
            if self.discord_auth:
                # Requests can queue behind another command; re-check current membership/session.
                self.authenticate(request)
                guild, owner = self.guild_owner(request)
            if action in ("play", "playnext") and "preview_id" not in data:
                await self.compatibility_preview(request, data, guild, owner, action)
                query = data["query"]
            sub = ""
            if self.discord_auth:
                sub = (query.split()[0] if action in ("play", "playnext") else
                       str(data.get("position", "")) if action == "seek" else
                       str(data.get("volume", "")) if action == "volume" else
                       {"song": "on", "all": "all", "off": "off"}.get(data.get("mode"), "") if action == "repeat" else
                       str(data.get("from", "")) if action == "move" else
                       request.match_info.get("position", "") if action == "remove" else "")
            preview = self.confirmed_preview(data, guild, owner) if action in ("play", "playnext") else None
            if preview:
                await self.renew_preview(request, data, preview, guild, owner, action)
            if action == "playnext" and (data.get("selected_items") is not None or (preview and preview.get("kind") == "playlist")):
                raise APIError(400, _web_text('m0415'))
            if preview and preview["status"] == "done" and not self.discord_auth:
                return web.json_response({"message": _web_text('m0449'),
                                          "state": self.snapshot(guild, owner), **(preview.get("summary") or {})})
            if self.discord_auth and action == "repeat":
                current = self.bot.get_player_in(guild)
                if current is not None:
                    subs = self.repeat_commands(current, data["mode"])
                    sub = subs[0] if subs else sub
            player, permissions, channel = await self.context(guild, owner, action, sub)
            if action == "seek" and (player is not seek_player or player.current_entry is not seek_entry):
                raise APIError(409, _web_text('m0447'))
            if self.discord_auth:
                self.authenticate(request)
                guild, owner = self.guild_owner(request)
            if preview and preview["status"] == "done":
                return web.json_response({"message": _web_text('m0449'),
                                          "state": self.snapshot(guild, owner), **(preview.get("summary") or {})})
            ssd = self.bot.server_data[guild.id]
            if action in ("remove", "move", "shuffle"):
                if not data.get("revision") or data["revision"] != revision(player):
                    raise APIError(409, _web_text('m0450'))
            response = None
            summary = {}
            if action == "play" and preview and preview.get("kind") == "playlist":
                summary = await self.play_selection(request, data, preview, guild, owner)
                reasons = list(dict.fromkeys(item["reason"] for item in summary["results"] if item["reason"]))
                response = Response(_D("Added %(added)s tracks; skipped %(skipped)s.", ssd) %
                                    {"added":summary["added"],"skipped":summary["skipped"]})
            elif action in ("play", "playnext"):
                if preview:
                    preview["status"] = "submitted"
                def validate_next(info):
                    if info.has_entries and (info.entry_count > 1 or "search" not in str(info.extractor)):
                        raise APIError(403, _web_text('m0415'))
                    if self.discord_auth:
                        self.authenticate(request)
                    current_guild, member = self.guild_owner(request)
                    perms = self.bot.permissions.for_user(member)
                    self.command_permission(member, perms, action, query.split()[0])
                    if self.discord_auth:
                        self.voice_permission(current_guild, member, perms, action)
                    # context() may just have summoned this player.
                    current_player = self.bot.get_player_in(current_guild) or player
                    self.addition_checks(current_player, member, perms)
                    # Native duration_td.seconds drops complete days and fractions.
                    # Check the fresh selected track using its full duration before
                    # _cmd_play can enqueue; search wrappers may retain child data.
                    candidate = info
                    if info.has_entries:
                        children = info.get_entries_objects()
                        if not children or children[0].has_entries:
                            raise APIError(403, _web_text('m0452'))
                        candidate = children[0]
                    reason = self.restriction(candidate, perms, extractor=info.extractor)
                    if reason:
                        raise APIError(403, reason)
                    return perms
                check_token = CONFIRMED_ENTRY_CHECK.set(ConfirmedEntryCheck(validate_next))
                try:
                    response = await self.run_resolution(guild, getattr(self.bot, "cmd_" + action)(
                        message=None, player=player, channel=channel, guild=guild,
                        author=owner, permissions=permissions, leftover_args=[],
                        song_url=query.strip()), owner=owner, priority="add", request=request)
                finally:
                    CONFIRMED_ENTRY_CHECK.reset(check_token)
            elif action == "seek":
                if not player.current_entry:
                    raise APIError(409, _web_text('m0378'))
                if not self.is_seekable(player.current_entry):
                    raise APIError(400, _web_text('m0453'))
                if position > player.current_entry.duration or data["position"] > player.current_entry.duration:
                    raise APIError(400, _web_text('m0454'))
                response = await self.bot.cmd_seek(
                    ssd_=ssd, guild=guild, player=player, leftover_args=[],
                    seek_time=str(data["position"]))
                # Native seek intentionally accepts fractional Discord arguments;
                # dashboard reporting shares the activity log integer format.
                response = Response(_D("Seek: %(seconds)s seconds", ssd) % {"seconds": data["position"]})
            elif action in ("pause", "resume"):
                response = await getattr(self.bot, "cmd_" + action)(ssd, player)
            elif action == "skip":
                response = await self.bot.cmd_skip(
                    ssd_=ssd, guild=guild, player=player, author=owner,
                    message=None, permissions=permissions,
                    voice_channel=player.voice_client.channel, param="")
            elif action == "volume":
                response = await self.bot.cmd_volume(ssd, player, str(data["volume"]))
            elif action == "repeat":
                if not player.current_entry:
                    raise APIError(409, _web_text('m0378'))
                mode = data["mode"]
                if self.discord_auth:
                    # Target mode may require multiple original repeat subcommands.
                    for repeat_sub in self.repeat_commands(player, mode):
                        self.command_permission(owner, permissions, "repeat", repeat_sub)
                if player.repeatsong and mode != "song":
                    response = await self.bot.cmd_repeat(ssd, player, "off")
                if player.loopqueue and mode != "all":
                    response = await self.bot.cmd_repeat(ssd, player, "all")
                if mode == "song" and not player.repeatsong:
                    response = await self.bot.cmd_repeat(ssd, player, "on")
                if mode == "all" and not player.loopqueue:
                    response = await self.bot.cmd_repeat(ssd, player, "all")
            elif action == "remove":
                position = request.match_info["position"]
                if not position.isdigit() or int(position) < 1:
                    raise APIError(400, _web_text('m0456'))
                index = int(position) - 1
                if index >= len(player.playlist.entries):
                    raise APIError(400, _web_text('m0457'))
                removed = player.playlist.entries[index]
                response = await self.bot.cmd_remove(
                    ssd_=ssd, user_mentions=[], author=owner,
                    permissions=permissions, player=player,
                    leftover_args=[], position=position)
                if not isinstance(response, ErrorResponse):
                    summary = self.remember_removal(guild, owner, removed, index)
                    response = Response(_D("Removed %(title)s", ssd) % {"title": str(removed.title)})
            elif action == "move":
                if self.discord_auth and not player.current_entry:
                    raise APIError(409, _web_text('m0378'))
                size = len(player.playlist.entries)
                source = self.integer(data, "from", 1, size) - 1
                target = self.integer(data, "to", 1, size) - 1
                # Same Playlist primitives as cmd_move, without its awaited
                # Discord animation/message before the mutation (race window).
                entry = player.playlist.delete_entry_at_index(source)
                player.playlist.insert_entry_at_index(target, entry)
                if self.discord_auth:
                    response = Response(_D("Moved track %(source)s to position %(target)s.", ssd) % {"source":source+1,"target":target+1})
            elif action == "shuffle":
                player.playlist.shuffle()
                if self.discord_auth:
                    response = Response(_D("Queue shuffled.", ssd))
            if isinstance(response, ErrorResponse):
                raise APIError(409, denial_text(response.description or _web_text('m0461')))
            if self.discord_auth:
                self.authenticate(request)
                guild, owner = self.guild_owner(request)
            if action in ("remove", "move", "shuffle"):
                await self.bot.serialize_queue(guild)
            if preview:
                preview["status"] = "done"
            message = _web_text("m0451", p0=summary["added"], p1=summary["skipped"]) if summary and "added" in summary else _web_text("m0462")
            if action == "skip":
                message = _web_text("message.skip")
            elif action == "repeat":
                message = _web_text("m0117") + _web_text({"off":"m0118","song":"m0115","all":"m0119"}[data["mode"]])
            if response is not None and (not summary or action == "remove"):
                if action == "remove":
                    message = _web_text("message.removed", p0=str(removed.title))
                await self.send_web_response(request, guild, owner, response, action)
            return web.json_response({"message": message, "state": self.snapshot(guild, owner), **summary})
