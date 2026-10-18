"""Replay bounded LRCLIB samples offline; never opens a network connection.

The baseline is pinned to the supplied production commit. Missing recorded
queries are reported explicitly, never converted into an empty API response.
All timing/backoff tests live separately in the round24 regression suite.
"""
import asyncio
import importlib.util
import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch, AsyncMock
from musicbot import web_dashboard_lyrics as current

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

class Content:
    def __init__(self, body): self.body = json.dumps(body).encode()
    async def iter_chunked(self, size):
        for start in range(0,len(self.body),size): yield self.body[start:start+size]

class Response:
    def __init__(self,row):
        self.status = row["status"]
        self.headers = {}
        self.content_type = "application/json"
        self.content = Content(row["body"])
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass

class Session:
    def __init__(self,responses,missing):
        self.responses,self.missing=responses,missing
    def get(self,url,params,**kwargs):
        path="/"+url.rsplit("/",1)[-1]
        key=json.dumps([path,params],sort_keys=True,ensure_ascii=False)
        if key not in self.responses:
            self.missing.append([path,params])
            raise ValueError("query not captured within HTTP budget")
        return Response(self.responses[key])

async def evaluate():
    spec=importlib.util.spec_from_file_location("lyrics_baseline",FIXTURES/"lyrics_round24_baseline.py")
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    fixture=json.loads((FIXTURES/"lyrics_round24_responses.json").read_text())
    rows=[]
    for song in json.loads((FIXTURES/"lyrics_round24_songs.json").read_text()):
        row=dict(song)
        for name,module in (("old",baseline),("new",current)):
            missing=[]
            client=module.LyricsClient();client.MIN_INTERVAL=0
            original=client._request
            async def request(session,path,params):
                return await original(Session(fixture["responses"],missing),path,params)
            client._request=request
            with patch.object(asyncio,"sleep",new=AsyncMock()):
                value=await client.lookup(song["title"],song["artist"],song["duration"])
            row[name]={k:value.get(k) for k in ("status","title","artist","duration","match")}
            row[name]["first_line"]=next((line["text"] for line in value.get("lines",[]) if line["text"].strip()),"") or value.get("plain_lyrics","").split("\n")[0]
            row[name]["uncaptured_queries"]=missing
        rows.append(row)
    return {"http_calls":len(fixture["calls"]),"counts":{name:dict(Counter(row[name]["status"] for row in rows)) for name in ("old","new")},"songs":rows}

if __name__=="__main__":
    print(json.dumps(asyncio.run(evaluate()),ensure_ascii=False,indent=2))
