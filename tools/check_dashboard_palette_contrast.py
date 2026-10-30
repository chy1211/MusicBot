"""WCAG contrast audit of the actual CSS palette tokens (mint is immutable)."""
import re
from pathlib import Path

def luminance(color):
    rgb = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
    return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))

def contrast(a, b):
    x, y = sorted([luminance(a), luminance(b)])
    return (y + .05) / (x + .05)

def check():
    css = (Path(__file__).resolve().parents[1] / 'frontend/src/styles/surfaces.css').read_text()
    failures = 0
    mint_exceptions = 0
    for palette in ('mint', 'amber', 'ocean', 'rose'):
        for mode in ('dark', 'light'):
            selector = (':root' if mode == 'dark' else ':root[data-theme=light]') if palette == 'mint' else ':root[data-palette=' + palette + ']' + ('' if mode == 'dark' else '[data-theme=light]')
            block = re.search(re.escape(selector) + r'\{([^}]+)', css).group(1)
            tokens = dict(re.findall(r'--([a-z-]+):(#[a-fA-F0-9]{6})(?=;)', block))
            pairs = [(fg, bg) for fg in ('text', 'muted', 'green') for bg in ('bg', 'flat')] + [('accent-ink', 'green')]
            for fg, bg in pairs:
                ratio = contrast(tokens[fg], tokens[bg])
                ok = ratio >= 4.5
                status = 'PASS' if ok else ('MINT EXCEPTION' if palette == 'mint' else 'FAIL')
                if not ok:
                    if palette == 'mint': mint_exceptions += 1
                    else: failures += 1
                print(f'{palette}/{mode} {fg} {tokens[fg]} on {bg} {tokens[bg]}: {ratio:.4f}:1 {status}')
    print(f'Contrast checks: 56; non-mint failures: {failures}; immutable mint exceptions: {mint_exceptions}')
    return failures

if __name__ == '__main__':
    raise SystemExit(bool(check()))
