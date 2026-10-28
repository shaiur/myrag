"""Milestone 3: one LLM call (OpenRouter) that turns a Source into a structured summary.

Usage:
    python summarize.py <url>      # fetch (paste fallback), summarize, print JSON
    python summarize.py --paste    # paste text directly, summarize, print JSON
"""
import json
import os
import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

from fetch import Source, get_source

MAX_INPUT_CHARS = 150_000  # ~40k tokens; caps cost on very long pages
TOPIC_SLUG = re.compile(r"^[a-z][a-z0-9-]*$")

SYSTEM_PROMPT = """You summarize sources into Shai's personal knowledge base.

Who reads this: not a human, but an AI agent that will later act on Shai's behalf: write code,
design a test strategy, make an investment decision, write a post. It reads this entry
instead of the source, and must come away thinking about the subject the way Shai would
after reading it.

Guiding rule: summarize the idea (what and why), not the implementation (how, with which tool).
No tool names, versions or code examples anywhere, including caveats and [model] items.
Write "tooling advice is dated (2018)" instead of naming the newer tools.
- Keep: principles, non-obvious insights, trade-offs, and caveats that affect how much to
  trust the source (e.g. "written in 2018, tools are dated"; "the author is an investor in
  the company he recommends").
- Drop: tool lists, versions, citations, examples that only illustrate a point already made,
  and point-in-time numbers that go stale (e.g. today's stock price).

Only from the source: state only what the source says.
Outside knowledge is allowed only when it helps judge the source (dated, biased, contradicted).
Mark every such item inline with the prefix "[model]:" so an agent can tell it apart from the
source, and say what it adds or contradicts.

Write in plain technical English. No filler, no marketing tone, no "the article discusses".
There are no word limits: length follows substance. A short article with one strong idea gets
a short entry; a long article that repeats itself does not get a long one.

Fields:
- core_idea: this is the entry's line in INDEX.md. It must stand alone: an agent reading only
  this line must be able to tell whether the entry is relevant to its task.
- key_points: each item is exactly one sentence with one claim; no semicolons joining two
  claims. No repetition: merge points that say the same thing. The goal is the source's real
  substance, not more points. Before answering, merge any two points an agent would act on
  the same way.
- evidence: only real data or experience-based evidence that backs the claims (measurements,
  study results, "we did X for N years and saw Y"). Not a list of who is cited or which tools
  appear in examples. Code samples and demos are never evidence. Empty list if there is none.
- applicability: when and how an agent should use this, and when not.
- caveats: what limits how much to trust or apply the source. Empty list if none.

{classification}

Score the source 1-5 ("ai_score") on these criteria, combined:
- source credibility
- evidence / data backing the claims
- actionability
- novelty vs. common takes
"ai_score_reason" is one line naming the criteria that drove the score.

Return ONLY a JSON object, no prose, no code fences, with exactly these keys:
{{
  "title": "string, the source's title (clean it up or write one if missing)",
  "core_idea": "string",
  "key_points": ["one sentence", ...],
  "evidence": ["string", ...],
  "applicability": "string",
  "caveats": ["string", ...],
  "topic": "string",
  "topic_is_proposal": false,
  "proposed_topic_description": "",
  "tags": ["2-6 tags, lowercase-kebab-case", ...],
  "ai_score": 1,
  "ai_score_reason": "string"
}}"""

CLASSIFY_FREE = """Classify the source into exactly one topic from this closed list:
{topics}

If none of the topics fits, propose a new one: a short lowercase slug (letters, digits, hyphens),
set "topic_is_proposal": true and give a one-line "proposed_topic_description".
Otherwise "topic_is_proposal" is false and "proposed_topic_description" is ""."""

CLASSIFY_FIXED = """The topic is already decided: "{topic}" ({desc}). Use it as "topic" with
"topic_is_proposal": false and "proposed_topic_description": "". Do not classify."""

LIST_FIELDS = ("key_points", "evidence", "caveats", "tags")
STR_FIELDS = ("title", "core_idea", "applicability", "topic", "ai_score_reason")


def load_topics(kb_path: str) -> dict[str, str]:
    path = Path(kb_path) / "topics.yaml"
    topics = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    if not topics:
        raise SystemExit(f"no topics in {path}")
    return topics


def build_user_message(src: Source) -> str:
    text = src.text
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS] + "\n[... truncated]"
    meta = "\n".join(f"{k}: {v}" for k, v in (
        ("source_type", src.source_type), ("url", src.url), ("title", src.title),
        ("author", src.author), ("published", src.published)) if v)
    return f"{meta}\n\n--- SOURCE TEXT ---\n{text}"


def parse_json(raw: str) -> dict:
    """Parse the model output; tolerate code fences or text around the object."""
    raw = raw.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in the response")
    return json.loads(raw[start:end + 1])


def validate(data: dict, topics: dict[str, str]) -> list[str]:
    """Return a list of problems; empty list means valid."""
    errors = []
    for f in STR_FIELDS:
        if not isinstance(data.get(f), str) or not data[f].strip():
            errors.append(f"'{f}' must be a non-empty string")
    for f in LIST_FIELDS:
        v = data.get(f)
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            errors.append(f"'{f}' must be a list of strings")
    if not data.get("key_points"):
        errors.append("'key_points' must not be empty")
    if not data.get("tags"):
        errors.append("'tags' must not be empty")

    score = data.get("ai_score")
    if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
        errors.append("'ai_score' must be an integer 1-5")

    proposal = data.get("topic_is_proposal")
    topic = data.get("topic")
    if not isinstance(proposal, bool):
        errors.append("'topic_is_proposal' must be true or false")
    elif isinstance(topic, str):
        if not proposal and topic not in topics:
            errors.append(f"topic '{topic}' is not in the list {list(topics)}; "
                          "pick one or set topic_is_proposal to true")
        if proposal:
            if topic in topics:
                errors.append(f"topic '{topic}' already exists; set topic_is_proposal to false")
            if not TOPIC_SLUG.match(topic):
                errors.append("a proposed topic must be a lowercase slug (a-z, 0-9, -)")
            desc = data.get("proposed_topic_description")
            if not isinstance(desc, str) or not desc.strip():
                errors.append("'proposed_topic_description' is required for a proposed topic")
    return errors


def summarize(src: Source, forced_topic: str = "") -> dict:
    """One LLM call returning validated summary JSON. Retries once if the JSON is invalid.

    forced_topic (must exist in topics.yaml) skips classification.
    """
    load_dotenv()
    api_key, model, kb_path = (os.getenv(k) for k in ("OPENROUTER_API_KEY", "MODEL", "KB_PATH"))
    if not (api_key and model and kb_path):
        raise SystemExit("OPENROUTER_API_KEY, MODEL and KB_PATH must be set in .env")
    topics = load_topics(kb_path)
    if forced_topic and forced_topic not in topics:
        raise SystemExit(f"unknown topic '{forced_topic}'; choose from {list(topics)}")
    topic_list = "\n".join(f"- {name}: {desc}" for name, desc in topics.items())
    if forced_topic:
        classification = CLASSIFY_FIXED.format(topic=forced_topic, desc=topics[forced_topic])
    else:
        classification = CLASSIFY_FREE.format(topics=topic_list)

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(classification=classification)},
        {"role": "user", "content": build_user_message(src)},
    ]
    for attempt in (1, 2):
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0.2)
        raw = resp.choices[0].message.content or ""
        try:
            data = parse_json(raw)
            errors = validate(data, topics)
            if forced_topic and data.get("topic") != forced_topic:
                errors.append(f"topic must be '{forced_topic}'")
        except ValueError as e:  # json.JSONDecodeError is a ValueError
            data, errors = None, [f"invalid JSON: {e}"]
        if not errors:
            return data
        print(f"Attempt {attempt}: invalid response: {'; '.join(errors)}", file=sys.stderr)
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "Your response was invalid: " + "; ".join(errors)
             + ". Return the corrected JSON object only."},
        ]
    raise SystemExit("LLM returned invalid JSON twice; giving up")


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit(__doc__)
    url = "" if argv[0] == "--paste" else argv[0]
    src = get_source(url)
    print(f"--- {src.source_type} | {len(src.text)} chars | summarizing...", file=sys.stderr)
    result = summarize(src)
    if result["topic_is_proposal"]:
        print(f"NEW TOPIC PROPOSED: {result['topic']} - {result['proposed_topic_description']}",
              file=sys.stderr)
    else:
        print(f"Topic chosen: {result['topic']}", file=sys.stderr)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
