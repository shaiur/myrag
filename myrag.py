"""MyRAG entry point (v1 through milestone 5): dedupe -> fetch -> summarize -> review -> save.

Usage:
    python myrag.py <url> [--topic NAME]
    python myrag.py --paste [--topic NAME]
"""
import argparse
import os

from dotenv import load_dotenv

from fetch import get_source
from review import review
from save import find_duplicate, save_entry
from summarize import load_topics, summarize


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize a link or pasted text into the knowledge base.")
    ap.add_argument("url", nargs="?", default="", help="link to fetch")
    ap.add_argument("--paste", action="store_true", help="paste the text instead of fetching")
    ap.add_argument("--topic", default="", help="existing topic name; skips classification")
    args = ap.parse_args()
    if bool(args.url) == args.paste:
        ap.error("give either a <url> or --paste")

    load_dotenv()
    kb_path = os.getenv("KB_PATH")
    if not kb_path:
        raise SystemExit("KB_PATH must be set in .env")
    topics = load_topics(kb_path)
    if args.topic and args.topic not in topics:
        raise SystemExit(f"unknown topic '{args.topic}'; choose from {', '.join(topics)}")

    dup = find_duplicate(kb_path, args.url)
    if dup:
        print(f"Already in the knowledge base: {dup}")
        if input("Continue anyway? [y/N] ").strip().lower() not in ("y", "yes"):
            return

    src = get_source(args.url)
    print(f"Summarizing {len(src.text)} chars...")
    summary = summarize(src, forced_topic=args.topic)
    entry = review(src, summary, topics)
    if entry is None:
        return
    path = save_entry(kb_path, entry)
    print(f"\nSaved and committed: {path}"
          + (f" (new topic '{entry.new_topic[0]}' added)" if entry.new_topic else ""))


if __name__ == "__main__":
    main()
