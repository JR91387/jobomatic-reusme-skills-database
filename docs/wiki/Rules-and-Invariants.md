# Rules and Invariants

The database enforces these. A write that breaks one is refused with the message shown, and nothing is saved. Source: `src/db/schema.sql`. Each rule names the table, trigger or constraint that enforces it. Connections run with `PRAGMA foreign_keys=ON`.

Plain-language copies of the rules are also in the `schema_guide` table (rows with `kind='rule'`).

## 1. Author: `updated_by` is required
- **What:** every INSERT and UPDATE must set `updated_by` to `'user'`, `'ai'` or `'app'`. You are `'ai'`.
- **Enforced by:** `CHECK (updated_by IN ('user','ai','app'))` on each table, plus triggers `<table>_need_by_ins` and `<table>_need_by_upd`. Tables: `people`, `links`, `images`, `employers`, `positions`, `originals`, `items`, `item_metrics`, `item_originals`, `tracks`, `bullet_variants`, `skills`, `skill_links`, `education`, `settings`, `qa`.
- **Error:** `updated_by is required: user, ai or app`
- **Detail:** after each write the trigger `<table>_after_ins` / `<table>_after_upd` stamps `updated_at`, copies `updated_by` into `audit.actor`, then sets `updated_by` back to NULL. State it again on every write. The MCP tools do this for you. In SQL:
```sql
UPDATE items SET status='Verified', updated_by='ai' WHERE id=5;
```

## 2. Retire, never delete
- **What:** DELETE is refused on every table.
- **Enforced by:** triggers `<table>_no_delete` on all 16 tables above plus `audit` (`audit_no_delete`).
- **Error:** `Do not delete: retire it by setting status`
- **Retire value by table:** `people` -> `Archived`; `tracks` -> `Retired`; `links`, `images`, `employers`, `positions`, `items`, `item_metrics`, `item_originals`, `bullet_variants`, `skills`, `skill_links`, `education`, `qa` -> `Deprecated`. `originals` and `settings` have no retire. The MCP `retire` tool picks the value.
- **Exception:** `search_index` is derived data and is rewritten by triggers.

## 3. One person per install
- **Enforced by:** triggers `people_one_ins`, `people_one_upd`. Only one `people` row may have `status='Active'`.
- **Error:** `One person per install`
- To start over with someone else, archive the current person first (`status='Archived'`).
- **Claiming:** when the first person is inserted, triggers `people_claims_qa` and `people_claims_originals` set `person_id` on every `qa` and `originals` row where it was NULL.

## 4. Authorship is append-only
- **Enforced by:** `audit_no_update` (`audit is append-only`) and `audit_no_delete`. `audit.op` is `'insert'` or `'update'`. `audit.actor` is `'user'`, `'ai'` or `'app'`.
- Only the `*_after_*` triggers write `audit`. Each row holds `table_name`, `row_id`, `old_json`, `new_json`, `at`.
- View `last_change` gives the latest `actor` and `at` per `(table_name, row_id)`. MCP `get` returns `created_by` and `last_changed_by`.

## 5. AI-added rows start as Needs review
- **Enforced by:** triggers `employers_ai_review`, `positions_ai_review`, `skills_ai_review`, `education_ai_review` (fire on `audit` insert). If actor is `ai`, op is `insert` and the new status is `Verified`, the row is flipped to `Needs review`.
- `qa_ai_review`: an AI insert with status `Needs answer` and a non-NULL `answer` becomes `Needs review`.
- `items`, `item_metrics`, `bullet_variants` default to `Needs review`. No trigger changes a status you choose there.
- To verify, UPDATE the row afterwards. `save_many` does many rows at once. The audit records that you did it. Do not mark facts `Verified` for the person without their say-so.

## 6. Status values (CHECK)
| Tables | Allowed `status` | Default |
|---|---|---|
| `employers`, `positions`, `skills`, `education` | `Verified`, `Needs review`, `Deprecated` | `Verified` |
| `items`, `item_metrics`, `bullet_variants` | `Verified`, `Needs review`, `Deprecated` | `Needs review` |
| `links`, `images`, `item_originals`, `skill_links` | `Active`, `Deprecated` | `Active` |
| `people` | `Active`, `Archived` | `Active` |
| `tracks` | `Active`, `Retired` | `Active` |
| `qa` | `Needs answer`, `Needs review`, `Verified`, `Deprecated` | `Needs answer` |

Printing: `resume_data` / `build_resume` skip `Deprecated` rows. Skills appear only when `Verified`.

## 7. Text must not be blank
Whitespace-only counts as blank.
| Column | Trigger | Error |
|---|---|---|
| `people.name` | `people_name_text_ins`, `people_name_text_upd` | `Name cannot be empty` |
| `employers.name` | `employers_name_text_ins/_upd` | `Employer cannot be empty` |
| `positions.title` | `positions_title_text_ins/_upd` | `Job title cannot be empty` |
| `items.title` or `items.detail` (one must have text) | `items_text_ins/_upd`, plus `CHECK (title IS NOT NULL OR detail IS NOT NULL)` | `Give the item a title or say what was done` |
| `item_metrics.value` | `item_metrics_value_text_ins/_upd` | `The metric value cannot be empty` |
| `bullet_variants.wording` | `bullet_variants_wording_text_ins/_upd` | `The wording cannot be empty` |
| `qa.question` | `qa_question_text_ins/_upd` | `The question cannot be empty` |

## 8. Dates
- **What:** `YYYY` or `YYYY-MM` (month `01` to `12`), or NULL. NULL `end_date` on a position means current ("Present").
- **Enforced by:** `positions_start_date_ins/_upd`, `positions_end_date_ins/_upd`, `education_start_date_ins/_upd`, `education_end_date_ins/_upd`, `items_start_date_ins/_upd`, `items_end_date_ins/_upd`.
- **Error:** `Dates are YYYY or YYYY-MM, like 2021 or 2021-06`
- Not enforced: that `end_date` is after `start_date`; that an item's dates fall inside its position's dates (the app only warns). Other date columns (`originals.doc_date`, `education.year`, `education.expires`, `item_metrics.as_of`) are free text. Use `YYYY-MM-DD` for `doc_date`.

## 9. Item nesting has no loops
- **Enforced by:** `CHECK (parent_item_id IS NOT id)`, `items_parent_loop_ins`, `items_parent_loop_upd` (walks the parent chain).
- **Error:** `An item cannot sit inside itself`

## 10. Versions (tracks)
- **Enforced by:** `bullet_variants_track_ins`, `bullet_variants_track_upd`: `bullet_variants.track` must equal an existing `tracks.name`.
- **Error:** `Unknown track: add it under Settings first`. Fix: insert into `tracks` first.
- `tracks.name` is `UNIQUE COLLATE NOCASE`. `bullet_variants.track` defaults to `'Original'`, which exists on a blank install.
- `tracks_rename`: renaming a track rewrites `bullet_variants.track` for all its lines.

## 11. Uniqueness
| Constraint | Meaning |
|---|---|
| `people.name` UNIQUE | one row per name |
| `employers` UNIQUE `(person_id, name COLLATE NOCASE)` | no duplicate employer, any case |
| `skills` UNIQUE `(person_id, name)` | no duplicate skill |
| `qa` UNIQUE `(person_id, question)` | no duplicate question |
| `originals.path` UNIQUE | one row per stored file |
| `tracks.name` UNIQUE NOCASE | one row per version |
| `settings.key` UNIQUE | |
| `images` UNIQUE `(person_id, sha256)` and index `images_one_active` | at most one `Active` headshot per person; retire the old one first |
| `item_originals` PRIMARY KEY `(item_id, original_id)` | one attachment per item and document |
| `skill_links` PRIMARY KEY `(skill_id, item_type, item_id)` | one link per skill and target |

## 12. Other CHECKs
- `originals.weight` between 1 and 3. `originals.extracted` in `Not yet`, `Text read`, `Partly`, `Done`. `originals.kind` in `Resume`, `Job description`, `Review`, `Recommendation`, `Other`, `AI output`.
- `bullet_variants.length` in `Short`, `Long`, `Story` (or NULL).
- `skill_links.item_type` in `position`, `item`, `education`.
- `qa.category` in `About you`, `Behavioral`, `Strengths`, `Motivation`, `Situational`, `Logistics`, `Other`. `qa.seeded` in 0, 1.
- `images.mime` in `image/png`, `image/jpeg`, `image/webp`, `image/gif`.
- Foreign keys: see [[Data-Model]].

## 13. Settings
- `settings_years_order`: `recent_years` must stay below `older_years`. Error: `The "Recent" years must be fewer than the older cutoff`.

## Rules the MCP layer adds (not the database)
- `save` / `save_many` accept only editable columns per table (see [[MCP-Tools]]). For example `images` allows `caption` and `status` only; `settings` allows `value` only; `originals` allows `title`, `doc_date`, `weight`, `position_id`, `extracted`, `notes`.
- `expected_updated_at` makes an update conditional on the row not having changed. If it changed, the error holds the current row. Merge into it.
- `add_original` refuses a file already stored (same `sha256`), a file over 25 MB, and a type that is not PDF, DOCX, TXT, MD, PNG or JPEG.
- `list` and `get` can read `audit` and `last_change`, never write them.
