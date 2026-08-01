import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def test_relative_markdown_links_resolve():
    broken = []
    for document in ROOT.rglob("*.md"):
        if ".git" in document.parts:
            continue
        text = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK_RE.findall(text):
            target = raw_target.strip().split("#", 1)[0].strip()
            if not target or "://" in target or target.startswith(("mailto:", "#")):
                continue
            resolved = (document.parent / target).resolve()
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                broken.append(f"{document.relative_to(ROOT)} -> {raw_target}")
                continue
            if not resolved.exists():
                broken.append(f"{document.relative_to(ROOT)} -> {raw_target}")
    assert not broken, "Defekte relative Markdown-Links:\n" + "\n".join(broken)
