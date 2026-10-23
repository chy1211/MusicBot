"""Validate the dashboard catalogs and translated frontend source."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def check():
    base=ROOT/"musicbot/web"
    en=json.loads((base/"i18n/en.json").read_text())
    zh=json.loads((base/"i18n/zh-TW.json").read_text())
    assert en.keys()==zh.keys(),"Catalog keys differ"
    for key in en:
        assert isinstance(en[key],str) and en[key].strip(),key
        assert isinstance(zh[key],str) and zh[key].strip(),key
        assert not re.search(r"[\u3400-\u9fff]",en[key]),key
        assert set(re.findall(r"\{p\d+\}",en[key]))==set(re.findall(r"\{p\d+\}",zh[key])),key
    for file in [*base.glob("*.js"),*base.glob("*.html"),base/"manifest.webmanifest"]:
        assert not re.search(r"[\u3400-\u9fff]",file.read_text()),f"Hardcoded CJK text: {file.name}"
    for file in base.glob("*.js"):
        for key in re.findall(r'\bt\("([^"]+)"',file.read_text()):
            assert key in en,(file.name,key)
    source = ROOT / "frontend/src"
    for file in [*source.rglob("*.vue"), *source.rglob("*.ts")]:
        if file.name == "env.d.ts": continue
        text = file.read_text()
        assert not re.search(r"[\u3400-\u9fff]", text), f"Hardcoded CJK text: {file}"
        for key in re.findall(r'(?:data-i18n(?:-[a-z-]+)?=|\bt\()[\"\']([^\"\']+)[\"\']', text):
            assert key in en, (file.name, key)
    for locale in ("en", "zh-TW"):
        public = ROOT / "frontend/public/i18n" / (locale + ".json")
        assert json.loads(public.read_text()) == json.loads((base/"i18n"/(locale+".json")).read_text()), "Public catalog drift"
    return len(en)
if __name__=="__main__":print(f"Dashboard catalogs: {check()} matching, translated keys; frontend CJK literals: 0")
