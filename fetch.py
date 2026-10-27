"""Milestone 2: URL -> clean article text, with manual paste fallback.

Usage:
    python fetch.py <url>      # fetch; on failure offers manual paste
    python fetch.py --paste    # skip fetching, paste text directly
"""
import sys
from dataclasses import dataclass

import trafilatura

MIN_CHARS = 300  # below this, extraction is treated as failed (paywall/login stub)


@dataclass
class Source:
    source_type: str  # "url" | "manual"
    text: str
    url: str = ""
    title: str = ""
    author: str = ""
    published: str = ""


def fetch_url(url: str) -> Source:
    """Download and extract the main article text. Raises ValueError on failure."""
    html = trafilatura.fetch_url(url)
    if not html:
        raise ValueError("could not download the page")
    text = trafilatura.extract(html, include_comments=False, include_tables=True)
    if not text or len(text) < MIN_CHARS:
        raise ValueError("no usable article text extracted (paywall, login, or JS-only page?)")
    meta = trafilatura.extract_metadata(html)
    return Source(
        source_type="url",
        text=text,
        url=url,
        title=(meta.title if meta else "") or "",
        author=(meta.author if meta else "") or "",
        published=(meta.date if meta else "") or "",
    )


def read_pasted_text() -> str:
    """Read multi-line text from the terminal until a line containing only END (or EOF)."""
    print("Paste the text below. Finish with a line containing only END (or Ctrl-Z + Enter).")
    lines = []
    try:
        for line in sys.stdin:
            if line.strip() == "END":
                break
            lines.append(line.rstrip("\n"))
    except KeyboardInterrupt:
        pass
    return "\n".join(lines).strip()


def manual_source(url: str = "") -> Source:
    text = read_pasted_text()
    if not text:
        raise ValueError("nothing pasted")
    if not sys.stdin.isatty():
        return Source(source_type="manual", text=text, url=url)
    title = input("Title (optional): ").strip()
    author = input("Author (optional): ").strip()
    published = input("Published date YYYY-MM-DD (optional): ").strip()
    return Source(source_type="manual", text=text, url=url, title=title,
                  author=author, published=published)


def get_source(url: str = "") -> Source:
    """Fetch the URL; if that fails, offer manual paste. No URL -> paste."""
    if not url:
        return manual_source()
    try:
        return fetch_url(url)
    except ValueError as e:
        print(f"Fetch failed: {e}")
        if input("Paste the text manually instead? [Y/n] ").strip().lower() in ("", "y", "yes"):
            return manual_source(url)
        raise SystemExit(1)


def main(argv: list[str]) -> None:
    url = "" if not argv or argv[0] == "--paste" else argv[0]
    if not argv:
        sys.exit(__doc__)
    src = get_source(url)
    print(f"\n--- {src.source_type} | {len(src.text)} chars | title: {src.title!r} "
          f"| author: {src.author!r} | published: {src.published!r}")
    print(src.text[:1500])
    if len(src.text) > 1500:
        print(f"\n... [{len(src.text) - 1500} more chars]")


if __name__ == "__main__":
    main(sys.argv[1:])
