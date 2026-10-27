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
- Summary language: technical English, optimized for LLM reading.
  Priority 1: the core idea is preserved and understandable to an LLM. Priority 2: short.
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
ai_score_reason: "one line"
my_score: 5
---
## Core idea
1-2 sentences.

## Key points
- ...

## Evidence / data
- ...

## Applicability
How/when to use this.

## Caveats
- ...
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
3. LLM step: one call returning JSON (summary sections, topic, tags, ai_score, reason).
4. Terminal review: show result, allow changing topic, give my_score, approve / reject / edit.
5. Save: write Markdown file, regenerate `INDEX.md`, git commit.

## Working agreement
- One Claude Code session per milestone. Update this file when a decision changes.
