"""Bounded, cancellable audio alignment. No NumPy or playback mutation."""
from __future__ import annotations
import array
import asyncio
import copy
import difflib
import math
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from .web_dashboard_lyrics import clean_metadata
from .web_dashboard_lyrics_store import video_id

FPS = 20
MAX_DOWNLOAD = 20 * 1024 * 1024
UNCERTAIN = {"offset": 0.0, "source": "uncertain", "confidence": 0.0}

def envelope(pcm, sample_rate=8000):
    samples = array.array("h")
    samples.frombytes(pcm[:len(pcm)//2*2])
    if sys.byteorder != "little":
        samples.byteswap()
    width = sample_rate // FPS
    return [math.log1p(sum(float(x)*x for x in samples[i:i+width])/width)
            for i in range(0, len(samples)-width+1, width)]

def correlate(mv, audio):
    """Pearson envelope correlation at 50ms resolution; reject broad peaks."""
    minimum = 20 * FPS
    if min(len(mv),len(audio)) < minimum:
        return None
    def prefix(values, square=False):
        result=[0.0]
        for x in values: result.append(result[-1]+(x*x if square else x))
        return result
    mx, ax, m2, a2 = prefix(mv),prefix(audio),prefix(mv,True),prefix(audio,True)
    scores=[]
    for lag in range(-30*FPS,60*FPS+1):
        mi,ai=max(0,lag),max(0,-lag)
        size=min(len(mv)-mi,len(audio)-ai)
        if size<minimum: continue
        sm,sa=mx[mi+size]-mx[mi],ax[ai+size]-ax[ai]
        vm=m2[mi+size]-m2[mi]-sm*sm/size
        va=a2[ai+size]-a2[ai]-sa*sa/size
        if vm<=1e-6 or va<=1e-6: continue
        dot=sum(mv[mi+i]*audio[ai+i] for i in range(size))-sm*sa/size
        scores.append((dot/math.sqrt(vm*va),lag))
    if not scores: return None
    scores.sort(reverse=True)
    peak,lag=scores[0]
    other=max((score for score,index in scores if abs(index-lag)>=int(.75*FPS)),default=-1)
    median=sorted(score for score,_ in scores)[len(scores)//2]
    if peak<.82 or peak-other<.12 or peak-median<.30:
        return None
    return {"offset":round(lag/FPS,2),"source":"matched","confidence":round(peak,4)}

def parse_silence(stderr):
    pairs=re.findall(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)",str(stderr))
    start=None
    for kind,raw in pairs:
        value=float(raw)
        if kind=="start":
            if start is not None or value>.15: return None
            start=value
        elif start is not None:
            return value if .25<=value<=30 else None
    return None

def pcm(path, seconds):
    # Only local, allowlisted files reach ffmpeg. No network protocol access.
    proc=subprocess.run(["ffmpeg","-nostdin","-v","error","-threads","1",
        "-protocol_whitelist","file,pipe,crypto","-i",str(path),"-t",str(seconds),
        "-vn","-ac","1","-ar","8000","-f","s16le","pipe:1"],
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=18,check=True)
    if len(proc.stdout)>seconds*8000*2+4096: raise ValueError()
    return proc.stdout

def silence(path):
    proc=subprocess.run(["ffmpeg","-nostdin","-hide_banner","-threads","1",
        "-protocol_whitelist","file,pipe,crypto","-i",str(path),"-t","30",
        "-af","silencedetect=noise=-40dB:d=0.25","-f","null","-"],
        stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=12,check=True)
    return parse_silence(proc.stderr.decode("utf-8","replace")[-64000:])

def similar(a,b):
    def norm(value):return "".join(c for c in str(value).casefold() if c.isalnum())
    return difflib.SequenceMatcher(None,norm(a),norm(b)).ratio()

def official_candidate(rows, title, artist, duration):
    for row in rows[:5]:
        if not isinstance(row,dict):continue
        channel=str(row.get("channel") or row.get("uploader") or "")
        topic=channel.casefold().endswith(" - topic")
        official=topic or bool(row.get("uploader_verified") or row.get("channel_is_verified")) and bool(re.search(r"official audio|audio only",str(row.get("title","")),re.I))
        if not official: continue
        name,performer=clean_metadata(row.get("track") or row.get("title",""))
        performer=row.get("artist") or performer or re.sub(r"\s*-\s*Topic$", "",channel,flags=re.I)
        length=row.get("duration")
        url=row.get("webpage_url") or row.get("url") or ""
        if (type(length) not in (int,float) or not math.isfinite(length) or abs(length-duration)>2
                or not video_id(url) or similar(title,name)<.94 or similar(artist,performer)<.90):
            continue
        return row
    return None

def _worker(pipe, source, details, cache_file, directory):
    """Isolated worker clones configured yt-dlp, using already loaded cookies only."""
    try:
        started=time.process_time()
        import resource
        children_start=resource.getrusage(resource.RUSAGE_CHILDREN)
        from yt_dlp import YoutubeDL
        from yt_dlp.cookies import YoutubeDLCookieJar
        from yt_dlp.utils import download_range_func
        class Quiet:
            def debug(self,*_):pass
            info=warning=error=debug
        params=dict(source.params)
        # Never open the cookie file, save a cookie jar, mutate the original
        # downloader, use a new proxy, or touch its output/cache paths.
        params.pop("cookiefile",None)
        params.update({"outtmpl":str(Path(directory)/"%(id)s.%(ext)s"),
            "paths":{"home":directory,"temp":directory},"cachedir":False,
            "writethumbnail":False,"writeinfojson":False,"writesubtitles":False,
            "writeautomaticsub":False,"extract_flat":False,"noplaylist":True,
            "playlistend":5,"max_filesize":MAX_DOWNLOAD,"socket_timeout":8,
            "retries":0,"fragment_retries":0,"concurrent_fragment_downloads":1,
            "format":"bestaudio[abr<=128]/bestaudio","logger":Quiet(),
            "postprocessors":[],"progress_hooks":[],"postprocessor_hooks":[],
            "usenetrc":False,"cookiesfrombrowser":None,"quiet":True,"no_warnings":True})
        with YoutubeDL(params) as ydl:
            jar=YoutubeDLCookieJar()
            existing=source.__dict__.get("cookiejar")
            if existing is not None:
                for cookie in existing:jar.set_cookie(copy.copy(cookie))
            ydl.cookiejar=jar
            def bounded(status):
                if status.get("downloaded_bytes",0)>MAX_DOWNLOAD:raise ValueError()
                for file in Path(directory).glob("*"):
                    if file.is_file() and file.stat().st_size>MAX_DOWNLOAD:raise ValueError()
            ydl.params["progress_hooks"]=[bounded]
            def download(url,seconds):
                ydl.params["download_ranges"]=download_range_func(None,[(0,seconds)])
                data=ydl.extract_info(url,download=True)
                paths=[Path(x["filepath"]) for x in data.get("requested_downloads",[]) if x.get("filepath")]
                paths.append(Path(ydl.prepare_filename(data)))
                for path in paths:
                    if path.is_file() and path.resolve().is_relative_to(Path(directory).resolve()) and path.stat().st_size<=MAX_DOWNLOAD:
                        return path
                raise ValueError()
            # Reference failure is independent of MV retrieval and silence fallback.
            reference=None
            try:
                found=ydl.extract_info("ytsearch5:"+details["artist"]+" "+details["title"]+" official audio",download=False)
                row=official_candidate(found.get("entries",[]),details["title"],details["artist"],details["duration"])
                if row:reference=download(row.get("webpage_url") or row["url"],60)
            except Exception:
                pass
            mv=Path(cache_file) if cache_file else None
            if mv is None:
                try:mv=download(details["url"],90)
                except Exception:pass
            value=dict(UNCERTAIN)
            if mv:
                if reference:
                    try:value=correlate(envelope(pcm(mv,90)),envelope(pcm(reference,60))) or value
                    except Exception:pass
                if value["source"]=="uncertain":
                    try:
                        offset=silence(mv)
                        if offset is not None:value={"offset":round(offset,2),"source":"silence","confidence":1.0}
                    except Exception:pass
            value["download_bytes"]=sum(path.stat().st_size for path in Path(directory).glob("*") if path.is_file())
            children=resource.getrusage(resource.RUSAGE_CHILDREN)
            value["cpu_seconds"]=round(time.process_time()-started + children.ru_utime+children.ru_stime-children_start.ru_utime-children_start.ru_stime,4)
            pipe.send(value)
    except BaseException:
        try:pipe.send(dict(UNCERTAIN))
        except Exception:pass
    finally:
        pipe.close()

class AlignmentService:
    TIMEOUT=60
    def __init__(self,store):
        self.store=store
        self.lock=asyncio.Lock()
        self.tasks={}

    async def request(self,bot,entry,lyrics):
        key=video_id(entry.url)
        if not key:return dict(UNCERTAIN)
        cached=await self.store.get(key,"analysis")
        if cached:return dict(cached,pending=False)
        duration=lyrics.get("duration")
        if type(duration) not in (int,float) or not math.isfinite(duration) or duration<=0:
            return dict(UNCERTAIN,pending=False)
        if type(entry.duration) in (int,float) and abs(entry.duration-duration)<=2:
            value={"offset":0.0,"source":"duration","confidence":1.0}
            await self.store.put(key,value,7*86400,"analysis")
            return dict(value,pending=False)
        if key not in self.tasks and len(self.tasks)<4:
            details={"title":str(lyrics.get("title",""))[:200],"artist":str(lyrics.get("artist",""))[:160],
                "duration":duration,"url":"https://www.youtube.com/watch?v="+key}
            cache_file=None
            try:
                root=Path(bot.config.audio_cache_path).resolve()
                file=Path(entry.filename).resolve()
                if file.is_file() and file.is_relative_to(root):cache_file=str(file)
            except (AttributeError,OSError,TypeError,ValueError):pass
            task=asyncio.create_task(self.job(key,bot.downloader,details,cache_file),name="dashboard-lyric-alignment")
            self.tasks[key]=task
            task.add_done_callback(lambda _:self.tasks.pop(key,None))
        return dict(UNCERTAIN,pending=key in self.tasks)

    async def job(self,key,downloader,details,cache_file):
        async with self.lock:
            value=dict(UNCERTAIN)
            try:
                value=await asyncio.wait_for(self.run_worker(downloader,details,cache_file),self.TIMEOUT)
            except (Exception,asyncio.CancelledError) as exc:
                if isinstance(exc,asyncio.CancelledError):raise
            try:await self.store.put(key,value,7*86400,"analysis")
            except OSError:pass

    async def run_worker(self,downloader,details,cache_file):
        snapshot=getattr(downloader,"cookie_ytdl_snapshot",None)
        source=await asyncio.to_thread(snapshot) if snapshot else getattr(downloader,"unsafe_ytdl",None)
        if source is None:return dict(UNCERTAIN)
        params={}
        for key,value in source.params.items():
            if key in ("cookiefile","cookiesfrombrowser","logger","progress_hooks","postprocessor_hooks"):
                continue
            try:json.dumps(value)
            except (TypeError,ValueError):continue
            params[key]=value
        cookie_fields=("version","name","value","port","port_specified","domain","domain_specified",
            "domain_initial_dot","path","path_specified","secure","expires","discard","comment","comment_url","rfc2109")
        cookies=[]
        jar=source.__dict__.get("cookiejar")
        if jar is not None:
            for cookie in jar:
                cookies.append({**{name:getattr(cookie,name) for name in cookie_fields},"rest":dict(cookie._rest)})
        with tempfile.TemporaryDirectory(prefix="musicbot-webtest-lyrics-align-") as directory:
            payload=json.dumps({"params":params,"cookies":cookies,"details":details,
                "cache_file":cache_file,"directory":directory}).encode()
            if len(payload)>1024*1024:return dict(UNCERTAIN)
            proc=await asyncio.create_subprocess_exec(sys.executable,"-m","musicbot.web_dashboard_lyrics_worker",
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,start_new_session=True)
            try:
                output,_=await proc.communicate(payload)
                if len(output)>8192:return dict(UNCERTAIN)
                value=json.loads(output)
                return value if isinstance(value,dict) else dict(UNCERTAIN)
            finally:
                if proc.returncode is None:
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    await proc.wait()

    async def close(self):
        tasks=list(self.tasks.values())
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
