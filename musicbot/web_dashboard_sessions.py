"""Bounded, atomic session records; raw bearer/OAuth tokens never reach disk."""
from __future__ import annotations
import json
import math
import os
import re
import tempfile
from pathlib import Path

class SessionStore:
    def __init__(self, root):
        self.path = Path(root) / "sessions.json"

    def read(self):
        try:
            if self.path.stat().st_size > 1024 * 1024:
                return {}
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if set(value) != {"version", "sessions"} or value["version"] != 1:
                return {}
            records = value["sessions"]
            if not isinstance(records, dict) or len(records) > 1024:
                return {}
            for digest, item in records.items():
                if not re.fullmatch(r"[0-9a-f]{64}", digest): return {}
                if not isinstance(item, dict) or set(item) != {"user","created","last_seen","expires"}: return {}
                user = item["user"]
                if (not isinstance(user, dict) or set(user) != {"id","name","avatar"}
                    or not isinstance(user["id"],str) or not re.fullmatch(r"[0-9]{1,20}",user["id"]) or int(user["id"]) <= 0
                    or not isinstance(user["name"],str) or not 1 <= len(user["name"]) <= 128
                    or not isinstance(user["avatar"],str) or len(user["avatar"]) > 512): return {}
                for field in ("created","last_seen","expires"):
                    if type(item[field]) not in (int,float) or not math.isfinite(item[field]) or item[field] <= 0: return {}
                if not item["created"] <= item["last_seen"] < item["expires"] <= item["last_seen"] + 30*86400: return {}
            return records
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            # Missing or corrupt files only require signing in again.
            return {}

    def write(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".sessions-",dir=self.path.parent)
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(fd,"w",encoding="utf-8") as stream:
                json.dump({"version":1,"sessions":records},stream,ensure_ascii=False)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary,self.path)
            directory=os.open(self.path.parent,os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
