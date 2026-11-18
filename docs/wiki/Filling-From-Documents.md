# Filling From Documents

The person drops past resumes, job descriptions, performance reviews and recommendations into the app's Originals screen. Job-o-Matic keeps each file unedited and saves its text beside it. Your job: turn that text into facts.

## The four steps
| Step | MCP tool | CLI equivalent (`src/db.py`) |
|---|---|---|
| 1. Add a file (if the person points you to one) | `add_original(path, kind, title=None)` | None. Use the app's Upload, or the MCP tool. A raw INSERT would need `sha256` and `bytes` and would skip text extraction. |
| 2. See what is waiting | `list_originals` | `SELECT id, kind, path, title, weight, extracted, notes FROM originals WHERE extracted <> 'Done'` |
| 3. Read the text | `read_original(id)` | Read the file `my_data/<path>.txt` next to the original (`path` is relative to `my_data/`). |
| 4. Save facts, link them, mark progress | `save` / `save_many`, then `mark_extracted(id, 'Done')` | `INSERT` / `UPDATE ... updated_by='ai'`, then `UPDATE originals SET extracted='Done', updated_by='ai' WHERE id=N` |

## Details
**Add.** `add_original` takes the full path of a file on the person's computer. `kind` is `Resume`, `Job description`, `Review`, `Recommendation`, `Other`, or `AI output` (a file you wrote). PDF, DOCX, TXT, MD, PNG or JPEG, up to 25 MB. The file is copied into `my_data/originals/<folder>/` and never changed. Its text is extracted. A file already stored is refused with its id (`Already stored as original N`). Default `weight`: Review 3, AI output 1, anything else 2.

**Extraction state** (`originals.extracted`):
- `Not yet`: no text layer (a scanned PDF or an image). `notes` says `no text layer`. Ask the person to paste the text, or read the image yourself if you can.
- `Text read`: text is ready, no facts taken yet.
- `Partly`, `Done`: set only by you, through `mark_extracted`. Use `Done` only when you took everything useful.

**Read.** `read_original(id)` returns the metadata plus `text`. If there is no `.txt` it returns `text: null` and a message.

**Trust.** `originals.weight`: 3 official (a performance review, a signed job description), 2 the person's own (a past resume), 1 loose notes. When documents disagree, prefer the higher weight, note the conflict in `items.notes`, and ask the person.

## Put the facts in the tables
Order matters. Ask before saving many rows.
1. `employers`, then `positions` (a promotion is a second position at the same employer).
2. `items` for each thing done or received. Put what was done in `detail`. Keep the person's words.
3. `item_metrics` for each number the document states. Never invent one.
4. `bullet_variants` (resume lines) written from the item. Track must exist in `tracks`.
5. `skills`, `education`, `links` as the document shows.
6. **Link each fact to its document:** insert into `item_originals`.
7. `mark_extracted(id, 'Done')`.

Example, after reading original 3 (a review of Odalys Brannigan-Voss):
```sql
INSERT INTO items (person_id, position_id, kind, title, detail, source, updated_by)
VALUES (1, 1, 'Achievement', 'Cut dock wait times',
        'Rebuilt the daily dock schedule so trucks no longer queue.', 'performance review', 'ai');
INSERT INTO item_metrics (item_id, label, value, unit, as_of, updated_by)
VALUES (last_insert_rowid(), 'Average truck wait', '35', 'percent less', '2024', 'ai');
```
`last_insert_rowid()` only works inside one `--file` run. Otherwise read the new id back first. Then:
```sql
INSERT INTO item_originals (item_id, original_id, note, updated_by) VALUES (<item id>, 3, 'page 2', 'ai');
UPDATE originals SET extracted='Done', updated_by='ai' WHERE id=3;
```
(Numbers above are made-up demo values, not from the shipped demo data.)

With MCP: `save('items', {...})`, `save('item_metrics', {...})`, `save('item_originals', {item_id, original_id, note})`, `mark_extracted(3, 'Done')`.

New rows start as `Needs review`. The person confirms them in the app. See [[Rules-and-Invariants]]. Next: [[Making-a-Resume]].
