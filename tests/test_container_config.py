"""Offline first-run config, credential handling and image contract tests."""
import contextlib,configparser,io,os,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.container_config import settings,ConfigurationError,main

ROOT=Path(__file__).resolve().parents[1]
FAKE={"DISCORD_BOT_TOKEN":"FAKE_BOT_TOKEN_R13_DO_NOT_USE","OWNER_ID":"123456789012345678",
      "DASHBOARD_PUBLIC_URL":"http://localhost:8080","DISCORD_CLIENT_ID":"123456789012345679",
      "DISCORD_CLIENT_SECRET":"FAKE_CLIENT_SECRET_R13_DO_NOT_USE","DEFAULT_LANGUAGE":"en","TIME_ZONE":"UTC"}
class ContainerConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="musicbot-webtest-config-")
        self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        sample=self.root/"sample_config";sample.mkdir()
        for name in ["example_options.ini","example_web_dashboard.ini","example_permissions.ini","example_aliases.json"]:
            shutil.copyfile(ROOT/"config"/name,sample/name)
    def read(self,name):
        p=configparser.ConfigParser(interpolation=None);p.read(self.root/"config"/name);return p
    def test_generates_ini_and_random_secret_without_logging_credentials(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):settings(self.root,FAKE)
        options=self.read("options.ini");dashboard=self.read("web_dashboard.ini")
        self.assertEqual(options["Credentials"]["Token"],FAKE["DISCORD_BOT_TOKEN"])
        self.assertEqual(options["Permissions"]["OwnerID"],FAKE["OWNER_ID"])
        self.assertEqual(dashboard["WebDashboard"]["PublicURL"],FAKE["DASHBOARD_PUBLIC_URL"])
        self.assertEqual(dashboard["WebDashboard"]["DefaultLanguage"],"en")
        self.assertEqual(dashboard["WebDashboard"]["TimeZone"],"UTC")
        self.assertGreaterEqual(len(dashboard["WebDashboard"]["SessionSecret"]),48)
        for key in ("DISCORD_BOT_TOKEN","DISCORD_CLIENT_SECRET"):self.assertNotIn(FAKE[key],out.getvalue())
        self.assertEqual((self.root/"config/options.ini").stat().st_mode & 0o777,0o600)
    def test_existing_files_are_never_overwritten_and_need_no_env(self):
        settings(self.root,FAKE);paths=[self.root/"config"/n for n in ("options.ini","web_dashboard.ini")]
        original=[p.read_bytes() for p in paths]
        settings(self.root,{})
        self.assertEqual(original,[p.read_bytes() for p in paths])
        settings(self.root,{**FAKE,"DISCORD_BOT_TOKEN":"CHANGED_FAKE","DISCORD_CLIENT_SECRET":"CHANGED_FAKE"})
        self.assertEqual(original,[p.read_bytes() for p in paths])
    def test_missing_variables_are_named_and_no_partial_ini_is_created(self):
        with self.assertRaises(ConfigurationError) as error:settings(self.root,{"DISCORD_BOT_TOKEN":FAKE["DISCORD_BOT_TOKEN"]})
        text=str(error.exception)
        self.assertIn("OWNER_ID",text);self.assertIn("Developer Mode",text);self.assertIn("discord.com/developers",text)
        self.assertNotIn(FAKE["DISCORD_BOT_TOKEN"],text)
        self.assertFalse((self.root/"config/options.ini").exists())
    def test_dashboard_can_be_disabled_without_oauth(self):
        settings(self.root,{"DISCORD_BOT_TOKEN":FAKE["DISCORD_BOT_TOKEN"],"OWNER_ID":FAKE["OWNER_ID"],"DASHBOARD_ENABLED":"false"})
        self.assertFalse(self.read("web_dashboard.ini").getboolean("WebDashboard","Enabled"))
    def test_invalid_values_do_not_echo_secrets(self):
        for field,value in [("OWNER_ID","SECRET_BAD_OWNER"),("TIME_ZONE","SECRET_BAD_ZONE"),("DASHBOARD_PUBLIC_URL","https://SECRET_BAD_URL/a"),("DISCORD_CLIENT_SECRET","SECRET"+chr(10)+"INJECT")]:
            with self.subTest(field=field):
                # A real newline must be rejected before any file is written.
                with self.assertRaises(ConfigurationError) as error:settings(self.root,{**FAKE,field:value})
                self.assertNotIn("SECRET",str(error.exception))
    def test_image_and_compose_use_nonroot_runtime_and_init_gate(self):
        docker=(ROOT/"Dockerfile").read_text();compose=(ROOT/"docker-compose.yml").read_text()
        self.assertIn(" AS wheels",docker);self.assertIn("USER 1000:1000",docker);self.assertIn("HEALTHCHECK",docker)
        self.assertIn("service_completed_successfully",compose);self.assertIn('restart: "no"',compose)
        self.assertIn("127.0.0.1:",compose)
