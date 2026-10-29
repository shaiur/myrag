"""Milestone 5: save a ReviewedEntry into the knowledge base.

save_entry(kb_path, entry) writes KB_PATH/<topic>/<id>.md, registers a new topic if needed,
regenerates INDEX.md from all entry files, and commits in the KB repo.
find_duplicate(kb_path, url) is the pre-fetch check on normalized URLs.
check_kb(kb_path) is the startup check that the KB is a git repo with topics.yaml.
"""
import os
import re
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import yaml

from review import OPTIONAL_SECTIONS, SECTIONS, ReviewedEntry, _slug
from summarize import PROJECT_DIR

TRACKING_PARAMS = {  # compared lowercase; utm_* is matched by prefix
    "fbclid", "gclid", "ref",
    # LinkedIn
    "trk", "trkinfo", "trackingid", "lipi", "licu", "midtoken", "midsig", "eid", "refid",
    "otptoken", "originalsubdomain", "rcm",
}

INDEX_HEADER = """# Knowledge base index

For AI agents: read this index first, then open only the entries that are relevant to your task.
Do not open every entry. This file is auto-generated from the entry files; do not edit it by hand.

Each entry holds lessons Shai has adopted from a source, not a summary of the source: treat its
takeaways as his own positions, and its limits as when they do not apply.
One line per entry, fields separated by ` | `:
`id | topic | tags | ai_score | my_score | core_idea | relative path`

- `ai_score` is the model's 1-5 rating of the source; `my_score` is Shai's own 1-5 rating. They are
  stored separately: weigh them yourself (my_score is the owner's judgment, ai_score is a rough prior).
- `core_idea` is what the source teaches, in one standalone line; the path points to the full entry.

"""


# ---------- startup check ----------

def _git_out(kb_path: Path, *args: str) -> str | None:
    """stdout of a git command in kb_path, or None if it fails."""
    try:
        r = subprocess.run(["git", "-C", str(kb_path), *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("git is not installed or not on PATH. Install git, then run again.")
    return r.stdout.strip() if r.returncode == 0 else None


def check_kb(kb_path: Path) -> None:
    """Exit with a fix-it message unless KB_PATH is a git repo root with topics.yaml.

    Runs at startup so a broken KB fails before any fetch or LLM call.
    """
    win = os.name == "nt"
    template = PROJECT_DIR / "kb_template" / "topics.example.yaml"
    mkdir = f'mkdir "{kb_path}"' if win else f'mkdir -p "{kb_path}"'
    copy = f'{"copy" if win else "cp"} "{template}" "{kb_path / "topics.yaml"}"'
    init = f'git -C "{kb_path}" init'
    problems, fixes = [], []
    if not kb_path.is_dir():
        problems.append("the folder does not exist")
        fixes += [mkdir, copy, init]
    else:
        if not (kb_path / "topics.yaml").is_file():
            problems.append("topics.yaml is missing")
            fixes.append(copy)
        top = _git_out(kb_path, "rev-parse", "--show-toplevel")
        if top is None:
            problems.append("it is not a git repository")
            fixes.append(init)
        elif Path(top).resolve() != kb_path.resolve():
            problems.append(f"it is not its own git repository (it is inside the repo at {top})")
            fixes.append(init)
        elif not (_git_out(kb_path, "config", "user.name") and _git_out(kb_path, "config", "user.email")):
            problems.append("git user.name / user.email are not set, so commits would fail")
            fixes += ['git config --global user.name "Your Name"',
                      'git config --global user.email "you@example.com"']
    if problems:
        raise SystemExit(
            f"Knowledge base is not ready: {kb_path}  (KB_PATH in .env)\n"
            + "".join(f"  - {p}\n" for p in problems)
            + "Fix it with:\n" + "".join(f"  {f}\n" for f in fixes)
            + "Then run again. See README.md, section Setup.")


# ---------- duplicate check ----------

def normalize_url(url: str) -> str:
    """Canonical form for comparison only: https, no www, no fragment/trailing slash/tracking params."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if parts.port:
        host += f":{parts.port}"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    return f"https://{host}{parts.path.rstrip('/')}" + (f"?{urlencode(sorted(query))}" if query else "")


def entry_files(kb_path: str | Path) -> list[Path]:
    """All entry files: Markdown files inside topic folders (not INDEX.md at the root)."""
    return sorted(p for p in Path(kb_path).glob("*/*.md"))


def read_entry(path: Path) -> tuple[dict, str]:
    """Return (frontmatter, body) of an entry file."""
    text = path.read_text(encoding="utf-8-sig")
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", text, re.S)
    if not m:
        raise ValueError(f"{path}: front matter is missing")
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def find_duplicate(kb_path: str | Path, url: str) -> Path | None:
    """Path of an existing entry with the same normalized URL, or None. Empty url: no check."""
    if not url:
        return None
    target = normalize_url(url)
    for path in entry_files(kb_path):
        existing = read_entry(path)[0].get("url")
        if existing and normalize_url(str(existing)) == target:
            return path
    return None


# ---------- writing ----------

def unique_id(kb_path: str | Path, base: str) -> str:
    """Add -2, -3, ... if an entry with this id exists in any topic folder."""
    taken = {p.stem for p in entry_files(kb_path)}
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def render_entry(entry: ReviewedEntry, entry_id: str) -> str:
    s, src = entry.summary, entry.source
    meta = {"id": entry_id}
    if src.url:
        meta["url"] = src.url
    meta["source_type"] = src.source_type
    meta["title"] = s["title"]
    if src.author:
        meta["author"] = src.author
    if src.published:
        meta["published"] = src.published
    meta.update(saved=str(date.today()), topic=s["topic"], tags=s["tags"], ai_score=s["ai_score"],
                ai_score_reason=s["ai_score_reason"], my_score=entry.my_score)
    if entry.my_note:
        meta["my_note"] = entry.my_note
    out = ["---", yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=10_000,
                                 default_flow_style=None).strip(), "---"]
    for heading, (key, kind) in SECTIONS.items():
        if heading in OPTIONAL_SECTIONS and not s[key]:
            continue
        out.append(f"## {heading}")
        out.append(s[key] if kind == "str" else "\n".join(f"- {x}" for x in s[key]) or "- (none)")
        out.append("")
    return "\n".join(out)


def add_topic(kb_path: Path, name: str, description: str) -> None:
    path = kb_path / "topics.yaml"
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    text += yaml.safe_dump({name: description}, allow_unicode=True, width=10_000)
    path.write_text(text, encoding="utf-8")
    (kb_path / name).mkdir(exist_ok=True)


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).replace("|", "/").strip()


def regenerate_index(kb_path: str | Path) -> Path:
    """Rebuild INDEX.md from all entry files, one line per entry, oldest first."""
    kb_path = Path(kb_path)
    lines = []
    for path in entry_files(kb_path):
        meta, body = read_entry(path)
        m = re.search(r"^## Core idea\s*\n(.*?)(?=^## |\Z)", body, re.S | re.M)
        core = _one_line(m.group(1)) if m else ""
        tags = ",".join(str(t) for t in meta.get("tags") or [])
        rel = path.relative_to(kb_path).as_posix()
        lines.append((str(meta.get("id", path.stem)), " | ".join(
            [str(meta.get("id", path.stem)), str(meta.get("topic", "")), tags,
             str(meta.get("ai_score", "")), str(meta.get("my_score", "")), core, rel])))
    index = kb_path / "INDEX.md"
    index.write_text(INDEX_HEADER + "\n".join(line for _, line in sorted(lines)) + "\n", encoding="utf-8")
    return index


def git_commit(kb_path: Path, paths: list[Path], message: str) -> None:
    rels = [str(p.relative_to(kb_path)) for p in paths]
    subprocess.run(["git", "-C", str(kb_path), "add", "--", *rels], check=True)
    subprocess.run(["git", "-C", str(kb_path), "commit", "-m", message, "--", *rels],
                   check=True, stdout=subprocess.DEVNULL)


def save_entry(kb_path: str | Path, entry: ReviewedEntry, replaces: Path | None = None) -> Path:
    """Write the entry, update topics/INDEX, commit. Returns the entry path.

    replaces: an existing entry file to delete; the new entry keeps its id.
    """
    kb_path = Path(kb_path)
    s = entry.summary
    touched = []
    if entry.new_topic:
        add_topic(kb_path, *entry.new_topic)
        touched.append(kb_path / "topics.yaml")
    if replaces:
        entry_id = replaces.stem
        replaces.unlink()
        touched.append(replaces)
    else:
        entry_id = unique_id(kb_path, f"{date.today()}-{_slug(s['title'])}")
    path = kb_path / s["topic"] / f"{entry_id}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(render_entry(entry, entry_id), encoding="utf-8")
    touched += [path, regenerate_index(kb_path)]
    verb = "Update" if replaces else "Add"
    git_commit(kb_path, list(dict.fromkeys(touched)), f"{verb} {entry_id} ({s['topic']})")
    return path
