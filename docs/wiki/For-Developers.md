# For Developers

Job-o-Matic is plain Python (standard library plus `mcp` and `pypdf`), SQLite and a static HTML/CSS/JS front end with no build step. The rules live in the database itself (CHECK constraints and triggers), so every client gets the same behaviour. Back to the [README](https://github.com/JR91387/jobomatic-reusme-skills-database#readme).

## Repo layout
```
src/db/            schema.sql (the rules live in SQL), schema_guide.sql, seed_blank.sql, seed_demo.sql
src/jobomatic/     store, originals + extract, helper (local edit server), viewer,
                   mcp_server, resume, demo
src/web/           the screens (plain HTML/CSS/JS, sql.js, no build step)
src/db.py          command-line access (see [[Command-Line]])
templates/         the five resume templates
scripts/           connector, bundle builder, demo and wiki generators
tests/             python -m unittest
docs/              AI_GUIDE.md, wiki/ (mirror of this wiki), assets/, screenshots/
demo/              the view-only demo page (generated)
```

## Install from PyPI
`pip install job-o-matic` (or `uvx job-o-matic-mcp`) gives three commands: `job-o-matic` (the screens), `job-o-matic-mcp` (the MCP server) and `job-o-matic-db` (SQL). Installed, the package's files live in `jobomatic/_data/` and data goes to the user data folder (`src/jobomatic/paths.py`). Releases publish to PyPI and the MCP Registry from `.github/workflows/publish.yml` when a GitHub Release is published.

## Tests
From the repo root, with `mcp` and `pypdf` installed (a virtual environment is easiest):
```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest
```

## Scripts
| Script | What it does |
|---|---|
| `scripts/build_bundles.py` | Builds the downloadable zips into `dist/`, one per platform. |
| `scripts/build_demo.py` | Writes `demo/Job-o-Matic demo (view only).html` from the fictional demo person. |
| `scripts/gen_wiki.py` | Regenerates [[Table-Reference]], [[MCP-Tools]] and [[Command-Line]] from the code; `--check` fails if they are stale or a link is broken. |
| `scripts/gen_triggers.py` | Regenerates the house triggers in `src/db/schema.sql` from its CREATE TABLE statements. |
| `scripts/make_demo_originals.py` | Regenerates the invented demo documents in `src/db/demo_originals/`. |
| `scripts/make_style_thumbs.mjs` | Renders a thumbnail of each resume style (needs Playwright). |
| `scripts/connect_claude_desktop.py` | Adds the MCP server to Claude Desktop's config (`--write`; preview without it). |

## After a schema or tool change
1. Edit `src/db/schema.sql` (and `schema_guide.sql` for the plain-language description).
2. Run `scripts/gen_triggers.py` if you added or changed a table.
3. Run `scripts/gen_wiki.py` and `scripts/build_demo.py`.
4. Run the tests. `tests/test_wiki.py` fails if the generated wiki pages are out of date.

The wiki's source of truth is `docs/wiki/` in the repo; copy those files to the wiki repo (`<repo>.wiki.git`) to publish.
