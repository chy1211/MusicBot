"""First-run container configuration. Existing files always take precedence."""
from __future__ import annotations
import argparse
import configparser
import os
from pathlib import Path
import secrets
import shutil
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

class ConfigurationError(Exception):
    pass

def settings(root: Path, env, prepare=False):
    root = root.resolve()
    config = root / "config"
    for name in ("config", "data", "audio_cache", "logs"):
        target = root / name
        if target.is_symlink(): raise ConfigurationError("Volume directories must not be symbolic links.")
        target.mkdir(exist_ok=True)
    uid, gid = int(env.get("PUID") or "1000"), int(env.get("PGID") or "1000")
    if uid <= 0 or gid <= 0: raise ConfigurationError("PUID and PGID must be positive; MusicBot runs without root.")
    options, dashboard = config / "options.ini", config / "web_dashboard.ini"
    enabled = env.get("DASHBOARD_ENABLED", "true").lower() in ("true", "1", "yes")
    required = []
    if not options.exists(): required += ["DISCORD_BOT_TOKEN", "OWNER_ID"]
    if not dashboard.exists() and enabled:
        required += ["DASHBOARD_PUBLIC_URL", "DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET"]
    missing = [key for key in required if not env.get(key, "").strip()]
    if missing:
        raise ConfigurationError("Missing required variables: " + ", ".join(missing) +
            ". 缺少必要環境變數。\n"
            "Open https://discord.com/developers/applications > New Application > Bot > Reset Token.\n"
            "Enable Server Members Intent and Message Content Intent. Copy the OAuth2 Client ID and Client Secret.\n"
            "Add DASHBOARD_PUBLIC_URL/auth/callback under OAuth2 Redirects.\n"
            "Enable Discord Developer Mode, right-click your own profile > Copy User ID for OWNER_ID.\n"
            "在 Discord 開發者入口建立應用程式、取得 Bot Token 與 OAuth2 憑證；開啟開發者模式複製自己的 ID。\n"
            "Fill .env, then run docker compose up -d again. No credentials were printed.")
    values = {}
    if not options.exists():
        values.update({"Token": env["DISCORD_BOT_TOKEN"], "OwnerID": env["OWNER_ID"],
                       "CommandPrefix": env.get("COMMAND_PREFIX") or "!",
                       "Spotify_ClientID": env.get("SPOTIFY_CLIENT_ID", ""),
                       "Spotify_ClientSecret": env.get("SPOTIFY_CLIENT_SECRET", "")})
        if not values["OwnerID"].isdigit() or int(values["OwnerID"]) <= 0:
            raise ConfigurationError("OWNER_ID must be your numeric Discord user ID.")
    if not dashboard.exists():
        language, zone = env.get("DEFAULT_LANGUAGE") or "en", env.get("TIME_ZONE") or "UTC"
        if language not in ("en", "zh-TW"): raise ConfigurationError("DEFAULT_LANGUAGE must be en or zh-TW.")
        try: ZoneInfo(zone)
        except (KeyError,ValueError): raise ConfigurationError("TIME_ZONE must be a valid IANA time zone, such as UTC.")
        values.update({"DefaultLanguage": language, "TimeZone": zone})
        if enabled:
            url = env["DASHBOARD_PUBLIC_URL"].strip().rstrip("/")
            try:
                parts = urlsplit(url)
                valid = (parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")))
                valid = valid and bool(parts.hostname) and not (parts.username or parts.password or parts.query or parts.fragment) and not parts.path
                _ = parts.port
            except ValueError: valid = False
            if not valid: raise ConfigurationError("DASHBOARD_PUBLIC_URL must be an HTTPS root origin (HTTP allowed only on loopback).")
            if not env["DISCORD_CLIENT_ID"].isdigit(): raise ConfigurationError("DISCORD_CLIENT_ID must be numeric.")
            values.update({"PublicURL":url,"DiscordClientID":env["DISCORD_CLIENT_ID"],"DiscordClientSecret":env["DISCORD_CLIENT_SECRET"]})
    for key,value in values.items():
        if any(c in value for c in ("\r","\n","\x00")): raise ConfigurationError("Invalid control character in " + key + ".")
    created = []
    def write_ini(target, sample, changes):
        if target.exists(): return
        parser=configparser.ConfigParser(interpolation=None)
        parser.optionxform=str
        parser.read(root / "sample_config" / sample, encoding="utf-8")
        for section, fields in changes.items():
            if not parser.has_section(section): parser.add_section(section)
            for key,value in fields.items(): parser.set(section,key,str(value))
        # Exclusive creation never truncates an existing ini, even on a concurrent start.
        try:
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:return
        with os.fdopen(fd,"w",encoding="utf-8") as stream: parser.write(stream)
        created.append(target)
    if not options.exists():
        write_ini(options,"example_options.ini",{
            "Credentials":{k:values[k] for k in ("Token","Spotify_ClientID","Spotify_ClientSecret")},
            "Permissions":{"OwnerID":values["OwnerID"]},
            "ChatCommands":{"CommandPrefix":values["CommandPrefix"]}})
    if not dashboard.exists():
        write_ini(dashboard,"example_web_dashboard.ini",{
            "WebDashboard":{"Enabled":"yes" if enabled else "no","Host":"0.0.0.0","Port":"8080",
                "AuthMode":"discord","PublicURL":values.get("PublicURL",""),
                "DiscordClientID":values.get("DiscordClientID",""),"DiscordClientSecret":values.get("DiscordClientSecret",""),
                "SessionSecret":secrets.token_urlsafe(48),"DefaultLanguage":values["DefaultLanguage"],"TimeZone":values["TimeZone"]}})
    for source_name,target_name in (("example_permissions.ini","permissions.ini"),("example_aliases.json","aliases.json")):
        target=config/target_name
        if not target.exists():
            try:
                with target.open("xb") as stream:stream.write((root/"sample_config"/source_name).read_bytes())
                created.append(target)
            except FileExistsError:pass
    if prepare and os.geteuid()==0:
        for name in ("config","data","audio_cache","logs"):os.chown(root/name,uid,gid)
        for path in created:
            os.chown(path,uid,gid);path.chmod(0o600)
    print("Configuration ready. Existing ini files were preserved; credentials were not logged.")
    return created

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare",action="store_true")
    args=parser.parse_args()
    try:settings(Path("/musicbot"),os.environ,args.prepare)
    except (ConfigurationError,OSError,ValueError):
        # Validation details name only keys and portal steps, never supplied values.
        exc=sys.exc_info()[1]
        text=str(exc) if isinstance(exc,ConfigurationError) else "Cannot initialize volumes. Check PUID/PGID and directory permissions."
        print("Configuration error: "+text,file=sys.stderr)
        return 78
    return 0
if __name__=="__main__":sys.exit(main())
