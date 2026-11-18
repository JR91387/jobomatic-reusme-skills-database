# Quick Start for AI

You are helping one person keep their career facts in Job-o-Matic. You do most of the reading and writing. They review.

## Three ways in

### 1. MCP tools (best)
Any MCP app (Claude Desktop, for example) can connect.

**Quickest: from PyPI.** No download needed; `uvx` fetches it, and a blank database is created on first run in the user data folder (`~/.local/share/job-o-matic`, `~/Library/Application Support/Job-o-Matic` or `%APPDATA%\Job-o-Matic`; set `JOBOMATIC_HOME` to choose another).
```json
{ "mcpServers": { "job-o-matic": { "command": "uvx", "args": ["job-o-matic-mcp"] } } }
```

**From the zip download:** the server is `app/src/jobomatic/mcp_server.py`. It takes the database path as `argv[1]`, or env `JOBOMATIC_DB`, or defaults to `my_data/jobomatic.db` in the install folder.

Config entry (what `scripts/connect_claude_desktop.py --write` adds for Claude Desktop):
```json
{ "mcpServers": { "job-o-matic": {
    "command": "<install>/python/bin/python3",
    "args": ["<install>/app/src/jobomatic/mcp_server.py"],
    "env": { "JOBOMATIC_DB": "<install>/my_data/jobomatic.db" } } } }
```
Tools: `schema_guide`, `resume_data`, `search`, `get_profile`, `list`, `get`, `save`, `save_many`, `retire`, `list_originals`, `add_original`, `read_original`, `mark_extracted`, `qa_open`, `build_resume`. Details: [[MCP-Tools]]. Every write through `save`, `save_many`, `retire`, `add_original` and `mark_extracted` is recorded as `ai`.

### 2. Command line (AIs that can run commands)
Run from the install folder.
```
# macOS / Linux
python/bin/python3 app/src/db.py "SELECT id, name FROM people"
python/bin/python3 app/src/db.py "UPDATE people SET headline='x', updated_by='ai' WHERE id=1"
python/bin/python3 app/src/db.py --file changes.sql     # all statements saved together, or none
# Windows
python\python.exe app\src\db.py "SELECT * FROM people"
```
A single `SELECT`, `WITH` or read-only `PRAGMA` is a read. Anything else is a write and must set `updated_by='ai'`. Do not put `BEGIN` or `COMMIT` in the SQL. Details: [[Command-Line]].

### 3. Copy a prompt (chat AIs with no tools)
The person clicks the robot button on a screen, or **Create Resume**, copies the prompt, pastes it into your chat, and pastes your answer back. You cannot read or write the file yourself here.

## Fastest path to a resume
1. Call `schema_guide` (or `SELECT * FROM schema_guide`). It explains every table, column and rule.
2. Call `resume_data(track)` (or `SELECT resume FROM resume_json WHERE track='Original'`). One JSON document: person, links, employers with positions, ranked lines with their item and metrics, `items`, Verified skills, education, `warnings`.
3. To tailor to a job, paste the whole job description into `search`. Best matches come back first, each with `source_table` and `source_id`.
4. Write the resume yourself from that JSON, or call `build_resume(template, track)` to get an HTML file the person prints to PDF. See [[Making-a-Resume]].
5. Tell the person about any `warnings` (rows still `Needs review`, skills hidden because not `Verified`).

## Must-follow rules
- Set `updated_by='ai'` on every row you insert or update. MCP does it for you. A write without it is refused. See [[Rules-and-Invariants]].
- Never delete. Retire: `status='Deprecated'` (most tables), `'Archived'` (`people`), `'Retired'` (`tracks`). The `retire` tool picks the right value.
- One Active person per install.
- Pass `expected_updated_at` (the `updated_at` you read) when you update a row. If the person changed it, nothing is written and the error carries the current row.
- Facts first, then lines: save the `items` row, each number in `item_metrics`, then write `bullet_variants`. Never invent a number.
- Keep the person's own words. Rows you add start as `Needs review`. Ask before saving many rows.
- A resume line's `track` must already exist in `tracks`.
- Dates are `YYYY` or `YYYY-MM`. An empty `end_date` on a position means current.

## Where to go next
- [[Data-Model]] for the tables and how they link
- [[Filling-From-Documents]] to load the person's past documents
- [[Interview-QA]] to answer interview questions with them
- [[Table-Reference]], [[MCP-Tools]], [[Command-Line]] for exact names
