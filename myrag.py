"""MyRAG entry point (v1 through milestone 4): fetch -> summarize -> review.

Usage:
    python myrag.py <url> [--topic NAME]
    python myrag.py --paste [--topic NAME]
"""
import argparse
import os

from dotenv import load_dotenv

from fetch import get_source
from review import review
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

    src = get_source(args.url)
    print(f"Summarizing {len(src.text)} chars...")
    summary = summarize(src, forced_topic=args.topic)
    entry = review(src, summary, topics)
    if entry is None:
        return
    # Milestone 5 will save `entry`; for now just confirm.
    print(f"\nApproved (not saved yet - milestone 5): {entry.summary['title']!r} "
          f"| topic={entry.summary['topic']} | my_score={entry.my_score}"
          + (f" | NEW TOPIC {entry.new_topic}" if entry.new_topic else ""))


if __name__ == "__main__":
    main()
