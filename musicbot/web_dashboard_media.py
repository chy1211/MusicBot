"""Canonical HTTP media identities shared by dashboard features."""
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

def media_url(value):
    if not isinstance(value,str) or len(value)>2000 or any(c.isspace() or ord(c)<32 for c in value): return ""
    try:
        p=urlsplit(value); host=(p.hostname or "").lower(); port=p.port
        if p.scheme not in ("http","https") or not host or p.username or p.password: return ""
        segments=p.path.strip("/").split("/")
        youtube=host in ("youtube.com","youtube-nocookie.com") or host.endswith((".youtube.com",".youtube-nocookie.com"))
        ident=segments[0] if host in ("youtu.be","www.youtu.be") else (
            dict(parse_qsl(p.query)).get("v","") if youtube and p.path=="/watch" else
            segments[1] if youtube and len(segments)==2 and segments[0] in ("shorts","embed","live","v") else "")
        if youtube or host in ("youtu.be","www.youtu.be"):
            return "https://www.youtube.com/watch?v="+ident if re.fullmatch(r"[A-Za-z0-9_-]{11}",ident) else ""
        query=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True)
               if not k.lower().startswith("utm_") and k.lower() not in ("si","feature","fbclid","gclid")]
        authority=host+(":"+str(port) if port and port != (443 if p.scheme=="https" else 80) else "")
        return urlunsplit((p.scheme,authority,p.path.rstrip("/") or "/",urlencode(sorted(query)),""))
    except (ValueError,UnicodeError): return ""

def dedupe_favorites(value):
    tracks=value["playlists"][0]["tracks"]; seen=set(); unique=[]
    for track in tracks:
        key=media_url(track["url"])
        if key and key in seen: continue
        if key: seen.add(key)
        unique.append(track)
    tracks[:]=unique
