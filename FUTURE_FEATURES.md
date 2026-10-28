# Future Features — ideas for after v1

Rule: nothing here gets built until v1 works and has been used for 1-2 weeks.
New ideas that come up during v1 go here, not into the code.

## v2 candidates
- **Suggest a post**: after saving, cross-reference the new entry with existing entries
  (same topic / shared tags), find connections and new insights, propose a post draft.
- **UI** instead of terminal.
- **Move to a database** (e.g. SQLite) when Markdown files get too many to scan.
- **Score weighting**: compare ai_score vs my_score over time and decide how much weight each gets.
- **Easier LinkedIn input** — note: automated login with username/password breaks LinkedIn's
  terms and can get the account blocked; check for a safe option before building.

## Parking lot (ideas raised during the build — logged only, not implemented)
Format: `- YYYY-MM-DD — idea (one line)`
- 2026-10-28 — Summary feedback loop: rate/comment on summary quality and use past feedback to improve the summary prompt automatically.
- 2026-10-28 — `--relevance-check` command: loop over all KB entries one at a time, send each to the LLM to check if it is still relevant (dated, contradicted by newer entries, low value), and recommend: keep / edit / delete / change score. Recommendations only; Shai approves each change.
- 2026-10-28 — Summary granularity: point count grows with "one claim per point" and the merge test didn't help (the two rules conflict). Revisit after ~2 weeks of real entries.
