"""Milestone 4: terminal review of a summarized entry.

review(src, summary, topics) shows the summary, lets Shai fix the topic, give my_score / my_note,
then approve / edit / reject. Edit round-trips through a Markdown draft in drafts/.
Returns a ReviewedEntry on approve, None on reject. Writes nothing to the knowledge base.
"""
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from fetch import Source
from summarize import validate

DRAFTS_DIR = Path(__file__).parent / "drafts"
EDITOR_CMD = os.getenv("MYRAG_EDITOR", "code --wait")

SECTIONS = {  # heading -> (summary key, kind)
    "Core idea": ("core_idea", "str"),
    "Key points": ("key_points", "list"),
    "Evidence / data": ("evidence", "list"),
    "Applicability": ("applicability", "str"),
    "Caveats": ("caveats", "list"),
}


@dataclass
class ReviewedEntry:
    """Handed to milestone 5 (save). new_topic is (name, description) if Shai approved one."""
    source: Source
    summary: dict  # title, core_idea, key_points, evidence, applicability, caveats, topic, tags, ai_score, ai_score_reason
    my_score: int
    my_note: str
    new_topic: tuple[str, str] | None


# ---------- display ----------

_COLOR = sys.stdout.isatty()
if _COLOR and os.name == "nt":
    os.system("")  # enable ANSI escapes in the Windows console


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def _fmt(text: str) -> str:
    """Make '[model]:' items stand out."""
    return text.replace("[model]:", _c("1;33", "[model]:")) if "[model]:" in text else text


def _bullets(items: list[str]) -> None:
    for i, item in enumerate(items, 1):
        print(f"  {i}. {_fmt(item)}")
    if not items:
        print("  (none)")


def show(s: dict, src: Source, topics: dict[str, str], my_score: int | None, my_note: str) -> None:
    rule = "=" * 72
    print(f"\n{rule}\n{_c('1', s['title'])}")
    origin = src.url or "manual paste"
    print(f"{origin} | {src.author or 'author unknown'} | {src.published or 'date unknown'}")
    print(f"tags: {', '.join(s['tags'])}")
    if s["topic_is_proposal"]:
        print(_c("1;33", f"TOPIC: NEW TOPIC PROPOSED -> '{s['topic']}'")
              + f" - {s['proposed_topic_description']}")
        print("        (not in topics.yaml; needs your approval, or pick an existing topic)")
    else:
        print(f"TOPIC: {_c('1;32', s['topic'])} - {topics[s['topic']]}")
    print(f"\n{_c('1', 'Core idea')}\n  {_fmt(s['core_idea'])}")
    print(f"\n{_c('1', 'Key points')}")
    _bullets(s["key_points"])
    print(f"\n{_c('1', 'Evidence / data')}")
    _bullets(s["evidence"])
    print(f"\n{_c('1', 'Applicability')}\n  {_fmt(s['applicability'])}")
    print(f"\n{_c('1', 'Caveats')}")
    _bullets(s["caveats"])
    print(f"\nai_score: {s['ai_score']}/5 - {_fmt(s['ai_score_reason'])}")
    if my_score:
        print(f"my_score: {my_score}/5" + (f" | note: {my_note}" if my_note else ""))
    print(rule)


# ---------- prompts ----------

def pick_topic(s: dict, topics: dict[str, str]) -> None:
    """Resolve the topic in place. A proposed topic must be approved or replaced."""
    names = list(topics)
    print("\nTopics:")
    for i, n in enumerate(names, 1):
        print(f"  {i}. {n} - {topics[n]}")
    while True:
        if s["topic_is_proposal"]:
            prompt = f"Approve NEW topic '{s['topic']}'? [y] yes, or number of an existing topic: "
        else:
            prompt = f"Topic '{s['topic']}' - Enter to keep, or number to change: "
        ans = input(prompt).strip().lower()
        if ans in ("y", "yes") and s["topic_is_proposal"]:
            return
        if ans == "" and not s["topic_is_proposal"]:
            return
        if ans.isdigit() and 1 <= int(ans) <= len(names):
            s["topic"] = names[int(ans) - 1]
            s["topic_is_proposal"] = False
            s["proposed_topic_description"] = ""
            return
        print("  Invalid choice.")


def ask_score(current: int | None) -> int:
    while True:
        hint = f" (Enter keeps {current})" if current else ""
        ans = input(f"my_score 1-5{hint}: ").strip()
        if not ans and current:
            return current
        if ans in ("1", "2", "3", "4", "5"):
            return int(ans)
        print("  Enter a whole number 1-5.")


def ask_note(current: str) -> str:
    hint = f" (Enter keeps: {current!r}; '-' clears)" if current else " (Enter to skip)"
    ans = input(f"my_note, one line{hint}: ").strip()
    if ans == "-":
        return ""
    return ans or current


# ---------- draft round-trip ----------

def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "entry"


def write_draft(path: Path, s: dict, my_score: int | None, my_note: str) -> None:
    meta = {k: s[k] for k in ("title", "topic", "tags", "ai_score", "ai_score_reason")}
    meta["my_score"] = my_score
    meta["my_note"] = my_note
    if s["topic_is_proposal"]:
        meta["proposed_topic_description"] = s["proposed_topic_description"]
    out = ["---", yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1000).strip(), "---"]
    for heading, (key, kind) in SECTIONS.items():
        out.append(f"## {heading}")
        out.append(s[key] if kind == "str" else "\n".join(f"- {x}" for x in s[key]))
        out.append("")
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")


def read_draft(path: Path, old: dict, topics: dict[str, str]) -> tuple[dict, int | None, str]:
    """Parse an edited draft. Raises ValueError with a readable message if malformed."""
    text = path.read_text(encoding="utf-8-sig")
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", text, re.S)
    if not m:
        raise ValueError("front matter (--- block) is missing")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"front matter is not valid YAML: {e}")
    s = dict(old)
    for k in ("title", "topic", "tags", "ai_score", "ai_score_reason"):
        if k in meta:
            s[k] = meta[k]
    s["topic_is_proposal"] = s["topic"] not in topics
    s["proposed_topic_description"] = (
        str(meta.get("proposed_topic_description") or old["proposed_topic_description"])
        if s["topic_is_proposal"] else "")
    parts = re.split(r"^## (.+?)\s*$", m.group(2), flags=re.M)
    found = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    for heading, (key, kind) in SECTIONS.items():
        if heading not in found:
            raise ValueError(f"section '## {heading}' is missing")
        body = found[heading]
        if kind == "str":
            s[key] = body
        else:
            s[key] = [re.sub(r"^[-*]\s+", "", ln.strip()) for ln in body.splitlines() if ln.strip()]
    errors = validate(s, topics)
    if errors:
        raise ValueError("; ".join(errors))
    score = meta.get("my_score")
    if score is not None and score not in (1, 2, 3, 4, 5):
        raise ValueError("my_score must be 1-5 or empty")
    return s, score, str(meta.get("my_note") or "")


def edit_draft(s: dict, topics: dict[str, str], my_score: int | None, my_note: str):
    """Open a draft in the editor, reload it. Returns (summary, my_score, my_note) or None."""
    path = DRAFTS_DIR / f"{date.today()}-{_slug(s['title'])}.md"
    write_draft(path, s, my_score, my_note)
    try:
        while True:
            print(f"\nDraft: {path}\nEdit, save, and close the editor tab to continue...")
            try:
                subprocess.run(shlex.split(EDITOR_CMD, posix=False) + [str(path)], check=True,
                               shell=(os.name == "nt"))
            except (OSError, subprocess.CalledProcessError) as e:
                print(f"Could not run '{EDITOR_CMD}': {e}")
                return None
            try:
                return read_draft(path, s, topics)
            except ValueError as e:
                print(f"Draft problem: {e}")
                if input("Open it again to fix? [Y/n] ").strip().lower() in ("n", "no"):
                    return None
    finally:
        path.unlink(missing_ok=True)


# ---------- main loop ----------

def review(src: Source, summary: dict, topics: dict[str, str]) -> ReviewedEntry | None:
    s = dict(summary)
    my_score, my_note = None, ""
    while True:
        show(s, src, topics, my_score, my_note)
        pick_topic(s, topics)
        my_score = ask_score(my_score)
        my_note = ask_note(my_note)
        print(f"\nTopic: {s['topic']}" + (" (NEW, approved)" if s["topic_is_proposal"] else "")
              + f" | my_score: {my_score}" + (f" | note: {my_note}" if my_note else ""))
        while True:
            ans = input("[a]pprove / [e]dit / [r]eject: ").strip().lower()
            if ans in ("a", "e", "r"):
                break
        if ans == "r":
            print("Rejected. Nothing saved.")
            return None
        if ans == "a":
            new_topic = (s["topic"], s["proposed_topic_description"]) if s["topic_is_proposal"] else None
            out = {k: v for k, v in s.items() if k not in ("topic_is_proposal", "proposed_topic_description")}
            return ReviewedEntry(src, out, my_score, my_note, new_topic)
        edited = edit_draft(s, topics, my_score, my_note)
        if edited:
            s, edited_score, my_note = edited
            my_score = edited_score or my_score
