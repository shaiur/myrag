"""Milestone 3: one LLM call (OpenRouter) that turns a Source into a review summary (shown at
review, not saved) plus the knowledge base entry (core idea, takeaways, limits, score).

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

SYSTEM_PROMPT = """You process sources for Shai's personal knowledge base. The knowledge base
stores the lessons Shai adopts, not summaries of articles. One answer has two parts:

1. review_summary: for Shai's eyes only, shown while he decides whether he agrees with the
   source. It is NOT saved. It must let him judge the source: its claims, the data behind
   them, and its weaknesses.
2. The knowledge base entry (core_idea, takeaways, limits, ai_score): what gets saved if he
   approves. Saving means he agrees, so the entry states conclusions and decisions, never
   their justification. Who reads the entry: not a human, but an AI agent that will later act
   on Shai's behalf: write code, design a test strategy, make an investment decision, write a
   post. It reads the entry instead of the source and must act the way Shai would.

Rules for both parts:
- Only from the source: state only what the source says. Outside knowledge is allowed only
  when it helps judge the source (dated, biased, contradicted). Mark every such item inline
  with the prefix "[model]:" and say what it adds or contradicts.
- Plain technical English. No filler, no marketing tone, no "the article discusses". No word
  limits: length follows substance. A long article that repeats itself gets a short answer.
- Code samples and demos are never evidence.

Rule for the entry: capture the idea (what and why), not the implementation (how, with which
tool). No tool names, versions or code examples in core_idea, takeaways or limits. Drop
examples that only illustrate a point and point-in-time numbers that go stale.

Fields:
- review_summary.key_points: the source's main claims, one sentence each, with the numbers
  that back them. Merge points that say the same thing.
- review_summary.evidence: the data or experience behind the claims (measurements, study
  results, "we did X for N years and saw Y"), and how strong it is. Not a list of who is
  cited. Empty list if there is none.
- review_summary.caveats: what limits trust in the source: datedness, bias, conflicts of
  interest, weak method, claims without support. Empty list if none.
- core_idea: what the source teaches, one standalone line. It is the entry's line in INDEX.md:
  an agent reading only this line must be able to tell whether the entry is relevant.
  No judgment of the source here (bias, data quality): that goes in ai_score_reason.
- takeaways: each one a conclusion or decision an agent should act on, one sentence, one
  claim. No justification: no statistics, percentages, study names, company names or sample
  sizes, and no numbers unless the number itself is the decision.
  Good: "Replace fixed sleeps with condition-based waits."
  Bad: "Async wait causes ~45% of flaky tests and is usually fixed by condition-based waits."
  A takeaway may end with a short "because ..." (a few words, no data) only when an expert
  could not infer the reason; it lets an agent judge when the rule applies. Keep priority
  words from the source ("top cause", "first", "most important"). Merge any two takeaways an
  agent would act on the same way. No "[model]:" items in takeaways.
  Say what to do, not how it is built: drop mechanism and architecture details
  (e.g. "Isolate slow consumers", not "Isolate slow consumers through decoupled queues").
- limits: when a takeaway does NOT apply (context, scale, situation). Each limit names the
  situation; it refers to a takeaway in the list, not to something the entry does not say.
  Add what to do instead only when it is new: never restate another takeaway, and never
  write a limit that only says a takeaway does not cover what other takeaways already
  cover. Start each limit by quoting a few words of that takeaway in double quotes, e.g.
  "Replace fixed sleeps": ... Never refer to a takeaway by its position ("third takeaway",
  "#3"): takeaways get reordered at review. Same style as takeaways: no data, studies or
  numbers. Trust in the source (vendor bias, old or weak data, unverified claims) never goes
  here: it goes in ai_score_reason. "[model]:" items are allowed only here and must be
  marked. Empty list if none.

{classification}

Score the source 1-5 ("ai_score") on these criteria, combined:
- source credibility
- evidence / data backing the claims
- actionability
- novelty vs. common takes
"ai_score_reason" is one line naming the criteria that drove the score. Source bias or
datedness, if any, goes in this line.

Return ONLY a JSON object, no prose, no code fences, with exactly these keys:
{{
  "title": "string, the source's title (clean it up or write one if missing)",
  "review_summary": {{
    "key_points": ["one sentence", ...],
    "evidence": ["string", ...],
    "caveats": ["string", ...]
  }},
  "core_idea": "string",
  "takeaways": ["one sentence", ...],
  "limits": ["string", ...],
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

LIST_FIELDS = ("takeaways", "limits", "tags")
STR_FIELDS = ("title", "core_idea", "topic", "ai_score_reason")
REVIEW_FIELDS = ("key_points", "evidence", "caveats")  # review_summary lists, never saved


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
    if not data.get("takeaways"):
        errors.append("'takeaways' must not be empty")
    model_items = [x for x in [data.get("core_idea")] + list(data.get("takeaways") or [])
                   if isinstance(x, str) and "[model]:" in x]
    if model_items:
        errors.append("'[model]:' items are allowed only in 'limits', not in core_idea or takeaways")
    rs = data.get("review_summary")
    if not isinstance(rs, dict):
        errors.append("'review_summary' must be an object")
    else:
        for f in REVIEW_FIELDS:
            v = rs.get(f)
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                errors.append(f"'review_summary.{f}' must be a list of strings")
        if not rs.get("key_points"):
            errors.append("'review_summary.key_points' must not be empty")
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
