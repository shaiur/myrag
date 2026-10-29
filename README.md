# MyRAG

A terminal tool that turns a link (or pasted text) into a reviewed entry in a personal
knowledge base (KB) that AI agents can read.

The KB stores **lessons Shai has adopted**, not article summaries. An agent acting on his behalf
(writing code, designing a test strategy, making an investment decision, drafting a post) reads
the KB to act the way he would. Saving an entry means he agrees with it, so entries hold
conclusions and decisions, not the data that justified them.

## How it works

```
link ──► fetch text ──► one LLM call ──► human review ──► save entry + INDEX.md + git commit
            │                │                 │
      (paste fallback)  review_summary     approve / edit / reject
                        + KB entry
```

1. **Duplicate check.** Before fetching, the URL is compared with every saved entry's URL. The
   comparison normalizes the URL first: https, no `www.`, no fragment or trailing slash, and no
   tracking parameters (`utm_*`, `fbclid`, LinkedIn `trk`, …). On a match you choose:
   re-run and **replace** the old entry when you approve (it keeps the same id), **add** a second
   entry, or quit.
2. **Fetch.** The article text is extracted from the page. If that fails, or the text is shorter
   than 300 characters (paywall, login wall, JavaScript-only page), you are offered a manual
   paste. Input over 150,000 characters is truncated.
3. **One LLM call** (OpenRouter, model from `.env`) returns JSON with two parts:
   - **`review_summary`**, shown at review and **never saved**. It holds the source's key points
     with their numbers, the evidence and how strong it is, caveats (bias, datedness, weak
     method), and *model notes*: the model's own critiques and exceptions, from knowledge
     outside the source.
   - **The KB entry**, the part that is saved:
     - `core_idea`: what the source teaches, in one line. This is the entry's line in INDEX.md.
     - `takeaways`: one conclusion or decision per line, with no data or justification.
     - `limits`: optional. Only situations the source itself says a takeaway does not apply
       to. Usually empty.
     - `ai_score` and `ai_score_reason`, plus `topic` and `tags`.

   The saved entry follows these rules:
   - It contains only what the source says. Anything from the model's own knowledge stays in
     the model notes.
   - It describes ideas, not implementation: no tool names, versions or code. Tags may name
     tools.

   The response is validated: fields, a known topic, and no `[model]:` text in the saved part.
   If the JSON is invalid, the call is retried once with the errors.
4. **Review** in the terminal. The review summary is shown first, then the entry, labelled
   **WILL BE SAVED**. You then:
   - confirm or change the topic, or approve a newly proposed one
   - give `my_score` (1-5)
   - optionally write a one-line `my_note`
   - choose approve, edit or reject

   **Edit** opens the entry as a Markdown draft in your editor. When you close the draft it is
   re-read and re-validated. Edit and approve act on the KB entry only.
5. **Save.** The entry is written to `KB_PATH/<topic>/<id>.md`, where the id is
   `YYYY-MM-DD-title-slug`. If the topic is new it is added to `topics.yaml`. `INDEX.md` is then
   regenerated from all entry files, and these files are committed in the KB repo. Nothing is
   pushed.

**Topics** are a closed list in `KB_PATH/topics.yaml`. The model picks one and says which. If none
fits, it proposes a new slug and description, which you must approve at review. `--topic`
skips classification.

**Scores.** `ai_score` (1-5) is the model's rating of the source: credibility, evidence,
actionability, and novelty against common takes. `my_score` (1-5) is yours, given at review. The
two are stored separately and never merged, and any weighting between them is left to the agent
that reads them.

## Commands

| Command | What it does |
|---|---|
| `python myrag.py <url>` | Full flow: duplicate check, fetch, summarize, review, save, commit. |
| `python myrag.py --paste` | Same flow, but you paste the text. End it with a line containing only `END`, or Ctrl-Z then Enter. You are then asked for title, author and date (all optional). |
| `--topic NAME` | Works with either form above. Uses an existing topic and skips classification. |
| `python summarize.py <url>` / `--paste` | Debug: fetch and summarize, then print the JSON. Nothing is saved. |
| `python fetch.py <url>` / `--paste` | Debug: show the extracted text and metadata. |

Environment variable `MYRAG_EDITOR` sets the editor used by **edit**. The default is `code --wait`.

## Setup

Prerequisites:
- Python 3.10+ (developed on 3.14)
- git
- VS Code with `code` on PATH, or another editor set through `MYRAG_EDITOR`
- an [OpenRouter](https://openrouter.ai) API key

```bash
git clone <this repo> myrag && cd myrag
python -m venv venv
venv\Scripts\activate            # Windows; on macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # then fill it in
```

`.env` (gitignored, never commit it):
```
OPENROUTER_API_KEY=...                  # your OpenRouter key
MODEL=anthropic/claude-sonnet-5.5       # any OpenRouter model id
KB_PATH=/path/to/myrag-kb               # the knowledge base folder (its own git repo)
```

Create the knowledge base repo:
```bash
mkdir myrag-kb && cd myrag-kb && git init
```
Then create `topics.yaml` in it, with one `slug: one-line description` per topic:
```yaml
qa: Software testing, test automation, AI-assisted testing, QA process
development: Programming, software architecture, tools, AI/LLM engineering
investing: Markets, investing strategy, financial analysis
companies: Specific companies, products, news and company analysis
```
Topic folders and `INDEX.md` are created on the first save.

## How an agent uses the KB

1. Read `KB_PATH/INDEX.md` first. It has one line per entry:
   `id | topic | tags | ai_score | my_score | core_idea | path`.
2. Use `core_idea`, `topic`, `tags` and the scores to choose the relevant entries. Open only
   those, not every entry.
3. Treat an entry's takeaways as Shai's positions, and its limits as the cases where they do not
   apply. `my_score` is his judgment of the source; `ai_score` is a rough prior.

## Known limits

- LinkedIn, paywalled and JavaScript-only pages usually can't be fetched: use `--paste`.
  There is no automated LinkedIn login.
- One LLM call per link, plus one retry if the JSON is invalid. There are no follow-up passes.
  To change an entry, edit the draft at review.
- Input is cut at 150,000 characters.
- The duplicate check only works on URLs, not on pasted text without a URL.
- KB commits are local only. Push the KB repo yourself.

## Files

| File | Purpose |
|---|---|
| `myrag.py` | Entry point. Runs the whole flow: duplicate check, fetch, summarize, review, save. |
| `fetch.py` | Extracts article text and metadata from a URL, with a manual paste fallback. |
| `summarize.py` | Prompt, the single OpenRouter call, JSON parsing and validation, topic loading. |
| `review.py` | Terminal review screen, topic and score prompts, and the edit-draft round trip. |
| `save.py` | Writes the entry file, URL normalization and duplicate check, `INDEX.md`, KB git commit. |
| `requirements.txt` | Pinned dependencies. |
| `.env.example` | Template for `.env`. |
| `CLAUDE.md` | Project decisions and v1 scope: the source of truth for design choices. |
| `FUTURE_FEATURES.md` | Ideas deliberately left out of v1. |
