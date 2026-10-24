"""Validate the dashboard catalogs and translated frontend source."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def check():
    base=ROOT/"frontend/public"
    en=json.loads((base/"i18n/en.json").read_text())
    zh=json.loads((base/"i18n/zh-TW.json").read_text())
    assert en.keys()==zh.keys(),"Catalog keys differ"
    for key in en:
        assert isinstance(en[key],str) and en[key].strip(),key
        assert isinstance(zh[key],str) and zh[key].strip(),key
        assert not re.search(r"[\u3400-\u9fff]",en[key]),key
        assert set(re.findall(r"\{p\d+\}",en[key]))==set(re.findall(r"\{p\d+\}",zh[key])),key
    for file in [*base.glob("*.js"), *base.glob("*.html"), ROOT/"frontend/index.html", ROOT/"frontend/vite.config.ts"]:
        assert not re.search(r"[\u3400-\u9fff]",file.read_text()),f"Hardcoded CJK text: {file.name}"
    for file in base.glob("*.js"):
        for key in re.findall(r'\bt\("([^"]+)"',file.read_text()):
            assert key in en,(file.name,key)
    source = ROOT / "frontend/src"
    for file in [*source.rglob("*.vue"), *source.rglob("*.ts"), *source.rglob("*.css")]:
        if file.name == "env.d.ts": continue
        text = file.read_text()
        assert not re.search(r"[\u3400-\u9fff]", text), f"Hardcoded CJK text: {file}"
        for key in re.findall(r'(?:data-i18n(?:-[a-z-]+)?=|\bt\()[\"\']([^\"\']+)[\"\']', text):
            assert key in en, (file.name, key)
    return len(en)
if __name__=="__main__":print(f"Dashboard catalogs: {check()} matching, translated keys; frontend CJK literals: 0")
