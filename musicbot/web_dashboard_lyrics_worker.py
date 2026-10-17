"""Private stdin/stdout worker: credentials stay in memory, never logs/files."""
import http.cookiejar
import json
import sys
from types import SimpleNamespace
from .web_dashboard_lyrics_alignment import _worker, UNCERTAIN

def main():
    sent=False
    class Pipe:
        def send(self,value):
            nonlocal sent
            if not sent:
                sys.stdout.write(json.dumps(value));sys.stdout.flush();sent=True
        def close(self):pass
    pipe=Pipe()
    try:
        raw=sys.stdin.buffer.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError()
        payload=json.loads(raw)
        source=SimpleNamespace(params=payload["params"])
        jar=http.cookiejar.CookieJar()
        for fields in payload["cookies"]:
            jar.set_cookie(http.cookiejar.Cookie(**fields))
        source.cookiejar=jar
        _worker(pipe,source,payload["details"],payload["cache_file"],payload["directory"])
    except BaseException:
        pipe.send(dict(UNCERTAIN))

if __name__=="__main__":
    main()
