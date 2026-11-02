#!/usr/bin/env python3
"""Build the mirror feed for "Chief of Staff Confidential".

Reads the pristine Muse-platform RSS feed and writes a copy with ONLY two
insertions in <channel>, which Apple Podcasts Connect requires and which the
platform feed cannot carry:

  <itunes:author>Mohit Agarwal</itunes:author>
  <itunes:category text="Business">
    <itunes:category text="Management"/>
  </itunes:category>

Everything else is preserved byte-for-byte (GUIDs, enclosure URLs, item
order). The insertion is anchored on the channel-level <itunes:explicit>
line, falling back to the <channel> line. Idempotent: if either tag is
already present in the channel header, it is not inserted again, so this
script is safe to re-run on every sync.

Usage:
  python3 build_mirror.py [source.xml] [mirror.xml]
Defaults: source-feed.xml -> feed.xml in this script's directory.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The mirror's own public URL (GitHub Pages). The channel's atom self-link
# is rewritten to this so the mirror feed is self-consistent.
MIRROR_URL = "https://mohito91.github.io/chief-of-staff-confidential-feed/feed.xml"

AUTHOR_LINE = "  <itunes:author>Mohit Agarwal</itunes:author>\n"
CATEGORY_LINES = (
    '  <itunes:category text="Business">\n'
    '    <itunes:category text="Management"/>\n'
    "  </itunes:category>\n"
)
# Spotify for Creators verifies ownership by emailing a code to the address
# in itunes:owner; the platform feed carries no owner block, so the mirror
# adds one (name + the user's show-contact email).
OWNER_LINES = (
    "  <itunes:owner>\n"
    "    <itunes:name>Mohit Agarwal</itunes:name>\n"
    "    <itunes:email>mohit.a91@gmail.com</itunes:email>\n"
    "  </itunes:owner>\n"
)

# Creator-provided transcripts (Podcasting 2.0 <podcast:transcript>).
# Apple's auto-generated transcript for episode 3 misspells "principal" as
# "principle" (homophone ASR error); the corrected, timed VTT is hosted in
# this same GitHub Pages repo, and Podcasts Connect is set to display the
# transcripts we provide. Keyed by episode GUID so syncs keep the tag.
PODCAST_NS = "https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/1.0.md"
TRANSCRIPTS = {
    "ep-b484f639-8a56-47ea-9daf-e7cd672adfb3": (
        "https://mohito91.github.io/chief-of-staff-confidential-feed/"
        "transcripts/youre-not-alone.vtt"
    ),
}


def _add_transcript_tags(text: str) -> str:
    if "xmlns:podcast" not in text:
        text = text.replace(
            'xmlns:atom="http://www.w3.org/2005/Atom">',
            'xmlns:atom="http://www.w3.org/2005/Atom"\n'
            f'     xmlns:podcast="{PODCAST_NS}">',
            1,
        )
    for guid, url in TRANSCRIPTS.items():
        # Find the <item> block containing this GUID and add the tag once.
        tag = (
            f'    <podcast:transcript url="{url}" type="text/vtt" '
            'language="en"/>\n'
        )
        for match in re.finditer(r"<item>.*?</item>", text, re.DOTALL):
            block = match.group(0)
            if guid not in block or "podcast:transcript" in block:
                continue
            guid_end = block.index("</guid>") + len("</guid>\n")
            new_block = block[:guid_end] + tag + block[guid_end:]
            text = text[: match.start()] + new_block + text[match.end():]
            break
    return text


def _rewrite_self_link(text: str) -> str:
    head, sep, tail = text.partition("<item>")

    def _swap_href(match: "re.Match[str]") -> str:
        return re.sub(
            r'href="[^"]*"', f'href="{MIRROR_URL}"', match.group(0), count=1
        )

    head = re.sub(r'<atom:link[^>]*rel="self"[^>]*/>', _swap_href, head, count=1)
    return head + sep + tail


def build(source_text: str) -> str:
    source_text = _add_transcript_tags(source_text)
    source_text = _rewrite_self_link(source_text)
    lines = source_text.splitlines(keepends=True)

    # Only inspect the channel header (before the first <item>) for
    # idempotency checks, so episode content can never confuse us.
    header_end = next(
        (i for i, ln in enumerate(lines) if "<item>" in ln), len(lines)
    )
    header = "".join(lines[:header_end])
    need_author = "<itunes:author>" not in header
    need_category = "<itunes:category" not in header
    need_owner = "<itunes:owner>" not in header
    if not need_author and not need_category and not need_owner:
        return source_text

    insert_at = None
    for i in range(header_end):
        if "</itunes:explicit>" in lines[i]:
            insert_at = i + 1
            break
    if insert_at is None:
        for i in range(header_end):
            if lines[i].strip() == "<channel>":
                insert_at = i + 1
                break
    if insert_at is None:
        raise SystemExit("error: could not find an insertion anchor in <channel>")

    block = ""
    if need_author:
        block += AUTHOR_LINE
    if need_category:
        block += CATEGORY_LINES
    if need_owner:
        block += OWNER_LINES
    lines.insert(insert_at, block)
    return "".join(lines)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "source-feed.xml"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "feed.xml"
    out = build(src.read_text(encoding="utf-8"))
    dst.write_text(out, encoding="utf-8")
    print(f"wrote {dst} ({len(out.encode('utf-8'))} bytes) from {src}")


if __name__ == "__main__":
    main()
