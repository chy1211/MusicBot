"""Read-only Spotify matching through the bot's existing client."""
from .web_dashboard_i18n import message as _web_text
import asyncio
import re
import time
import unicodedata
from collections import OrderedDict
from difflib import SequenceMatcher
from urllib.parse import quote, urlencode, urlsplit
from aiohttp import web
from .web_dashboard_lyrics import clean_metadata

def spotify_track_url(value):
    if not isinstance(value,str): return ""
    try:
        p=urlsplit(value)
        if p.scheme not in ("http","https") or p.hostname!="open.spotify.com" or p.username or p.password or p.port not in (None,80,443): return ""
        m=re.fullmatch(r"/(?:intl-[A-Za-z-]+/)?track/([A-Za-z0-9]{1,100})/?",p.path)
        return "https://open.spotify.com/track/"+m[1] if m else ""
    except ValueError: return ""

def metadata(entry):
    info=getattr(entry,"info",{}) or {}
    artist=info.get("artist") or info.get("creator") or ""
    if not artist and isinstance(info.get("artists"),list): artist=", ".join(str(a) for a in info["artists"])
    title,artist=clean_metadata(info.get("track") or entry.title,artist)
    title=re.sub(r"[【】\[\]]"," ",title)
    title=re.sub(r"\b(?:lyrics?|official|video|mv)\b"," ",title,flags=re.I)
    return re.sub(r"\s+"," ",title).strip(),str(artist).strip()

def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKC",str(value)).casefold() if c.isalnum())

class SpotifyLookup:
    def __init__(self):
        self.cache=OrderedDict();self.lock=asyncio.Lock();self.cooldown_until=0
    async def lookup(self,bot,entry):
        info=getattr(entry,"info",{}) or {}
        for value in (getattr(entry,"spotify_url",""),info.get("spotify_url"),info.get("original_url"),
                      info.get("__input_subject"),getattr(entry,"url","")):
            direct=spotify_track_url(value)
            if direct: return {"url":direct,"mode":"track","query":""}
        title,artist=metadata(entry);query=" ".join(p for p in (artist,title) if p)[:200] or _web_text('m0576')
        fallback={"url":"https://open.spotify.com/search/"+quote(query,safe=""),"mode":"search","query":query}
        key=(title.casefold(),artist.casefold(),getattr(entry,"duration",None))
        cached=self.cache.get(key)
        if cached and cached[0]>time.monotonic(): return dict(cached[1])
        value=fallback
        if getattr(bot.config,"spotify_enabled",False) and getattr(bot,"spotify",None):
            try:
                value=await asyncio.wait_for(self.search(bot.spotify,title,artist,entry.duration,key,fallback),8)
            except Exception:
                self.cooldown_until=time.monotonic()+30
        self.cache[key]=(time.monotonic()+3600,value)
        self.cache.move_to_end(key)
        while len(self.cache)>256: self.cache.popitem(last=False)
        return dict(value)
    async def search(self,spotify,title,artist,duration,key,fallback):
        async with self.lock:
            cached=self.cache.get(key)
            if cached and cached[0]>time.monotonic(): return cached[1]
            if self.cooldown_until>time.monotonic(): return fallback
            response=await spotify.make_api_req("search?"+urlencode({"q":" ".join((artist,title)).strip(),"type":"track","limit":1}))
            rows=response.get("tracks",{}).get("items",[])
            if not rows or not title or not artist: return fallback
            track=rows[0];a=", ".join(str(x.get("name","")) for x in track.get("artists",[]) if isinstance(x,dict))
            score=SequenceMatcher(None,normalized(title),normalized(track.get("name",""))).ratio()
            artist_score=SequenceMatcher(None,normalized(artist),normalized(a)).ratio()
            milliseconds=track.get("duration_ms")
            length_ok=(not duration or (type(milliseconds) in (int,float) and abs(milliseconds/1000-duration)<=12))
            url=spotify_track_url(track.get("external_urls",{}).get("spotify",""))
            if url and score>=.94 and artist_score>=.90 and length_ok:
                return {"url":url,"mode":"track","query":fallback["query"],
                        "title":str(track.get("name",""))[:200],"artist":a[:160],"duration":milliseconds/1000 if type(milliseconds) in (int,float) else None}
            return fallback

class DashboardSpotify:
    def init_spotify_lookup(self):
        self.spotify_lookup=SpotifyLookup()
        self.spotify_rate_limits={}
        self.app.router.add_get("/api/guilds/{guild_id}/spotify",self.current_spotify)
    async def current_spotify(self,request):
        from .web_dashboard import APIError
        guild,member=self.guild_owner(request)
        now=time.monotonic()
        self.spotify_rate_limits={uid:[t for t in stamps if t>now-60] for uid,stamps in self.spotify_rate_limits.items() if stamps and stamps[-1]>now-60}
        stamps=self.spotify_rate_limits.setdefault(member.id,[])
        if len(stamps)>=12: raise APIError(429,_web_text('m0577'))
        stamps.append(now)
        player=self.bot.get_player_in(guild);entry=getattr(player,"current_entry",None)
        if entry is None: raise APIError(409,_web_text('m0378'))
        token=self.track_token(player)
        value=await self.spotify_lookup.lookup(self.bot,entry)
        if self.discord_auth: self.authenticate(request)
        self.guild_owner(request)
        return web.json_response(dict(value,track_token=token))
