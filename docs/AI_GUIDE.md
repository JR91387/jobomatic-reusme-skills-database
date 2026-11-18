![Job-o-Matic Resume Builder](assets/wordmark.svg)

# Job-o-Matic: guide for the AI

You are helping one person keep their career facts in Job-o-Matic. This file is the
store you read from when you write their resumes, cover letters and interview answers.
The person sets it up once and then mostly leaves it alone, so **you** do most of the
reading and writing. They review what you did.

## Where things are
```
Job-o-Matic/
  my_data/jobomatic.db         the database (SQLite, one person)
  my_data/originals/<kind>/    their past documents, kept exactly as they gave them
  my_data/resumes/             resumes you generate (HTML, print to PDF)
  Job-o-Matic (view only).html what the person looks at; rebuilt after every change
  app/                         the program (do not edit)
  python/                      the bundled Python (do not edit)
```

## Two ways in
1. **MCP tools** (any MCP app, Claude Desktop for example), 15 of them: `schema_guide`,
   `resume_data`, `search`, `get_profile`, `list`, `get`, `save`, `save_many`, `retire`,
   `list_originals`, `add_original`, `read_original`, `mark_extracted`, `qa_open`,
   `build_resume`. Every write through `save`, `save_many`, `retire`, `add_original` and
   `mark_extracted` is recorded as `ai`.
2. **Command line** (AIs that can run commands), from the `Job-o-Matic` folder:
   - Windows: `python\python.exe app\src\db.py "SELECT * FROM people"`
   - macOS / Linux: `python/bin/python3 app/src/db.py "SELECT * FROM people"`
   - A file of changes: `... app/src/db.py --file changes.sql` (all saved together, or none).

## Fastest path to a resume
- **Start with `schema_guide`:** every table, column and rule in plain words
  (or `SELECT * FROM schema_guide`).
- **One call for a whole resume:** `resume_data(track)`, or
  `SELECT resume FROM resume_json WHERE track='Original'`. It returns one JSON document:
  the person, links, employers (each with its positions, so a promotion shows as two titles under
  one employer), each position's lines best first (Verified first, then Short, Long, then lines with no length; Story lines are
  for cover letters and interviews and never appear on a resume) with the item
  and metrics behind each line, plus `items` (awards, projects, reviews, publications, volunteer ...
  every kind except responsibilities and achievements), Verified skills and education.
- **Tailor to a job:** paste the whole job description into `search`. The best-matching
  lines, facts, skills and answers come back first, each with its table and id.
- **Store the item, its metrics, then lines.** Save the fact in `items`, each number in `item_metrics`
  (label, value, unit, as_of), and only then write `bullet_variants` from it. Never invent a number.

## Rules (the database enforces them)
- **Say who you are on every write:** set `updated_by='ai'` on every row you insert or
  update. A write without it is refused. (MCP does this for you.)
- **Never delete.** Retire instead: set `status` to `Deprecated` (most tables),
  `Archived` (people) or `Retired` (versions, table `tracks`). The `retire` tool picks the right one. Deletes are refused.
- **One person per install.**
- **Don't overwrite the person's edits.** When you update a row, pass the `updated_at` you
  read (`save(..., expected_updated_at=...)`). If they changed it since, nothing is written and
  you get an error: read the row again and merge.
- **Keep the person's own words.** Don't polish a fact into something they didn't do.
  Rows you add are marked `Needs review` until they confirm them: `items`, `item_metrics` and
  `bullet_variants` default to it, and the database flips your new `employers`, `positions`,
  `skills` and `education` rows (and `qa` answers) to it for you.

## What lives where
| Table | Holds |
|---|---|
| `people` | name, headline, contact details, summary |
| `links` | LinkedIn, portfolio, website |
| `employers` | who the person worked for: name, location |
| `positions` (view `experience`) | titles at an employer, with dates; a promotion is a second position under the same employer |
| `items` | one fact each: `kind` (Responsibility, Achievement, Award, Project, Review, Publication, Volunteer ...), title, detail, outputs; tied to a position (`position_id`, optional) and optionally nested under another item (`parent_item_id`) |
| `item_metrics` | the numbers behind an item, many per item: label, value, unit, as_of |
| `item_originals` | attachments: which original documents back an item (many to many) |
| `bullet_variants` (view `resume_lines`) | ready-made resume wordings of an item (`item_id`), per version (column `track`, e.g. Leadership) and `length` (Short, Long, Story) |
| `tracks` | the versions (angles) resume lines are written for |
| `skills`, `skill_links` | skills and where they were used |
| `education` | degrees, courses, certifications |
| `qa` | interview questions and their answers |
| `originals` | index of the unedited documents in `my_data/originals/`; `position_id` ties one to a job |
| `settings` | a few preferences |
| `audit` (view `last_change`) | every change, who made it and when |

## Filling it from their documents
The person drops past resumes, job descriptions, performance reviews and
recommendations into Originals. The app keeps each file unedited and saves its text
next to it (`<file>.txt`).
1. `list_originals` (or `SELECT * FROM originals WHERE extracted <> 'Done'`) to see
   what is waiting (`Text read` = text is ready, no facts taken yet; `Not yet` = no text layer).
2. `read_original(id)` for the text.
3. Put the facts in the right tables, then link each item to the document it came from with a row in
   `item_originals` (`item_id`, `original_id`). There is no `original_id` column on `items`.
4. `mark_extracted(id, 'Done')` (or `'Partly'`).

Trust documents by their `weight`: **3** = official (a performance review, a signed job
description), **2** = their own (a past resume), **1** = loose notes. When documents
disagree, prefer the higher weight and ask the person.
A scanned PDF has no text layer (`notes` says so). To store a new file yourself, use `add_original`
(give its full path); a raw SQL insert would skip the file copy, hash and text extraction. Ask the person to paste the text or
read it from an image if you can.

## Interview questions (Q&A)
The `qa` table starts with ten common interview questions and no answers.
- `qa_open` lists what still needs an answer.
- Work through them with the person, one at a time: ask, draft from their own facts,
  and let them change it. Save the answer with `status='Needs review'`, or `'Verified'`
  once they approve.
- Ask them which other questions they keep running into and add those
  (new rows get `seeded = 0` automatically). Every answer helps their resume and applications.
- Question 2 ("What do you know about our company…") changes per company: store a
  reusable frame and tailor it each time.

## Making a resume
`build_resume(template, track)` with template `executive`, `navy_bar`, `two_column`, `structured` or `genz`
writes an HTML file to `my_data/resumes/`. The person opens it and prints to PDF.
Only `resume_lines` that are not `Deprecated`, are tied to a position and are Short or Long appear (Story lines never do). Awards and Projects come from `items` by kind; a one-off item prints a single date.
