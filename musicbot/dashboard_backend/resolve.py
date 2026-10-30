"""Bounded dashboard URL resolution and preview routes."""
from __future__ import annotations


class DashboardResolveRoutes:

    async def resolve_options(self, guild, owner, query, action="play"):
        from ..web_dashboard import APIError, Spotify, _web_text, exceptions, get_compound_link_ids, normalize_query, public_url, urlsplit, video_id, youtube_playlist_subject
        permissions = self.bot.permissions.for_user(owner)
        player = self.preview_player(guild)
        self.addition_checks(player, owner, permissions)
        if self.discord_auth:
            self.command_permission(owner, permissions, action, query.split()[0])
        try:
            self.bot._do_song_blocklist_check(query)
        except exceptions.MusicbotException:
            raise APIError(403, _web_text('m0411')) from None
        query = normalize_query(query)
        parsed = urlsplit(query)
        if (parsed.scheme and parsed.scheme not in ("http", "https")
                and ("://" in query or parsed.scheme in ("file", "data", "javascript", "spotify"))):
            raise APIError(400, _web_text('m0410'))
        valid_url = self.bot.downloader.get_url_or_none(query)
        # Split combined links into explicit choices, eliminating reaction prompts.
        playlist_id, video_id = get_compound_link_ids(query)
        if playlist_id:
            subjects = [(query if action == "play" else "https://www.youtube.com/watch?v=" + video_id, False)]
        elif valid_url:
            subjects = [(valid_url, False)]
        else:
            limit = getattr(permissions, "max_search_items", self.SEARCH_LIMIT)
            limit = min(self.SEARCH_LIMIT, limit) if limit > 0 else self.SEARCH_LIMIT
            subjects = [(f"{self.bot.config.default_search_service}{limit}:{query}", True)]
        results = []
        for subject, search in subjects:
            try:
                self.bot._do_song_blocklist_check(query)
                self.bot._do_song_blocklist_check(subject)
            except exceptions.MusicbotException:
                raise APIError(403, _web_text('m0411')) from None
            if "open.spotify.com" in subject.lower():
                if not self.bot.config.spotify_enabled:
                    raise APIError(403, _web_text('m0412'))
                if not Spotify.is_url_supported(subject):
                    raise APIError(400, _web_text('m0413'))
            imported = None
            from ..web_dashboard_imports import source_url
            try:
                canonical, kind = source_url(subject)
            except APIError:
                canonical = None
                # Malformed YouTube lists must not fall back to native cookies.
                if youtube_playlist_subject(subject):
                    raise
            if canonical:
                imported = await self.import_source(canonical, kind)
                extractor = "spotify:musicbot" if kind == "spotify" else "youtube"
                from ..downloader import YtdlpResponseDict
                info = YtdlpResponseDict({"title": imported["title"], "extractor": extractor,
                    "__input_subject": canonical, "webpage_url": canonical,
                    "playlist_count": imported["count"], "entries": [
                        dict(item, webpage_url=item["url"], extractor=extractor,
                             __input_subject=item["url"]) for item in imported["tracks"]]})
                subject = canonical
            else:
                # Restrict cross-request reuse to a direct, complete single URL.
                # Search/playlist/Spotify choices still resolve only selected items.
                import asyncio
                import time
                from ..web_dashboard_reuse import CompleteInfoCache, log
                from ..downloader import YtdlpResponseDict
                direct = bool(callable(getattr(getattr(self.bot.downloader, '_cookie_clients', None), 'snapshot', None))
                              and valid_url and not imported and not search
                              and 'open.spotify.com' not in subject.lower()
                              and not youtube_playlist_subject(subject))
                token = None
                if direct:
                    client = (await asyncio.to_thread(
                        self.bot.downloader._cookie_clients.snapshot, refresh=True))[0]
                    cache = self.__dict__.setdefault('_complete_info_cache', CompleteInfoCache())
                    generation, settings = cache.scope(client, getattr(self.bot.downloader._cookie_clients, 'options', {}))
                    token = (guild.id, owner.id, generation, settings, subject)
                    cached, reason = cache.get(token, subject)
                    log.info('Complete URL metadata cache: %s', reason)
                else:
                    cached = None
                if cached is not None:
                    info = YtdlpResponseDict(cached)
                else:
                    started = time.monotonic()
                    info = await self.bot.downloader.extract_info(
                        subject, download=False, process=True)
                    log.info('Provider complete URL extraction: %.3fs', time.monotonic()-started)
                    if direct and info:
                        cache.put(token, subject, info.data)
            if not info or ("entries" in info and not info.entry_count):
                raise APIError(404, _web_text('m0414'))
            try:
                permissions.can_use_extractor(info.extractor)
            except exceptions.MusicbotException:
                raise APIError(403, _web_text('m0405')) from None
            if search:
                from ..web_dashboard_search_quality import rank_search_results
                choices = info.get_entries_objects() if info.has_entries else [info]
                previews = [dict(self.preview_track(item, permissions, extractor=info.extractor), kind="track")
                            for item in choices[:limit]]
                results.extend(rank_search_results(query, previews))
            elif info.has_entries:
                count = max(info.playlist_count or 0, info.entry_count)
                reason = (_web_text('m0415')
                          if action == "playnext" else self.playlist_restriction(permissions, count))
                # Only retain/check the bounded subset we actually offer for selection.
                children = info.get_entries_objects()[:self.PREVIEW_LIMIT]
                items = [dict(self.preview_track(item, permissions, playlist=True,
                                                extractor=info.extractor),
                              item_id=str(i),
                              is_requested=bool(video_id and item.webpage_url == "https://www.youtube.com/watch?v=" + video_id),
                              default_selected=(not imported or not imported.get("is_mix") or i == 1))
                         for i, item in enumerate(children, 1)]
                eligible = sum(item["allowed"] for item in items)
                if not eligible and not reason:
                    reason = _web_text('m0416')
                results.append({
                    "kind": "playlist", "title": info.title, "url": subject,
                    "source_url": imported["source_url"] if imported else "",
                    "source_type": imported["source_type"] if imported else "",
                    "saveable": bool(imported), "is_mix": imported.get("is_mix", False) if imported else False,
                    "count_is_minimum": imported.get("count_is_minimum", False) if imported else False,
                    "thumbnail": public_url(info.thumbnail_url), "duration": 0,
                    "count": count, "checked_count": len(items), "eligible_count": eligible,
                    "entries": items, "allowed": not reason, "reason": reason,
                    "truncated": count > len(items), "limit": 25 if imported and imported.get("is_mix") else self.PREVIEW_LIMIT,
                    "warning": (_web_text('m0417') if imported and imported.get("is_mix") else "") +
                               (_web_text('m0418', p0=count, p1=len(items)) if imported and imported.get("count_is_minimum") else "") +
                               (_web_text('m0419', p0=self.PREVIEW_LIMIT) if count > len(items) else "") +
                               _web_text('m0420'),
                })
            else:
                from ..web_dashboard_preview import PreviewTrack, save_extraction
                item = PreviewTrack(self.preview_track(info, permissions), kind="track")
                if (valid_url and not playlist_id and not search and imported is None
                        and "open.spotify.com" not in subject.lower()
                        and not youtube_playlist_subject(subject) and "entries" not in info):
                    item.extraction, item.extraction_reason = save_extraction(info, subject, item["url"])
                results.append(item)
        if not results:
            raise APIError(404, _web_text('m0414'))
        return results

    RESOLVE_QUEUE_TIMEOUT = 15

    async def run_resolution(self, guild, operation, timeout_key="m0423", *,
                             owner, priority="lookup", request=None, timeout=None):
        """Admission lasts until cancellation has killed and reaped provider work."""
        return await self.resolution_queue.run(guild, owner, operation,
            priority=priority, request=request,
            timeout=self.RESOLVE_TIMEOUT if timeout is None else min(timeout, self.RESOLVE_TIMEOUT),
            timeout_key=timeout_key)

    async def resolution_status(self, request):
        from ..web_dashboard import web
        guild, owner = self.guild_owner(request)
        request_id = request.query.get("request_id", "")
        # No guild broadcast or SSE: authenticated person + guild + opaque local
        # request ID must ALL match. Never include queries, identities or counts.
        state = next(("resolving" if job.task is not None else "queued"
            for job in self.resolution_queue.jobs
            if request_id and job.request_id == request_id
            and job.owner_id == owner.id and job.guild_id == guild.id), None)
        return web.json_response({"state": state})

    async def resolve(self, request):
        from ..web_dashboard import APIError, ExtractionBudgetExceeded, UnsupportedDashboardURL, _web_text, exceptions, log, web
        data = await self.payload(request)
        query = self.query(data)
        action = data.get("action", "play")
        if action not in ("play", "playnext"):
            raise APIError(400, _web_text('m0421'))
        guild, owner = self.guild_owner(request)
        self.user_rate_limit(owner)
        try:
            results = await self.run_resolution(guild,
                self.resolve_options(guild, owner, query, action), owner=owner, request=request)
        except (APIError, exceptions.MusicbotException, UnsupportedDashboardURL, ExtractionBudgetExceeded):
            raise
        except Exception:
            log.warning("Dashboard preview extraction failed")
            raise APIError(502, _web_text('m0424')) from None
        if self.discord_auth:
            self.authenticate(request)
            guild, owner = self.guild_owner(request)
            self.command_permission(owner, self.bot.permissions.for_user(owner), action, query.split()[0])
        await self.issue_previews(guild, owner, results, query, action)
        return web.json_response({"results": results, "expires_in": self.PREVIEW_TTL})

    async def issue_previews(self, guild, owner, results, query, action):
        from ..web_dashboard import secrets, time
        now = time.monotonic()
        self.previews = {key: value for key, value in self.previews.items()
                         if value.get("retain_until", value["expires"]) > now}
        for item in results:
            token = secrets.token_urlsafe(24)
            item["preview_id"] = token
            self.previews[token] = {
                "guild_id": guild.id, "owner_id": owner.id, "url": item["url"],
                "allowed": item["allowed"], "expires": now + self.PREVIEW_TTL,
                "retain_until": now + 3600, "original_query": query, "action": action,
                "status": "ready", "kind": item["kind"],
                "count": item.get("count", 1),
                "entries": [dict(child) for child in item.get("entries", [])],
                "extraction_reason": getattr(item, "extraction_reason", "not-single-url"),
            }
            extraction = getattr(item, "extraction", None)
            if extraction is not None:
                self.previews[token]["extraction"] = extraction
                item.extraction = None
            if item.get("source_url") or item.get("saveable") or item.get("kind") == "playlist":
                value = await self.playlist_store.transact(owner.id)
                item["save_revision"] = value["revision"]
                self.import_previews[token] = {
                    "owner_id": owner.id, "guild_id": guild.id, "playlist_id": None,
                    "revision": value["revision"], "expires": now + self.PREVIEW_TTL,
                    "tracks": [dict(child) for child in item["entries"]],
                    "source_url": item["source_url"], "source_type": item["source_type"]}
        # Bounded memory even when many queries are made within the TTL.
        while len(self.previews) > 100:
            self.previews.pop(next(iter(self.previews)))
        from ..web_dashboard_preview import prune_extractions
        prune_extractions(self.previews, now)
        return results

    async def run_preview_add(self, guild, owner, request, preview, query, operation):
        from ..web_dashboard_preview import (PREVIEW_EXTRACTION, PreviewExtraction,
            load_extraction, log)
        data, reason = load_extraction(preview, query)
        preview.pop("extraction", None)
        if data is None:
            log.info("Dashboard add re-extracting preview: %s", reason)
            return await self.run_resolution(guild, operation, owner=owner,
                priority="add", request=request)
        scope = PreviewExtraction(data, lambda extraction: self.run_resolution(
            guild, extraction, owner=owner, priority="add", request=request))
        token = PREVIEW_EXTRACTION.set(scope)
        try:
            return await operation
        finally:
            scope.close()
            PREVIEW_EXTRACTION.reset(token)

    async def compatibility_preview(self, request, data, guild, owner, action):
        """Old one-request clients use the same preview and guarded confirmation."""
        from ..web_dashboard import APIError, _web_text
        query = data["query"]
        # Preserve the old command's voice/text-channel admission before providers.
        permissions = self.bot.permissions.for_user(owner)
        self.command_permission(owner, permissions, action, query.split()[0])
        if self.discord_auth:
            self.voice_permission(guild, owner, permissions, action)
        elif not owner.voice or not owner.voice.channel:
            raise APIError(409, _web_text('m0397'))
        self.channel_for(guild, owner)
        results = await self.run_resolution(guild,
            self.resolve_options(guild, owner, query, action), owner=owner, priority="add", request=request)
        if self.discord_auth:
            self.authenticate(request)
        guild, owner = self.guild_owner(request)
        permissions = self.bot.permissions.for_user(owner)
        self.command_permission(owner, permissions, action, query.split()[0])
        if self.discord_auth:
            self.voice_permission(guild, owner, permissions, action)
        self.addition_checks(self.preview_player(guild), owner, permissions)
        selected = results[0]  # Legacy keyword requests still choose the first match.
        if not selected["allowed"]:
            raise APIError(403, selected["reason"] or _web_text('m0426'))
        if (selected["kind"] == "playlist" and permissions.max_songs
                and self.preview_player(guild).playlist.count_for_user(owner)
                    + selected["eligible_count"] > permissions.max_songs):
            raise APIError(403, _web_text('m0341'))
        await self.issue_previews(guild, owner, [selected], query, action)
        data.update(query=selected["url"], preview_id=selected["preview_id"])

    def confirmed_preview(self, data, guild, owner):
        from ..web_dashboard import APIError, _web_text, time
        if "preview_id" not in data:
            raise APIError(409, _web_text('m0425'))
        token = data["preview_id"]
        preview = self.previews.get(token) if isinstance(token, str) else None
        if preview and preview["expires"] <= time.monotonic():
            preview.pop("extraction", None)
            preview["extraction_reason"] = "expired-preview"
        if (not preview or preview.get("retain_until", preview["expires"]) <= time.monotonic()
                or preview["guild_id"] != guild.id or preview["owner_id"] != owner.id):
            raise APIError(409, _web_text('m0425'))
        if data["query"].strip() != preview["url"] or not preview["allowed"]:
            raise APIError(403, _web_text('m0426'))
        if preview.get("kind") == "playlist":
            selected = data.get("selected_items")
            if selected is None:
                selected = [item["item_id"] for item in preview["entries"] if item["allowed"]]
            if (not isinstance(selected, list) or not selected
                    or len(selected) > self.PREVIEW_LIMIT
                    or any(not isinstance(i, str) for i in selected)
                    or len(set(selected)) != len(selected)):
                raise APIError(400, _web_text('m0427'))
            available = {item["item_id"]: item for item in preview["entries"]}
            if any(i not in available or (not available[i]["allowed"] and preview["status"] != "done") for i in selected):
                raise APIError(403, _web_text('m0428'))
            canonical = [item["item_id"] for item in preview["entries"]
                         if item["item_id"] in selected]
            if preview["status"] == "done" and canonical != preview["selection"]:
                raise APIError(409, _web_text('m0429'))
            data["selected_items"] = canonical
        elif "selected_items" in data:
            raise APIError(400, _web_text('m0430'))
        if preview["status"] == "done":
            return preview
        if preview["status"] != "ready":
            raise APIError(409, _web_text('m0431'))
        return preview

    async def renew_preview(self, request, data, preview, guild, owner, action):
        from ..web_dashboard import APIError, _web_text, public_url, time
        if preview["status"] != "ready" or preview["expires"] > time.monotonic():
            return
        query = preview.get("original_query")
        if not query:
            raise APIError(409, _web_text('m0432'))
        self.user_rate_limit(owner)
        from ..web_dashboard_preview import log
        log.info("Dashboard add re-extracting preview: expired-preview")
        results = await self.run_resolution(guild,
            self.resolve_options(guild, owner, query, action), "m0434",
            owner=owner, priority="add", request=request)
        if self.discord_auth: self.authenticate(request)
        guild, owner = self.guild_owner(request)
        await self.issue_previews(guild, owner, results, query, action)
        from ..web_dashboard_media import media_url
        def same(a, b):
            return (media_url(a) or public_url(a)) == (media_url(b) or public_url(b))
        match = next((item for item in results if item["kind"] == preview["kind"]
                      and same(item["url"], preview["url"])), None)
        if match is None or (preview["kind"] == "track" and not match["allowed"]):
            raise APIError(409, _web_text('m0435'),
                           {"results": results, "expires_in": self.PREVIEW_TTL})
        if preview["kind"] == "playlist":
            refreshed = []
            for old in preview["entries"]:
                new = next((item for item in match["entries"] if same(item["url"], old["url"])), None)
                refreshed.append(dict(new, item_id=old["item_id"]) if new else
                                 dict(old, allowed=False, reason=_web_text('m0436')))
            preview["entries"] = refreshed
            preview["count"] = match["count"]
            preview["fresh_reason"] = match["reason"]
        # Renewal already extracted under admission. Transfer its private data
        # to the original locked token, without extending the extraction's age.
        if match["kind"] == "track":
            refreshed = self.previews[match["preview_id"]]
            preview.pop("extraction", None)
            if "extraction" in refreshed:
                preview["extraction"] = refreshed.pop("extraction")
            preview["extraction_reason"] = refreshed.get("extraction_reason", "no-saved-result")
        preview["expires"] = time.monotonic() + self.PREVIEW_TTL
        from ..web_dashboard_preview import prune_extractions
        prune_extractions(self.previews, time.monotonic())

    @staticmethod
    def playlist_restriction(permissions, count):
        from ..web_dashboard import _web_text
        # AllowPlaylists applies to the whole preview, even a one-item selection.
        if not permissions.allow_playlists:
            return _web_text('m0344')
        if permissions.max_playlist_length and count > permissions.max_playlist_length:
            return _web_text('m0437', p0=count, p1=permissions.max_playlist_length)
        return ""
