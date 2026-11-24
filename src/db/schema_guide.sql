-- Plain-language guide to every table, view, column and rule, for people and AI. Runs after schema.sql.
-- Read-only once seeded: change it here and rebuild, never by hand.
CREATE TABLE schema_guide (
  object       TEXT NOT NULL,
  column_name  TEXT,
  kind         TEXT NOT NULL CHECK (kind IN ('table','view','column','rule')),
  description  TEXT NOT NULL,
  example      TEXT,
  PRIMARY KEY (object, column_name)
);

BEGIN;
INSERT INTO schema_guide (object, column_name, kind, description, example) VALUES
  ('people', NULL, 'table', 'The person this career repository is about. One Active person per install.', NULL),
  ('people', 'name', 'column', 'Unique name the app uses for the person. Filled from first and last name when left empty.', 'Odalys Brannigan-Voss'),
  ('people', 'full_name', 'column', 'Name as printed on a resume. Saving first_name or last_name through the app or MCP sets it to "First Last".', 'Odalys Brannigan-Voss'),
  ('people', 'first_name', 'column', 'First (given) name, plus any middle names. Required for a new person.', 'Odalys'),
  ('people', 'last_name', 'column', 'Last (family) name. Required for a new person.', 'Brannigan-Voss'),
  ('people', 'other_names', 'column', 'Former or alternate names (for matching old documents).', 'Odalys Voss'),
  ('people', 'headline', 'column', 'One-line professional headline under the name.', 'Operations Coordinator - scheduling, inventory and vendor logistics'),
  ('people', 'location', 'column', 'City and state shown on the resume.', 'Springfield Heights, Ohio'),
  ('people', 'phone', 'column', 'Contact phone in international (E.164) form. The app and MCP accept any common format (US is assumed without a country code) and store it this way.', '+15555550142'),
  ('people', 'email', 'column', 'Contact email. Saved trimmed, with the part after @ in lower case.', 'odalys@example.com'),
  ('people', 'summary', 'column', 'Professional summary paragraph for the top of a resume.', NULL),
  ('people', 'work_authorization', 'column', 'Work authorization note, in the person''s words. Used when work_auth_status is Other.', 'Authorized to work in the United States'),
  ('people', 'work_auth_status', 'column', 'Can the person work in work_auth_country without the employer sponsoring a visa: Authorized, Needs sponsorship or Other.', 'Authorized'),
  ('people', 'work_auth_country', 'column', 'Country that work_auth_status is about.', 'United States'),
  ('people', 'status', 'column', 'Active or Archived. Archive instead of deleting.', 'Active'),

  ('links', NULL, 'table', 'Web links shown in the resume contact line. LinkedIn lives here (kind LinkedIn).', NULL),
  ('links', 'kind', 'column', 'LinkedIn, GitHub, Website, Portfolio or Other.', 'Website'),
  ('links', 'label', 'column', 'Text shown for the link; the URL is shown if empty.', 'Personal site'),
  ('links', 'url', 'column', 'The address.', 'https://odalys.example.com'),
  ('links', 'sort', 'column', 'Display order, low first.', '1'),
  ('links', 'status', 'column', 'Active or Deprecated.', 'Active'),

  ('images', NULL, 'table', 'Headshots. At most one Active per person: retire the old one first.', NULL),
  ('images', 'caption', 'column', 'Short description of the picture.', 'Headshot 2025'),
  ('images', 'mime', 'column', 'image/png, image/jpeg, image/webp or image/gif.', 'image/jpeg'),
  ('images', 'bytes', 'column', 'File size in bytes.', '48211'),
  ('images', 'sha256', 'column', 'Fingerprint of the picture; stops duplicates.', NULL),
  ('images', 'image', 'column', 'The picture itself (binary). Not copied into the audit log.', NULL),
  ('images', 'source', 'column', 'Where the picture came from.', 'Photographer, March 2025'),
  ('images', 'status', 'column', 'Active or Deprecated.', 'Active'),

  ('employers', NULL, 'table', 'Companies or organizations the person worked for. Positions belong to an employer, so a promotion is a second position under the same employer.', NULL),
  ('employers', 'name', 'column', 'Employer name, unique for the person ignoring case.', 'Brightwater Appliance Co.'),
  ('employers', 'location', 'column', 'City or region.', 'Dayton, OH'),
  ('employers', 'website', 'column', 'Employer website.', 'https://brightwater.example'),
  ('employers', 'notes', 'column', 'Private notes, not printed.', NULL),
  ('employers', 'status', 'column', 'Verified, Needs review or Deprecated.', 'Verified'),

  ('positions', NULL, 'table', 'Titles held: one row per title at an employer, from start_date to end_date. The Experience section of a resume.', NULL),
  ('positions', 'employer_id', 'column', 'The employer (employers.id).', '1'),
  ('positions', 'title', 'column', 'Job title.', 'Operations Coordinator'),
  ('positions', 'department', 'column', 'Department or team.', 'Distribution'),
  ('positions', 'start_date', 'column', 'Start Month, YYYY-MM (or a year, YYYY).', '2023-03'),
  ('positions', 'end_date', 'column', 'End Month, YYYY-MM (or a year, YYYY). Empty means current.', NULL),
  ('positions', 'sort_order', 'column', 'Resume order, 1 = first shown; empty sorts last, then newest start first.', '1'),
  ('positions', 'notes', 'column', 'Private notes, not printed.', 'Current role.'),
  ('positions', 'status', 'column', 'Verified, Needs review or Deprecated.', 'Verified'),

  ('originals', NULL, 'table', 'Index of unedited source documents (past resumes, reviews, job descriptions) kept in the originals/ folders. The files are never changed.', NULL),
  ('originals', 'kind', 'column', 'Resume, Job description, Review, Recommendation, Other, or AI output (a file the AI wrote, e.g. a draft it returns).', 'Review'),
  ('originals', 'path', 'column', 'Relative path of the file; its extracted text sits beside it as <path>.txt.', 'originals/reviews/2024_review.pdf'),
  ('originals', 'title', 'column', 'Human title of the document.', '2024 annual performance review'),
  ('originals', 'doc_date', 'column', 'Date of the document itself, YYYY-MM-DD.', '2024-12-15'),
  ('originals', 'weight', 'column', 'Trust, 1-3: 3 official (review, signed job description), 2 own (past resume), 1 loose notes.', '3'),
  ('originals', 'position_id', 'column', 'The position this document is about (positions.id).', '1'),
  ('originals', 'sha256', 'column', 'Fingerprint of the file; detects edits or duplicates.', NULL),
  ('originals', 'bytes', 'column', 'File size in bytes.', '20480'),
  ('originals', 'extracted', 'column', 'How far facts have been pulled into the tables. Not yet = no text layer; Text read = text extracted automatically, facts not read yet; Partly or Done = set by the AI after it reads the text. Waiting for the AI = anything but Done.', 'Partly'),
  ('originals', 'notes', 'column', 'Notes, e.g. "no text layer" for a scanned PDF.', NULL),

  ('items', NULL, 'table', 'Everything done or received: projects, responsibilities, achievements, awards, publications, volunteer work, talks, recommendations, reviews and kudos. Usually under a position; an item with no position is the person''s own (an award or publication outside a job). Resume lines are worded from items.', NULL),
  ('items', 'position_id', 'column', 'The position it belongs to (positions.id); empty = not tied to a job.', '2'),
  ('items', 'parent_item_id', 'column', 'The item it sits inside (items.id), e.g. an achievement inside a project; empty = top level.', NULL),
  ('items', 'kind', 'column', 'Project, Responsibility, Achievement, Award, Publication, Volunteer, Speaking, Recommendation, Review or Kudos.', 'Achievement'),
  ('items', 'title', 'column', 'Short name: the project, award, paper or talk.', 'ERP migration'),
  ('items', 'detail', 'column', 'What was done, plainly, no spin (or what the review or recommendation says). Title or detail is required.', 'Merged 14 inventory spreadsheets into one shared tracker.'),
  ('items', 'outputs', 'column', 'Products or deliverables produced.', 'Shared inventory tracker; training guide'),
  ('items', 'organization', 'column', 'Who issued it or where it happened (awarding body, publisher, venue, volunteer group).', 'Red Cross'),
  ('items', 'from_whom', 'column', 'Person who gave the review, recommendation or kudos.', 'Priya Halvorsen'),
  ('items', 'start_date', 'column', 'Start Month, YYYY-MM (or a year, YYYY). Not tied to the position''s dates (rule:item_dates).', '2024-01'),
  ('items', 'end_date', 'column', 'End Month, YYYY-MM (or a year, YYYY). A one-off award or review has only one date.', '2024-12'),
  ('items', 'source', 'column', 'Where the fact comes from, in words.', '2024 review'),
  ('items', 'notes', 'column', 'Conflicting numbers or sources.', NULL),
  ('items', 'status', 'column', 'Verified, Needs review or Deprecated.', 'Verified'),

  ('item_metrics', NULL, 'table', 'The numbers that prove an item, one row per number; an item can have several.', NULL),
  ('item_metrics', 'item_id', 'column', 'The item (items.id).', '2'),
  ('item_metrics', 'label', 'column', 'What is measured.', 'weekly reconciliation time'),
  ('item_metrics', 'value', 'column', 'The number as it should be quoted (text, not computed).', '6 h to 1.5 h'),
  ('item_metrics', 'unit', 'column', 'Unit, if not already in value.', 'hours'),
  ('item_metrics', 'as_of', 'column', 'When it was measured, YYYY-MM or YYYY-MM-DD.', '2024-06'),
  ('item_metrics', 'sort', 'column', 'Display order, low first.', '100'),
  ('item_metrics', 'status', 'column', 'Verified, Needs review or Deprecated.', 'Verified'),

  ('item_originals', NULL, 'table', 'Attachments: which source documents (originals) back up which items. One document can back many items and one item many documents.', NULL),
  ('item_originals', 'item_id', 'column', 'The item (items.id).', '2'),
  ('item_originals', 'original_id', 'column', 'The document (originals.id).', '1'),
  ('item_originals', 'note', 'column', 'Where in the document, in words.', 'page 3, manager comment'),
  ('item_originals', 'status', 'column', 'Active or Deprecated.', 'Active'),

  ('tracks', NULL, 'table', 'Versions: named sets of resume lines aimed at one kind of job, e.g. Original, Leadership. Every resume line belongs to one version (column bullet_variants.track).', NULL),
  ('tracks', 'name', 'column', 'Version name, unique ignoring case. Renaming carries every line with it.', 'Leadership'),
  ('tracks', 'color', 'column', 'Display color in the viewer.', '#2563eb'),
  ('tracks', 'sort', 'column', 'Display order, low first.', '20'),
  ('tracks', 'status', 'column', 'Active or Retired.', 'Active'),

  ('bullet_variants', NULL, 'table', 'Resume lines: wordings of an item, one per version (column track), focus (column angle) and length.', NULL),
  ('bullet_variants', 'item_id', 'column', 'The item this line is worded from (items.id).', '2'),
  ('bullet_variants', 'wording', 'column', 'The line exactly as printed on a resume.', 'Merged 14 inventory spreadsheets into one shared tracker, reducing weekly reconciliation from 6 hours to 90 minutes.'),
  ('bullet_variants', 'angle', 'column', 'What the line emphasizes.', 'Efficiency'),
  ('bullet_variants', 'length', 'column', 'Short (one line), Long (two lines) or Story (a paragraph for cover letters and interviews; never printed on a resume).', 'Short'),
  ('bullet_variants', 'track', 'column', 'Version name (tracks.name); must exist first.', 'Original'),
  ('bullet_variants', 'source', 'column', 'Where the wording came from.', 'Past resume 2022'),
  ('bullet_variants', 'status', 'column', 'Verified, Needs review or Deprecated.', 'Verified'),

  ('skills', NULL, 'table', 'Skills, systems, applications and software, methods and standards. Only Verified ones print on a resume.', NULL),
  ('skills', 'name', 'column', 'Skill name, unique per person.', 'Inventory control'),
  ('skills', 'category', 'column', 'Skill, System, Application/Software, Method or Standard.', 'Method'),
  ('skills', 'status', 'column', 'Verified, Needs review or Deprecated.', 'Verified'),

  ('skill_links', NULL, 'table', 'Ties a skill to the position, item or education where it was used.', NULL),
  ('skill_links', 'skill_id', 'column', 'The skill (skills.id).', '3'),
  ('skill_links', 'item_type', 'column', 'position, item or education.', 'position'),
  ('skill_links', 'item_id', 'column', 'id of the row in the item_type table.', '1'),
  ('skill_links', 'status', 'column', 'Active or Deprecated.', 'Active'),

  ('education', NULL, 'table', 'Degrees, courses, certifications and training.', NULL),
  ('education', 'kind', 'column', 'Degree, Course, Certification, Training or Self-study.', 'Degree'),
  ('education', 'name', 'column', 'Name of the degree or credential.', 'B.A. in Business Administration'),
  ('education', 'institution', 'column', 'School or provider.', 'Fairmont Valley College'),
  ('education', 'location', 'column', 'City and state.', 'Fairmont, Ohio'),
  ('education', 'year', 'column', 'Year completed, shown on the resume.', '2016'),
  ('education', 'start_date', 'column', 'Start month, YYYY-MM.', NULL),
  ('education', 'end_date', 'column', 'End month, YYYY-MM.', NULL),
  ('education', 'expires', 'column', 'When a certification expires.', '2027-06'),
  ('education', 'credential_url', 'column', 'Link that verifies the credential.', NULL),
  ('education', 'status', 'column', 'Verified, Needs review or Deprecated.', 'Verified'),

  ('settings', NULL, 'table', 'App settings. Only value can be changed.', NULL),
  ('settings', 'key', 'column', 'Setting name used by the app.', 'recent_years'),
  ('settings', 'label', 'column', 'Name shown to the person.', 'Recent years'),
  ('settings', 'value', 'column', 'The setting value, as text.', '10'),
  ('settings', 'note', 'column', 'What the setting does.', NULL),

  ('qa', NULL, 'table', 'Interview question bank with the person''s answers. Ships with 10 common questions; add the ones actually met.', NULL),
  ('qa', 'question', 'column', 'The question.', 'Tell me about yourself / Walk me through your resume.'),
  ('qa', 'category', 'column', 'About you, Behavioral, Strengths, Motivation, Situational, Logistics or Other.', 'Behavioral'),
  ('qa', 'common_wordings', 'column', 'Other ways the question gets asked.', 'Would you relocate?'),
  ('qa', 'answer', 'column', 'The person''s answer; empty until answered.', NULL),
  ('qa', 'status', 'column', 'Needs answer, Needs review, Verified or Deprecated.', 'Needs answer'),
  ('qa', 'sort', 'column', 'Seed order 1-10; empty for added questions.', '1'),
  ('qa', 'seeded', 'column', '1 if it shipped with the app, 0 if added.', '0'),
  ('qa', 'notes', 'column', 'Notes, e.g. how to tailor the answer per company.', NULL),

  ('audit', NULL, 'table', 'Append-only history of every insert and update, written by triggers. Cannot be changed.', NULL),
  ('audit', 'at', 'column', 'When the write happened (UTC).', '2026-11-01T18:00:00.000Z'),
  ('audit', 'table_name', 'column', 'Table that was written.', 'skills'),
  ('audit', 'row_id', 'column', 'id of the row written.', '3'),
  ('audit', 'op', 'column', 'insert or update.', 'update'),
  ('audit', 'old_json', 'column', 'The row before the write (JSON); empty for inserts.', NULL),
  ('audit', 'new_json', 'column', 'The row after the write (JSON).', NULL),
  ('audit', 'actor', 'column', 'Who wrote it: user, ai or app.', 'ai'),

  ('schema_guide', NULL, 'table', 'This guide: one plain-language row per table, view, column and rule. Read-only.', NULL),
  ('schema_guide', 'object', 'column', 'Table or view name, or rule name for rules.', 'skills'),
  ('schema_guide', 'column_name', 'column', 'Column described; empty for a table, view or rule row.', 'category'),
  ('schema_guide', 'kind', 'column', 'table, view, column or rule.', 'column'),
  ('schema_guide', 'description', 'column', 'What it means, in plain words.', NULL),
  ('schema_guide', 'example', 'column', 'A sample value or statement.', NULL),

  ('search_index', NULL, 'table', 'Full-text index (SQLite FTS5) of employers, positions, items, metrics, resume lines, skills and Q&A. Kept current by triggers; retired rows drop out. Search it with the search tool, which ranks best match first.', 'SELECT source_table, source_id FROM search_index WHERE search_index MATCH ''"dispatch" OR "carrier"'' ORDER BY rank'),
  ('search_index', 'source_table', 'column', 'Table the text came from.', 'bullet_variants'),
  ('search_index', 'source_id', 'column', 'id of the row in source_table.', '3'),
  ('search_index', 'text', 'column', 'The searchable words (English word stems match: "negotiated" finds "negotiate").', NULL),

  ('experience', NULL, 'view', 'Positions that are not Deprecated, with their employer name, in resume order.', 'SELECT * FROM experience'),
  ('resume_lines', NULL, 'view', 'Every resume line joined to its item (kind, title, detail), person and position, including Deprecated ones.', 'SELECT * FROM resume_lines WHERE track = ''Original'''),
  ('resume_lines_ranked', NULL, 'view', 'Printable resume lines (line and item not Deprecated, not Story) with their item; line_rank 1 is the best line for that position and version (Verified first, then Short, then Long).', 'SELECT * FROM resume_lines_ranked WHERE track = ''Leadership'' AND line_rank <= 3'),
  ('profile_json', NULL, 'view', 'One row: everything about the Active person as one JSON document (person, links, employers, positions with their employer, items with their metrics, attachments (original_ids) and their position as employer and job_title, skills, education). Start here to answer interview questions or write a profile or section.', 'SELECT profile FROM profile_json'),
  ('resume_json', NULL, 'view', 'One row per version (column track): the whole resume of the Active person as one JSON document (person, links, employers each with their positions, each position with ranked Short and Long lines and items_without_lines (with metrics), Verified skills, education, items that are not responsibilities or achievements (awards, projects, publications ...), and warnings: printed rows still Needs review and skills hidden because not Verified). Start here to write a resume.', 'SELECT resume FROM resume_json WHERE track = ''Original'''),
  ('last_change', NULL, 'view', 'Who last changed each row (user, ai or app) and when. Read only; the MCP list tool reads it.', 'SELECT * FROM last_change WHERE table_name = ''skills'''),

  ('rule:author', NULL, 'rule', 'Every insert and update must set updated_by to user, ai or app; it is recorded in audit and then cleared, so state it again on every write. AI writes use ai.', 'UPDATE skills SET category = ''Method'', updated_by = ''ai'' WHERE id = 3'),
  ('rule:ai_review', NULL, 'rule', 'Rows you (the AI) add start as Needs review until the person confirms them, and so does a Q&A answer you write. Choose another status only on purpose.', NULL),
  ('rule:never_delete', NULL, 'rule', 'Never delete a row; retire it by setting status (Deprecated; people Archived; versions in tracks Retired). DELETE is refused.', 'UPDATE bullet_variants SET status = ''Deprecated'', updated_by = ''ai'' WHERE id = 9'),
  ('rule:one_person', NULL, 'rule', 'Only one Active person per install. The first person added claims the seeded questions and any originals added before a person existed.', NULL),
  ('rule:version_check', NULL, 'rule', 'Before updating a row you read earlier, pass its updated_at as expected_updated_at; if the person changed it since, nothing is written and you get the current row to merge.', 'UPDATE people SET headline = ''x'', updated_by = ''ai'' WHERE id = 1 AND updated_at IS ''<value you read>'''),
  ('rule:tracks', NULL, 'rule', 'A resume line''s version (column track) must already exist in tracks (add it first). Renaming a version renames it on all its lines. Lines default to the Original version.', NULL),
  ('rule:weights', NULL, 'rule', 'originals.weight is trust from 1 to 3: 3 official, 2 own, 1 loose notes (an AI output file starts at 1). When sources disagree, prefer the higher weight and note the conflict in items.notes.', NULL),
  ('rule:dates', NULL, 'rule', 'Dates are text: months as YYYY-MM (printed as "Mar 2023"), document dates as YYYY-MM-DD. Months are validated: only YYYY or YYYY-MM is accepted. An empty end_date on a position means current.', '2023-03'),
  ('rule:not_blank', NULL, 'rule', 'Typed text cannot be blank: people.name, employers.name, positions.title, items.title or items.detail (one of them), item_metrics.value, bullet_variants.wording and qa.question.', NULL),
  ('rule:provenance', NULL, 'rule', 'Who wrote a row is kept in audit, not in updated_by (cleared after each write). The MCP get tool returns created_by and last_changed_by; list reads audit and last_change.', NULL),
  ('rule:verified', NULL, 'rule', 'The AI may set status Verified; the audit records that the AI did it. A new row the AI adds still starts as Needs review (rule:ai_review), so verify by updating it. The MCP save_many tool updates many rows in one go, all or none.', NULL),
  ('rule:add_original', NULL, 'rule', 'Add a document with the app''s Upload or the MCP add_original tool (a file path and a kind; AI output for a file the AI wrote). Both copy it into originals/, extract its text and refuse a file already stored.', NULL),
  ('rule:facts_then_lines', NULL, 'rule', 'Store the item first (what was done, in items.detail) and each number that proves it in item_metrics, then write resume lines (bullet_variants) from the item. Never invent a number.', NULL),
  ('rule:item_dates', NULL, 'rule', 'An item''s dates are not required to fall inside its position''s dates (a project can run across a promotion); the app warns when they do not.', NULL),
  ('rule:nesting', NULL, 'rule', 'An item can sit inside another (parent_item_id), e.g. achievements inside a project; an item cannot sit inside itself, directly or through its parents.', NULL);

-- Columns every audited table shares.
INSERT INTO schema_guide (object, column_name, kind, description, example)
  SELECT m.name, c.name, 'column',
         CASE c.name
           WHEN 'id' THEN 'Row number; other tables point to it.'
           WHEN 'person_id' THEN 'The person this row belongs to (people.id).'
           WHEN 'updated_by' THEN 'Who is writing: user, ai or app. MCP sets this for you; db.py users must set it. Cleared after it is recorded in audit.'
           WHEN 'updated_at' THEN 'When the row last changed (UTC). Pass it back as expected_updated_at to avoid overwriting newer edits.'
         END,
         CASE c.name WHEN 'updated_by' THEN 'ai' WHEN 'updated_at' THEN '2026-11-01T18:00:00.000Z' END
  FROM sqlite_master m, pragma_table_info(m.name) c
  WHERE m.type = 'table' AND m.name NOT LIKE 'sqlite_%' AND m.name NOT LIKE 'search_index%'
    AND c.name IN ('id', 'person_id', 'updated_by', 'updated_at');
COMMIT;

CREATE TRIGGER schema_guide_no_insert BEFORE INSERT ON schema_guide
  BEGIN SELECT RAISE(ABORT, 'schema_guide is read-only'); END;
CREATE TRIGGER schema_guide_no_update BEFORE UPDATE ON schema_guide
  BEGIN SELECT RAISE(ABORT, 'schema_guide is read-only'); END;
CREATE TRIGGER schema_guide_no_delete BEFORE DELETE ON schema_guide
  BEGIN SELECT RAISE(ABORT, 'Do not delete: schema_guide is read-only'); END;
