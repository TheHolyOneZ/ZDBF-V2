# SPDX-License-Identifier: Apache-2.0
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = sorted([ROOT / "README.md", ROOT / "CHANGELOG.md", ROOT / "extensions" / "README.md",
               *(ROOT / "docs").rglob("*.md"), *(ROOT / ".github").glob("*.md")])
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)|<img[^>]+src=\"([^\"]+)\"")
FENCE = re.compile(r"^(```|~~~).*?^\1", re.M | re.S)


def _slug(heading: str) -> str:
    text = re.sub(r"<[^>]+>", "", heading).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    for line in FENCE.sub("", path.read_text(encoding="utf-8")).splitlines():
        if m := re.match(r"^#{1,6}\s+(.*)$", line):
            slug = _slug(m.group(1))
            n = seen.get(slug, 0)
            seen[slug] = n + 1
            out.add(slug if n == 0 else f"{slug}-{n}")
    return out


def _links(path: Path) -> list[str]:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    text = re.sub(r"`[^`\n]*`", "", text)
    return [a or b for a, b in LINK.findall(text)]


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(doc: Path) -> None:
    broken = []
    for link in _links(doc):
        if re.match(r"^[a-z]+:", link):
            continue
        target, _, anchor = link.partition("#")
        dest = (doc.parent / target).resolve() if target else doc
        if not dest.exists():
            broken.append(link)
        elif anchor and dest.suffix == ".md" and anchor not in _anchors(dest):
            broken.append(link)
    assert not broken, f"broken links in {doc.relative_to(ROOT)}: {broken}"


def test_configuration_guide_matches_default_config() -> None:
    guide = (ROOT / "docs" / "guide" / "configuration.md").read_text(encoding="utf-8")
    block = re.search(r"## The full default file\n.*?```toml\n(.*?)```", guide, re.S)
    assert block is not None
    default = (ROOT / "zdbf" / "core" / "default_config.toml").read_text(encoding="utf-8")
    assert block.group(1) == default
