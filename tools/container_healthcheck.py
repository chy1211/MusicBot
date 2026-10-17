"""Local liveness check. A healthy dashboard does not imply Discord is connected."""
import configparser
from pathlib import Path
import sys
import urllib.request

def main():
    parser=configparser.ConfigParser(interpolation=None)
    try:
        parser.read(Path("/musicbot/config/web_dashboard.ini"))
        if not parser.getboolean("WebDashboard","Enabled",fallback=False):return 0
        port=parser.getint("WebDashboard","Port",fallback=8080)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz",timeout=3) as response:
            return 0 if response.status==200 and response.read()==b'{"status": "ok"}' else 1
    except Exception:return 1
if __name__=="__main__":sys.exit(main())
