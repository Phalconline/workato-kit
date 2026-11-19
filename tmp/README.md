# tmp/: your personal working cache

Everything in this folder except this file is git-ignored. It stays on your machine: nobody else
has your files, and you have nobody else's.

## What goes here

| Folder | Content | Written by |
|---|---|---|
| `wk/dev/<project-slug>/` | Dev recipe JSON and its `index.json` | `scripts/sync_recipes.py dev`, `scripts/lint_recipes.py` |
| `wk/lint.json` | the raw output of the last lint | `scripts/lint_recipes.py` |
| `wk/prod-drift/` | results of the Dev and Prod comparison | `scripts/prod_drift.py` |
| `wk/prod-jobs/` | reports of Prod jobs | `scripts/prod_jobs_report.py` |
| `<area>/<YYYY-MM-DD>-<topic>/` | the working material of one piece of work: raw findings, dumps, before and after copies for a push, drafts | you or your agent |

Name a piece of work by its area, its date and its topic, for example
`tmp/analysis/2030-01-31-invoice-retries/` or `tmp/evidence/2030-01-31-new-order-test/`.

The guard hook lets `wk ... -o <file>` write only below `tmp/`, and the option `--out` of
`scripts/prod_jobs_report.py` takes only a file below `tmp/`.

## Rules, for people and for agents

- Temporary files go here and nowhere else in the tree.
- Never link to a file in `tmp/` from a tracked file, and never rely on one being there. It may be
  missing or stale on another machine. `scripts/check_links.py` fails on such a link; this README
  is the one exception.
- Nothing from this folder is committed. When a result matters to the team, write the conclusion
  into `docs/` (the recipe doc, a runbook, the decision log) and leave the raw material here.
- Files here can contain personal data from jobs, such as e-mail addresses. Nothing is pasted
  into a doc without redaction: write `<user>`.
- What a script can rebuild (`wk/`) is safe to delete. Anything else here may be someone's only
  copy: look before you delete it, and an agent asks first.
- Never name a file here `CLAUDE.md`, `AGENTS.md` or `GEMINI.md`, in any letter case. Some file
  systems ignore case, and a harness loads a file with such a name as instructions for its folder,
  whatever it holds. Give a saved chat another name, such as `chat-2030-01-31.md`. For the same
  reason a full copy of the repository goes outside this tree.
