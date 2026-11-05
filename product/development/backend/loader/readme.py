"""Source-checked upstream README passages for M3; no network or AI execution.

``load_readme(corpus_root)`` reads the original manifest and the pinned machine
README, never Meridian's submission README. Paragraph IDs are deterministic
README/<normalized-heading>/p<n> names. Images and original native CAD are not
downloaded or substituted; their unavailable references remain explicit.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from backend.contracts import ReadmePassage, normalize_component, readme_name


class ReadmeError(ValueError):
    pass


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fragments = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1
        elif not self.ignored:
            if re.fullmatch(r"h[1-6]", tag):
                self.fragments.append("\n" + "#" * int(tag[1]) + " ")
            elif tag in {"p", "div", "br", "li", "tr"}:
                self.fragments.append("\n")
            elif tag == "img":
                alt = dict(attrs).get("alt", "Image")
                self.fragments.append(f"[Image not included: {alt}]")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.ignored = max(0, self.ignored - 1)
        elif not self.ignored and (tag in {"p", "div", "li", "tr"} or re.fullmatch(r"h[1-6]", tag)):
            self.fragments.append("\n")

    def handle_data(self, data):
        if not self.ignored:
            self.fragments.append(data)


def _plain(block: str) -> str:
    block = re.sub(r"!\[([^\]]*)\]\([^\n)]*\)", r"[Image not included: \1]", block)
    parser = _Text()
    parser.feed(block)
    text = "".join(parser.fragments)
    text = re.sub(r"\[([^\]]+)\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)", r"\1 (\2)", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return unescape(text).strip()


def extract_passages(source: str, source_sha256: str) -> list[ReadmePassage]:
    """Extract deterministic paragraphs from original UTF-8 source text.

    The supplied digest belongs to the original bytes, before HTML cleanup.
    Repeated heading names share a paragraph counter, avoiding duplicate IDs.
    Paragraph order, link labels/targets and source statements are preserved.
    """
    section = "Overview"
    counters = defaultdict(int)
    result = []
    block = []

    def flush():
        if not block:
            return
        original = "\n".join(block)
        block.clear()
        text = _plain(original)
        if not text or re.fullmatch(r"[-*_\s]+", text):
            return
        images = re.findall(r"!\[[^\]]*\]\(([^\s)]+)", original)
        images += re.findall(r"<img\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", original, re.I)
        slug = normalize_component(section)
        counters[slug] += 1
        result.append(ReadmePassage(name=readme_name(slug, counters[slug]), section=section,
            paragraph=counters[slug], text=text, source_sha256=source_sha256,
            missing_images=list(dict.fromkeys(unescape(image) for image in images)),
            mentions_unavailable_native_cad=bool(re.search(
                r"\.(?:step|stp|iges|igs|f3d|sldprt|fcstd)\b|\b(?:native|original)\s+CAD\b|\bFusion\s*360\b",
                original, re.I))))

    for line in source.splitlines():
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        html_heading = re.fullmatch(r"\s*<h[1-6]\b[^>]*>(.*?)</h[1-6]>\s*", line, re.I)
        if heading or html_heading:
            flush()
            section = _plain((heading or html_heading).group(1)) or "Overview"
        elif not line.strip():
            flush()
        else:
            block.append(line)
    flush()
    return result


def load_readme(corpus_root: Path) -> list[ReadmePassage]:
    """Read and hash-check the manifest's unique OPENLPBF-README asset."""
    root = Path(corpus_root).resolve()
    try:
        manifest = json.loads((root / "dataset/manifest.json").read_text(encoding="utf-8"))
        assets = [asset for asset in manifest["assets"] if asset.get("id") == "OPENLPBF-README"]
        if len(assets) != 1:
            raise ReadmeError("The original machine README manifest identity is missing or ambiguous.")
        asset = assets[0]
        path = (root / asset["path"]).resolve()
        if not path.is_relative_to(root):
            raise ReadmeError("README source path escapes the supplied corpus.")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != asset["sha256"]:
            raise ReadmeError("The machine README bytes no longer match the original manifest.")
        return extract_passages(data.decode("utf-8-sig"), digest)
    except (OSError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as error:
        raise ReadmeError("The original machine README could not be read and validated.") from error


def search_passages(passages: list[ReadmePassage], query: str = "") -> list[ReadmePassage]:
    """Literal case-insensitive token search, retaining source paragraph order."""
    terms = query.casefold().split()
    return [p for p in passages if all(term in (p.section + " " + p.text).casefold() for term in terms)]
