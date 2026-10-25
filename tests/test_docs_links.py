"""Every relative Markdown link in the docs points at a file that exists."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
FENCE = re.compile(r'^(```|~~~).*?^\1', re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r'`[^`\n]*`')
SKIP = ('http://', 'https://', 'mailto:', '#')


def _documents():
    yield from (p for p in (ROOT / 'README.md', ROOT / 'CHANGELOG.md') if p.exists())
    yield from sorted((ROOT / 'docs').rglob('*.md'))


def broken_links():
    broken = []
    for doc in _documents():
        text = INLINE_CODE.sub('', FENCE.sub('', doc.read_text(encoding='utf-8')))
        for target in LINK.findall(text):
            if target.startswith(SKIP):
                continue
            path = target.split('#', 1)[0]
            if path and not (doc.parent / path).exists():
                broken.append(f'{doc.relative_to(ROOT)} -> {target}')
    return broken


def test_relative_links_resolve():
    assert broken_links() == []
