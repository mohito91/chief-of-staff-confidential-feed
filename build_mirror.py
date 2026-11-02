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
_T = "https://mohito91.github.io/chief-of-staff-confidential-feed/transcripts/"
TRANSCRIPTS = {
    "ep-a078b6e2-06a3-41c6-804f-ee92c67da823": _T + "three-takeaways-for-first-time-chiefs-of-staff.vtt",
    "ep-fd223d1c-cbe4-4d8c-97eb-807416e93194": _T + "the-reading-list.vtt",
    "ep-b484f639-8a56-47ea-9daf-e7cd672adfb3": _T + "youre-not-alone.vtt",
    "ep-a9668dfc-e931-4bf6-ab04-7efc428f5a95": _T + "own-the-screen.vtt",
}


def _add_episode_numbers(text: str) -> str:
    """Stamp <itunes:episode> on every item, numbered by pubDate order.

    Titles stay clean (user decision, 2026-11-02): the number lives in
    metadata, which Apple Podcasts displays in the app. Numbering is derived
    from pubDates, so it is correct for the whole back catalog and extends
    itself automatically as new episodes publish. Idempotent: an existing
    tag's value is recomputed, never duplicated.
    """
    from email.utils import parsedate_to_datetime

    blocks = list(re.finditer(r"<item>.*?</item>", text, re.DOTALL))
    dated = []
    for match in blocks:
        block = match.group(0)
        date_match = re.search(r"<pubDate>([^<]+)</pubDate>", block)
        if not date_match:
            continue
        try:
            when = parsedate_to_datetime(date_match.group(1).strip())
        except (TypeError, ValueError):
            continue
        dated.append((when, match))
    dated.sort(key=lambda pair: pair[0])
    numbers = {id(match): i + 1 for i, (_, match) in enumerate(dated)}

    for match in reversed(blocks):
        number = numbers.get(id(match))
        if number is None:
            continue
        block = match.group(0)
        block = re.sub(r"[ \t]*<itunes:episode>\d+</itunes:episode>\n", "", block)
        guid_end = block.index("</guid>") + len("</guid>\n")
        tag = f"    <itunes:episode>{number}</itunes:episode>\n"
        block = block[:guid_end] + tag + block[guid_end:]
        text = text[: match.start()] + block + text[match.end():]
    return text


def _add_itunes_titles(text: str) -> str:
    """Mirror each item's <title> into <itunes:title> (identical text).

    Apple's display rule: an <itunes:episode> number only surfaces in the
    episode LIST when the item also carries an <itunes:title>; with the
    episode tag alone it shows only on the episode's own page. The itunes
    title is byte-identical to the existing title, so nothing about how any
    app renders the title changes. Idempotent.
    """
    out = []
    pos = 0
    for match in re.finditer(r"<item>.*?</item>", text, re.DOTALL):
        out.append(text[pos:match.start()])
        block = match.group(0)
        block = re.sub(r"[ \t]*<itunes:title>.*?</itunes:title>\n", "", block)
        title_match = re.search(r"(<title>.*?</title>\n)", block, re.DOTALL)
        if title_match:
            inner = re.search(r"<title>(.*?)</title>", title_match.group(1), re.DOTALL).group(1)
            insert_at = title_match.end(1)
            block = (
                block[:insert_at]
                + f"    <itunes:title>{inner}</itunes:title>\n"
                + block[insert_at:]
            )
        out.append(block)
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


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
            # Sit below the episode-number line when one is present, so
            # re-runs keep a stable tag order (guid, episode, transcript).
            rest = block[guid_end:]
            ep_line = re.match(r"[ \t]*<itunes:episode>\d+</itunes:episode>\n", rest)
            if ep_line:
                guid_end += ep_line.end()
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
    source_text = _add_itunes_titles(source_text)
    source_text = _add_episode_numbers(source_text)
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
