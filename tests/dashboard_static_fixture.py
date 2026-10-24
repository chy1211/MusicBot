"""Disposable built-static route inputs; real builds are checked by the Node suite."""
import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

@contextmanager
def dashboard_static():
    from musicbot import web_dashboard
    built = Path(web_dashboard.STATIC) / "dist"
    if (built / "index.html").is_file():
        yield built
        return
    with tempfile.TemporaryDirectory(prefix="dashboard-static-test-") as directory:
        root = Path(directory)
        built = root / "dist"
        shutil.copytree(ROOT / "frontend/public", built)
        (built / "index.html").write_bytes((ROOT / "frontend/index.html").read_bytes())
        (built / "sw.js").write_bytes((ROOT / "frontend/src/sw.ts").read_bytes())
        manifest = {"name": "Music dashboard", "start_url": "/", "scope": "/", "display": "standalone",
                    "icons": [{"sizes": size} for size in ("any", "192x192", "512x512")]}
        (built / "manifest.webmanifest").write_text(json.dumps(manifest))
        with patch("musicbot.web_dashboard.STATIC", root):
            yield built
