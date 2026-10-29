# MyRAG — Project Context

Read this file at the start of every session. It holds the decisions made so far.

## Goal (the only goal of v1)
A terminal tool that takes a link (or pasted text), summarizes it for LLM consumption,
classifies it into a topic, scores it, lets Shai review and score it, and saves it
into a personal knowledge base that other AI agents can read.

**Done = Shai pastes a link and a reviewed entry lands in the knowledge base, committed to git.**

## SCOPE RULE (important)
Shai tends to add features instead of finishing. If a request is not needed for the v1
goal above, push back and log it in `FUTURE_FEATURES.md` (one line: date + idea) and do not implement it. Go along only if he insists.

## Decisions
- Language: Python, VS Code, terminal only (no UI in v1).
- LLM: called through OpenRouter (OpenAI-compatible API), Claude model. Model name in config, not hard-coded.
- Secrets: API key lives in `.env` (gitignored). Never paste keys into chat or code.
- Storage: local folder of Markdown files, versioned with git (private GitHub backup).
  One file per entry, in a folder per topic. Move to a DB later (see FUTURE_FEATURES.md).
- Knowledge base lives in its own folder/repo; its path is set in `.env` (`KB_PATH`).
- Input: URL → automatic text extraction. Fallback: manual paste (for LinkedIn, paywalls).
  No automated LinkedIn login in v1.
- Summary language: technical English, optimized for LLM reading. The reader is an AI agent
  acting on Shai's behalf (code, test strategy, investment decision, post).
- The KB stores the lessons Shai adopts, not article summaries. Saving an entry means he agrees,
  so justification (data, statistics, studies) does not go in the KB.
- One LLM call returns two parts:
  - `review_summary` (key points with data, evidence, caveats): shown at review so Shai can
    judge the source. NOT saved.
  - The KB entry: `core_idea` (what the source teaches, one line, the INDEX.md line),
    `takeaways`, optional `limits`, `ai_score` + `ai_score_reason`.
- Takeaways: each one a conclusion or decision, one sentence, no justification, no numbers
  unless the number itself is the decision ("Replace fixed sleeps with condition-based waits",
  not "Async wait causes ~45% of flaky tests..."). A short "because ..." (a few words, no data)
  only when an expert could not infer the reason. Keep the source's priority words ("top cause",
  "first"). Merge takeaways an agent would act on the same way. Say what to do, not how it is
  built (drop details like "through decoupled queues").
- Limits: when a takeaway does NOT apply. A limit never restates another takeaway; "what to do
  instead" only when it is new. Each limit quotes a few words of its takeaway,
  never its position (takeaways get reordered at review). Source bias or datedness goes in `ai_score_reason`.
- Entry principle: the idea (what and why), not the implementation (how, with which tool):
  no tool names, versions or code examples in the entry. Code samples and demos are never
  evidence. No word limits.
- Only from the source: outside knowledge is allowed only to judge the source (dated, biased,
  contradicted) and is marked inline with "[model]:". In the entry, "[model]:" items appear
  only in Limits. [model]: items are the summarizing model's own notes, not Shai's positions;
  weigh them accordingly.
- Topics: closed list in `KB_PATH/topics.yaml`. The agent always says which topic it chose.
  If nothing fits, it proposes a new topic and Shai approves. A `--topic` flag overrides classification.
- Scores: both stored separately, never merged at save time.
  - `ai_score` 1-5, criteria: source credibility, evidence/data, actionability, novelty vs. common takes.
  - `my_score` 1-5, given by Shai at review.
  - Any weighting between them is computed later at query time.

## Entry format
```markdown
---
id: 2026-10-26-short-slug
url: https://...
source_type: url | manual
title: ...
author: ...
published: 2026-10-20        # if known
saved: 2026-10-26
topic: qa
tags: [automation, ai-testing]
ai_score: 4
ai_score_reason: "one line"    # source bias / datedness goes here
my_score: 5
my_note: "agree, except X"   # optional, one line, Shai's own take, filled in at review
---
## Core idea
What the source teaches, one standalone line (this is the entry's line in INDEX.md).

## Takeaways
- One conclusion or decision per line, no justification.

## Limits                     # optional; omitted when empty
- When a takeaway does not apply. "[model]:" items only here.
```

## Knowledge base layout
```
KB_PATH/
  topics.yaml          # allowed topics + one-line description each
  INDEX.md             # auto-generated: one line per entry (id, topic, tags, scores, core idea)
  qa/
  development/
  investing/
  companies/
```
`INDEX.md` + consistent tags are the only preparation for the future "suggest a post" feature.
No code for that feature in v1.

## v1 milestones
1. Project setup: venv, dependencies, `.env`, KB folder + `topics.yaml`, git init.
2. Fetch: URL → clean text; manual paste fallback.
3. LLM step: one call returning JSON (review_summary, KB entry sections, topic, tags, ai_score, reason).
4. Terminal review: show review_summary, then the KB entry labelled "WILL BE SAVED"; allow changing
   topic, give my_score, optional my_note input, approve / reject / edit (edit acts on the KB entry only).
5. Save: write Markdown file, regenerate `INDEX.md`, git commit.

## Working agreement
- One Claude Code session per milestone. Update this file when a decision changes.
