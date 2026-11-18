-- Job-O-Matic schema v1. Rules live here: no deletes, author required, audit trail.
-- Every write must state updated_by (user, ai, app). The *_after_* trigger stamps updated_at,
-- logs the write to audit with that actor, then clears updated_by so the next write must state it again.
-- Trigger bodies are generated, one set per table; edit the pattern everywhere or none.

CREATE TABLE people (
  id                 INTEGER PRIMARY KEY,
  name               TEXT NOT NULL UNIQUE,
  full_name          TEXT,
  other_names        TEXT,
  headline           TEXT,
  location           TEXT,
  phone              TEXT,
  email              TEXT,
  linkedin           TEXT,
  summary            TEXT,
  work_authorization TEXT,
  status             TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Archived')),
  updated_by         TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at         TEXT
);

CREATE TABLE links (
  id          INTEGER PRIMARY KEY,
  person_id   INTEGER NOT NULL REFERENCES people(id),
  kind        TEXT NOT NULL CHECK (kind IN ('LinkedIn','GitHub','Website','Portfolio','Other')),
  label       TEXT,
  url         TEXT NOT NULL,
  sort        INTEGER NOT NULL DEFAULT 0,
  status      TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Deprecated')),
  updated_by  TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at  TEXT
);

-- Headshots only. At most one Active headshot per person: retire the old one first.
CREATE TABLE images (
  id          INTEGER PRIMARY KEY,
  person_id   INTEGER NOT NULL REFERENCES people(id),
  caption     TEXT,
  mime        TEXT NOT NULL CHECK (mime IN ('image/png','image/jpeg','image/webp','image/gif')),
  bytes       INTEGER NOT NULL,
  sha256      TEXT NOT NULL,
  image       BLOB NOT NULL,
  source      TEXT,
  status      TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Deprecated')),
  updated_by  TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at  TEXT,
  UNIQUE (person_id, sha256)
);
CREATE UNIQUE INDEX images_one_active ON images(person_id) WHERE status = 'Active';

CREATE TABLE employers (
  id          INTEGER PRIMARY KEY,
  person_id   INTEGER NOT NULL REFERENCES people(id),
  name        TEXT NOT NULL,
  location    TEXT,
  website     TEXT,
  notes       TEXT,
  status      TEXT NOT NULL DEFAULT 'Verified' CHECK (status IN ('Verified','Needs review','Deprecated')),
  updated_by  TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at  TEXT,
  UNIQUE (person_id, name COLLATE NOCASE)
);

-- A title held at an employer, from start_date to end_date (NULL = current). A promotion is a new position.
CREATE TABLE positions (
  id           INTEGER PRIMARY KEY,
  person_id    INTEGER NOT NULL REFERENCES people(id),
  employer_id  INTEGER NOT NULL REFERENCES employers(id),
  title        TEXT NOT NULL,
  department   TEXT,
  start_date   TEXT,
  end_date     TEXT,
  sort_order   INTEGER,
  notes        TEXT,
  status       TEXT NOT NULL DEFAULT 'Verified' CHECK (status IN ('Verified','Needs review','Deprecated')),
  updated_by   TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at   TEXT
);

CREATE TABLE originals (
  id           INTEGER PRIMARY KEY,
  person_id    INTEGER REFERENCES people(id),   -- NULL until the first person claims it
  kind         TEXT NOT NULL CHECK (kind IN ('Resume','Job description','Review','Recommendation','Other','AI output')),
  path        TEXT NOT NULL UNIQUE,   -- relative: originals/reviews/2024_review.pdf
  title        TEXT,
  doc_date     TEXT,                   -- date of the document itself
  weight       INTEGER NOT NULL DEFAULT 2 CHECK (weight BETWEEN 1 AND 3),
                                       -- trust: 3 = official (review, signed JD), 2 = own (past resume), 1 = loose notes
  position_id  INTEGER REFERENCES positions(id),
  sha256       TEXT NOT NULL,          -- detects edits or duplicates; the file is never changed
  bytes        INTEGER NOT NULL,
  extracted    TEXT NOT NULL DEFAULT 'Not yet' CHECK (extracted IN ('Not yet','Text read','Partly','Done')),
                                       -- Not yet = no text layer; Text read = text extracted automatically;
                                       -- Partly / Done are set only by the AI (mark_extracted)
  notes        TEXT,
  updated_by   TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at   TEXT
);

-- Everything done or received: under a position, or the person's own (position_id NULL);
-- parent_item_id nests an item in another (an achievement inside a project). Item dates are not tied to the
-- position's dates; the app warns when they fall outside.
CREATE TABLE items (
  id              INTEGER PRIMARY KEY,
  person_id       INTEGER NOT NULL REFERENCES people(id),
  position_id     INTEGER REFERENCES positions(id),
  parent_item_id  INTEGER REFERENCES items(id),
  kind            TEXT NOT NULL CHECK (kind IN ('Project','Responsibility','Achievement','Award','Publication',
                                                 'Volunteer','Speaking','Recommendation','Review','Kudos')),
  title           TEXT,
  detail          TEXT,
  outputs         TEXT,
  organization    TEXT,
  from_whom       TEXT,
  start_date      TEXT,
  end_date        TEXT,
  source          TEXT,
  notes           TEXT,
  status          TEXT NOT NULL DEFAULT 'Needs review' CHECK (status IN ('Verified','Needs review','Deprecated')),
  updated_by      TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at      TEXT,
  CHECK (title IS NOT NULL OR detail IS NOT NULL),
  CHECK (parent_item_id IS NOT id)
);

-- The numbers that prove an item, as quoted on a resume ("30%", "$1.2M"): text, not computed.
CREATE TABLE item_metrics (
  id          INTEGER PRIMARY KEY,
  item_id     INTEGER NOT NULL REFERENCES items(id),
  label       TEXT,
  value       TEXT NOT NULL,
  unit        TEXT,
  as_of       TEXT,
  sort        INTEGER NOT NULL DEFAULT 100,
  status      TEXT NOT NULL DEFAULT 'Needs review' CHECK (status IN ('Verified','Needs review','Deprecated')),
  updated_by  TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at  TEXT
);

-- Attachments: which originals back up which items (many to many).
CREATE TABLE item_originals (
  item_id      INTEGER NOT NULL REFERENCES items(id),
  original_id  INTEGER NOT NULL REFERENCES originals(id),
  note         TEXT,
  status       TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Deprecated')),
  updated_by   TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at   TEXT,
  PRIMARY KEY (item_id, original_id)
);

CREATE TABLE tracks (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
  color       TEXT,
  sort        INTEGER NOT NULL DEFAULT 100,
  status      TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Retired')),
  updated_by  TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at  TEXT
);

CREATE TABLE bullet_variants (
  id                 INTEGER PRIMARY KEY,
  item_id            INTEGER NOT NULL REFERENCES items(id),
  wording            TEXT NOT NULL,
  angle              TEXT,
  length             TEXT CHECK (length IN ('Short','Long','Story')),
  track              TEXT NOT NULL DEFAULT 'Original',
  source             TEXT,
  status             TEXT NOT NULL DEFAULT 'Needs review' CHECK (status IN ('Verified','Needs review','Deprecated')),
  updated_by         TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at         TEXT
);

CREATE TABLE skills (
  id         INTEGER PRIMARY KEY,
  person_id  INTEGER NOT NULL REFERENCES people(id),
  name       TEXT NOT NULL,
  category   TEXT CHECK (category IN ('Skill','System','Method','Standard')),
  status     TEXT NOT NULL DEFAULT 'Verified' CHECK (status IN ('Verified','Needs review','Deprecated')),
  updated_by TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at TEXT,
  UNIQUE (person_id, name)
);

-- Ties a skill to a position, item or education row; item_id is not an FK because the target table varies.
CREATE TABLE skill_links (
  skill_id    INTEGER NOT NULL REFERENCES skills(id),
  item_type   TEXT NOT NULL CHECK (item_type IN ('position','item','education')),
  item_id     INTEGER NOT NULL,
  status      TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Deprecated')),
  updated_by  TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at  TEXT,
  PRIMARY KEY (skill_id, item_type, item_id)
);

CREATE TABLE education (
  id              INTEGER PRIMARY KEY,
  person_id       INTEGER NOT NULL REFERENCES people(id),
  kind            TEXT NOT NULL CHECK (kind IN ('Degree','Course','Certification','Training','Self-study')),
  name            TEXT NOT NULL,
  institution     TEXT,
  location        TEXT,
  year            TEXT,
  start_date      TEXT,
  end_date        TEXT,
  expires         TEXT,
  credential_url  TEXT,
  status          TEXT NOT NULL DEFAULT 'Verified' CHECK (status IN ('Verified','Needs review','Deprecated')),
  updated_by      TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at      TEXT
);

CREATE TABLE settings (
  id          INTEGER PRIMARY KEY,
  key         TEXT NOT NULL UNIQUE,
  label       TEXT NOT NULL,
  value       TEXT NOT NULL,
  note        TEXT,
  updated_by  TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at  TEXT
);

-- person_id is NULL on a blank install (the seeded questions exist before the person does).
CREATE TABLE qa (
  id              INTEGER PRIMARY KEY,
  person_id       INTEGER REFERENCES people(id),
  question        TEXT NOT NULL,
  category        TEXT CHECK (category IN ('About you','Behavioral','Strengths','Motivation','Situational','Logistics','Other')),
  common_wordings TEXT,            -- other ways the question gets asked
  answer          TEXT,            -- NULL until answered
  status          TEXT NOT NULL DEFAULT 'Needs answer'
                  CHECK (status IN ('Needs answer','Needs review','Verified','Deprecated')),
  sort            INTEGER,         -- seed order 1-10; NULL for added questions
  seeded          INTEGER NOT NULL DEFAULT 0 CHECK (seeded IN (0,1)),
  notes           TEXT,
  updated_by      TEXT CHECK (updated_by IN ('user','ai','app')),
  updated_at      TEXT,
  UNIQUE (person_id, question)
);

-- Append-only. Written only by the *_after_ins / *_after_upd triggers.
CREATE TABLE audit (
  id          INTEGER PRIMARY KEY,
  at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  table_name  TEXT NOT NULL,
  row_id      INTEGER NOT NULL,
  op          TEXT NOT NULL CHECK (op IN ('insert','update')),
  old_json    TEXT,
  new_json    TEXT NOT NULL,
  actor       TEXT NOT NULL CHECK (actor IN ('user','ai','app'))
);


CREATE VIEW experience AS
  SELECT p.*, e.name AS employer
  FROM positions p JOIN employers e ON e.id = p.employer_id
  WHERE p.status <> 'Deprecated'
  ORDER BY p.sort_order IS NULL, p.sort_order, p.start_date DESC;

CREATE VIEW resume_lines AS
  SELECT b.id, b.item_id, b.track, b.angle, b.length, b.wording, b.source, b.status,
         i.kind, i.title, i.detail, i.person_id, i.position_id
  FROM bullet_variants b JOIN items i ON i.id = b.item_id;

-- Who touched each row last (rows clear updated_by after every write; the audit keeps it).
CREATE VIEW last_change AS
  SELECT a.table_name, a.row_id, a.actor, a.at
  FROM audit a
  WHERE a.id = (SELECT max(b.id) FROM audit b WHERE b.table_name = a.table_name AND b.row_id = a.row_id);
CREATE INDEX audit_row ON audit(table_name, row_id, id);

-- Printable lines only, best first within each job and track: Verified, then Short < Long, then id.
-- Story lines are paragraphs for cover letters and interviews, never resume bullets.
CREATE VIEW resume_lines_ranked AS
  SELECT b.id, b.track, b.wording, b.length, b.angle, b.status, b.item_id,
         i.kind, i.title, i.detail, i.person_id, i.position_id,
         row_number() OVER (PARTITION BY b.track, i.position_id
           ORDER BY b.status = 'Verified' DESC,
                    CASE b.length WHEN 'Short' THEN 1 WHEN 'Long' THEN 2 ELSE 3 END, b.id) AS line_rank
  FROM bullet_variants b JOIN items i ON i.id = b.item_id
  WHERE b.status <> 'Deprecated' AND i.status <> 'Deprecated' AND b.length IS NOT 'Story';

-- The whole resume for one track as one JSON document. json() keeps nested arrays as JSON, not strings.
CREATE VIEW resume_json AS
  SELECT t.name AS track, json_object(
    'track', t.name,
    'person', json_object('name', p.name, 'full_name', p.full_name, 'headline', p.headline, 'location', p.location,
                          'email', p.email, 'phone', p.phone, 'linkedin', p.linkedin, 'summary', p.summary,
                          'work_authorization', p.work_authorization),
    'links', json((SELECT json_group_array(json_object('id', id, 'kind', kind, 'label', label, 'url', url))
                   FROM (SELECT * FROM links WHERE person_id = p.id AND status = 'Active' ORDER BY sort, id))),
    'employers', json((SELECT json_group_array(json_object(
                    'id', m.id, 'name', m.name, 'location', m.location,
                    'positions', json((SELECT json_group_array(json_object(
                       'id', e.id, 'title', e.title, 'department', e.department,
                       'start_date', e.start_date, 'end_date', e.end_date,
                       'lines', json((SELECT json_group_array(json_object(
                                        'id', r.id, 'wording', r.wording, 'length', r.length, 'angle', r.angle, 'status', r.status,
                                        'item', json_object('id', r.item_id, 'kind', r.kind, 'title', r.title, 'detail', r.detail,
                                                            'metrics', json((SELECT json_group_array(json_object('id', id, 'label', label, 'value', value, 'unit', unit, 'as_of', as_of)) FROM (SELECT * FROM item_metrics WHERE item_id = r.item_id AND status <> 'Deprecated' ORDER BY sort, id))))))
                                      FROM (SELECT * FROM resume_lines_ranked
                                            WHERE position_id = e.id AND track = t.name ORDER BY line_rank) r)),
                       'items_without_lines', json((SELECT json_group_array(json_object(
                                        'id', a.id, 'kind', a.kind, 'parent_item_id', a.parent_item_id, 'title', a.title,
                                        'detail', a.detail, 'outputs', a.outputs, 'status', a.status,
                                        'metrics', json((SELECT json_group_array(json_object('id', id, 'label', label, 'value', value, 'unit', unit, 'as_of', as_of)) FROM (SELECT * FROM item_metrics WHERE item_id = a.id AND status <> 'Deprecated' ORDER BY sort, id)))))
                                      FROM (SELECT * FROM items a
                                            WHERE a.position_id = e.id AND a.status <> 'Deprecated'
                                              AND NOT EXISTS (SELECT 1 FROM resume_lines_ranked r
                                                              WHERE r.item_id = a.id AND r.track = t.name)
                                            ORDER BY a.id) a))))
                     FROM (SELECT * FROM positions WHERE employer_id = m.id AND status <> 'Deprecated'
                           ORDER BY sort_order IS NULL, sort_order, start_date DESC) e))))
                  FROM (SELECT * FROM employers m WHERE person_id = p.id AND status <> 'Deprecated'
                          AND EXISTS (SELECT 1 FROM positions x WHERE x.employer_id = m.id AND x.status <> 'Deprecated')
                        ORDER BY (SELECT min(coalesce(x.sort_order, 1000000)) FROM positions x WHERE x.employer_id = m.id AND x.status <> 'Deprecated'),
                              (SELECT max(coalesce(x.end_date, '9999')) FROM positions x WHERE x.employer_id = m.id AND x.status <> 'Deprecated') DESC, m.id) m)),
    'skills', json((SELECT json_group_array(json_object('id', id, 'name', name, 'category', category))
                    FROM (SELECT * FROM skills WHERE person_id = p.id AND status = 'Verified' ORDER BY category, name))),
    'education', json((SELECT json_group_array(json_object(
                         'id', id, 'kind', kind, 'name', name, 'institution', institution, 'location', location, 'year', year,
                         'start_date', start_date, 'end_date', end_date, 'expires', expires, 'credential_url', credential_url))
                       FROM (SELECT * FROM education WHERE person_id = p.id AND status <> 'Deprecated' ORDER BY year DESC, id))),
    'items', json((SELECT json_group_array(json_object(
                     'id', i.id, 'kind', i.kind, 'position_id', i.position_id, 'parent_item_id', i.parent_item_id,
                     'title', i.title, 'detail', i.detail, 'outputs', i.outputs, 'organization', i.organization,
                     'from_whom', i.from_whom, 'start_date', i.start_date, 'end_date', i.end_date,
                     'metrics', json((SELECT json_group_array(json_object('id', id, 'label', label, 'value', value, 'unit', unit, 'as_of', as_of)) FROM (SELECT * FROM item_metrics WHERE item_id = i.id AND status <> 'Deprecated' ORDER BY sort, id)))))
                   FROM (SELECT * FROM items i WHERE person_id = p.id AND status <> 'Deprecated' AND kind NOT IN ('Responsibility','Achievement')
                         ORDER BY coalesce(end_date, start_date) DESC, id) i)),
    'warnings', json((SELECT json_group_array(w) FROM (
        SELECT n || CASE n WHEN 1 THEN ' printed row is' ELSE ' printed rows are' END
                  || ' Needs review (employers, positions, lines, education or items): check them with the person before sending.' AS w
        FROM (SELECT (SELECT count(*) FROM employers m WHERE m.person_id = p.id AND m.status = 'Needs review'
                        AND EXISTS (SELECT 1 FROM positions x WHERE x.employer_id = m.id AND x.status <> 'Deprecated'))
                   + (SELECT count(*) FROM positions WHERE person_id = p.id AND status = 'Needs review')
                   + (SELECT count(*) FROM resume_lines_ranked r WHERE r.track = t.name AND r.status = 'Needs review'
                        AND r.position_id IN (SELECT id FROM positions WHERE person_id = p.id AND status <> 'Deprecated'))
                   + (SELECT count(*) FROM education WHERE person_id = p.id AND status = 'Needs review')
                   + (SELECT count(*) FROM items WHERE person_id = p.id AND status = 'Needs review' AND kind NOT IN ('Responsibility','Achievement')) AS n)
        WHERE n > 0
        UNION ALL
        SELECT n || CASE n WHEN 1 THEN ' skill is' ELSE ' skills are' END || ' hidden because not Verified.'
        FROM (SELECT count(*) AS n FROM skills WHERE person_id = p.id AND status = 'Needs review')
        WHERE n > 0)))
  ) AS resume
  FROM tracks t JOIN people p ON p.status = 'Active';

-- Everything known about the Active person, any status but Deprecated: what the Q&A and fill prompts start from.
CREATE VIEW profile_json AS
  SELECT json_object(
    'person', json_object('id', p.id, 'name', p.name, 'full_name', p.full_name, 'headline', p.headline,
                          'location', p.location, 'email', p.email, 'phone', p.phone, 'linkedin', p.linkedin,
                          'work_authorization', p.work_authorization, 'summary', p.summary),
    'employers', json((SELECT json_group_array(json_object(
                         'id', id, 'name', name, 'location', location, 'website', website, 'notes', notes, 'status', status))
                       FROM (SELECT * FROM employers WHERE person_id = p.id AND status <> 'Deprecated' ORDER BY name))),
    'positions', json((SELECT json_group_array(json_object(
                         'id', id, 'employer_id', employer_id, 'employer', employer, 'title', title, 'department', department,
                         'start_date', start_date, 'end_date', end_date, 'notes', notes, 'status', status))
                       FROM (SELECT * FROM experience WHERE person_id = p.id))),
    'items', json((SELECT json_group_array(json_object(
                     'id', i.id, 'kind', i.kind, 'position_id', i.position_id, 'employer', i.employer, 'job_title', i.job_title,
                     'parent_item_id', i.parent_item_id, 'title', i.title, 'detail', i.detail, 'outputs', i.outputs,
                     'organization', i.organization, 'from_whom', i.from_whom, 'start_date', i.start_date, 'end_date', i.end_date,
                     'source', i.source, 'notes', i.notes, 'status', i.status,
                     'metrics', json((SELECT json_group_array(json_object('id', id, 'label', label, 'value', value, 'unit', unit, 'as_of', as_of, 'status', status)) FROM (SELECT * FROM item_metrics WHERE item_id = i.id AND status <> 'Deprecated' ORDER BY sort, id))),
                     'original_ids', json((SELECT json_group_array(original_id) FROM item_originals
                                           WHERE item_id = i.id AND status = 'Active'))))
                   FROM (SELECT i.*, x.employer, x.title AS job_title
                         FROM items i LEFT JOIN experience x ON x.id = i.position_id
                         WHERE i.person_id = p.id AND i.status <> 'Deprecated'
                         ORDER BY i.position_id IS NULL, i.position_id, i.parent_item_id IS NOT NULL, i.id) i)),
    'skills', json((SELECT json_group_array(json_object('id', id, 'name', name, 'category', category, 'status', status))
                    FROM (SELECT * FROM skills WHERE person_id = p.id AND status <> 'Deprecated' ORDER BY category, name))),
    'education', json((SELECT json_group_array(json_object(
                         'id', id, 'kind', kind, 'name', name, 'institution', institution, 'year', year,
                         'start_date', start_date, 'end_date', end_date, 'status', status))
                       FROM (SELECT * FROM education WHERE person_id = p.id AND status <> 'Deprecated' ORDER BY year DESC, id)))
  ) AS profile
  FROM people p WHERE p.status = 'Active';

CREATE TRIGGER people_no_delete BEFORE DELETE ON people
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER people_need_by_ins BEFORE INSERT ON people WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER people_need_by_upd BEFORE UPDATE ON people WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER people_after_ins AFTER INSERT ON people
  BEGIN
    UPDATE people SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'people', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'name', x.name, 'full_name', x.full_name, 'other_names', x.other_names, 'headline', x.headline, 'location', x.location, 'phone', x.phone, 'email', x.email, 'linkedin', x.linkedin, 'summary', x.summary, 'work_authorization', x.work_authorization, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM people x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER people_after_upd AFTER UPDATE ON people WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE people SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'people', NEW.rowid, 'update', json_object('id', OLD.id, 'name', OLD.name, 'full_name', OLD.full_name, 'other_names', OLD.other_names, 'headline', OLD.headline, 'location', OLD.location, 'phone', OLD.phone, 'email', OLD.email, 'linkedin', OLD.linkedin, 'summary', OLD.summary, 'work_authorization', OLD.work_authorization, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'name', x.name, 'full_name', x.full_name, 'other_names', x.other_names, 'headline', x.headline, 'location', x.location, 'phone', x.phone, 'email', x.email, 'linkedin', x.linkedin, 'summary', x.summary, 'work_authorization', x.work_authorization, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM people x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER links_no_delete BEFORE DELETE ON links
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER links_need_by_ins BEFORE INSERT ON links WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER links_need_by_upd BEFORE UPDATE ON links WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER links_after_ins AFTER INSERT ON links
  BEGIN
    UPDATE links SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'links', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'person_id', x.person_id, 'kind', x.kind, 'label', x.label, 'url', x.url, 'sort', x.sort, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM links x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER links_after_upd AFTER UPDATE ON links WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE links SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'links', NEW.rowid, 'update', json_object('id', OLD.id, 'person_id', OLD.person_id, 'kind', OLD.kind, 'label', OLD.label, 'url', OLD.url, 'sort', OLD.sort, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'person_id', x.person_id, 'kind', x.kind, 'label', x.label, 'url', x.url, 'sort', x.sort, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM links x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER images_no_delete BEFORE DELETE ON images
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER images_need_by_ins BEFORE INSERT ON images WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER images_need_by_upd BEFORE UPDATE ON images WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER images_after_ins AFTER INSERT ON images
  BEGIN
    UPDATE images SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'images', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'person_id', x.person_id, 'caption', x.caption, 'mime', x.mime, 'bytes', x.bytes, 'sha256', x.sha256, 'source', x.source, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM images x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER images_after_upd AFTER UPDATE ON images WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE images SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'images', NEW.rowid, 'update', json_object('id', OLD.id, 'person_id', OLD.person_id, 'caption', OLD.caption, 'mime', OLD.mime, 'bytes', OLD.bytes, 'sha256', OLD.sha256, 'source', OLD.source, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'person_id', x.person_id, 'caption', x.caption, 'mime', x.mime, 'bytes', x.bytes, 'sha256', x.sha256, 'source', x.source, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM images x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER employers_no_delete BEFORE DELETE ON employers
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER employers_need_by_ins BEFORE INSERT ON employers WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER employers_need_by_upd BEFORE UPDATE ON employers WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER employers_after_ins AFTER INSERT ON employers
  BEGIN
    UPDATE employers SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'employers', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'person_id', x.person_id, 'name', x.name, 'location', x.location, 'website', x.website, 'notes', x.notes, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM employers x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER employers_after_upd AFTER UPDATE ON employers WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE employers SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'employers', NEW.rowid, 'update', json_object('id', OLD.id, 'person_id', OLD.person_id, 'name', OLD.name, 'location', OLD.location, 'website', OLD.website, 'notes', OLD.notes, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'person_id', x.person_id, 'name', x.name, 'location', x.location, 'website', x.website, 'notes', x.notes, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM employers x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER positions_no_delete BEFORE DELETE ON positions
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER positions_need_by_ins BEFORE INSERT ON positions WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER positions_need_by_upd BEFORE UPDATE ON positions WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER positions_after_ins AFTER INSERT ON positions
  BEGIN
    UPDATE positions SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'positions', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'person_id', x.person_id, 'employer_id', x.employer_id, 'title', x.title, 'department', x.department, 'start_date', x.start_date, 'end_date', x.end_date, 'sort_order', x.sort_order, 'notes', x.notes, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM positions x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER positions_after_upd AFTER UPDATE ON positions WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE positions SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'positions', NEW.rowid, 'update', json_object('id', OLD.id, 'person_id', OLD.person_id, 'employer_id', OLD.employer_id, 'title', OLD.title, 'department', OLD.department, 'start_date', OLD.start_date, 'end_date', OLD.end_date, 'sort_order', OLD.sort_order, 'notes', OLD.notes, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'person_id', x.person_id, 'employer_id', x.employer_id, 'title', x.title, 'department', x.department, 'start_date', x.start_date, 'end_date', x.end_date, 'sort_order', x.sort_order, 'notes', x.notes, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM positions x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER originals_no_delete BEFORE DELETE ON originals
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER originals_need_by_ins BEFORE INSERT ON originals WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER originals_need_by_upd BEFORE UPDATE ON originals WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER originals_after_ins AFTER INSERT ON originals
  BEGIN
    UPDATE originals SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'originals', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'person_id', x.person_id, 'kind', x.kind, 'path', x.path, 'title', x.title, 'doc_date', x.doc_date, 'weight', x.weight, 'position_id', x.position_id, 'sha256', x.sha256, 'bytes', x.bytes, 'extracted', x.extracted, 'notes', x.notes, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM originals x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER originals_after_upd AFTER UPDATE ON originals WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE originals SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'originals', NEW.rowid, 'update', json_object('id', OLD.id, 'person_id', OLD.person_id, 'kind', OLD.kind, 'path', OLD.path, 'title', OLD.title, 'doc_date', OLD.doc_date, 'weight', OLD.weight, 'position_id', OLD.position_id, 'sha256', OLD.sha256, 'bytes', OLD.bytes, 'extracted', OLD.extracted, 'notes', OLD.notes, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'person_id', x.person_id, 'kind', x.kind, 'path', x.path, 'title', x.title, 'doc_date', x.doc_date, 'weight', x.weight, 'position_id', x.position_id, 'sha256', x.sha256, 'bytes', x.bytes, 'extracted', x.extracted, 'notes', x.notes, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM originals x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER items_no_delete BEFORE DELETE ON items
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER items_need_by_ins BEFORE INSERT ON items WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER items_need_by_upd BEFORE UPDATE ON items WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER items_after_ins AFTER INSERT ON items
  BEGIN
    UPDATE items SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'items', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'person_id', x.person_id, 'position_id', x.position_id, 'parent_item_id', x.parent_item_id, 'kind', x.kind, 'title', x.title, 'detail', x.detail, 'outputs', x.outputs, 'organization', x.organization, 'from_whom', x.from_whom, 'start_date', x.start_date, 'end_date', x.end_date, 'source', x.source, 'notes', x.notes, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM items x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER items_after_upd AFTER UPDATE ON items WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE items SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'items', NEW.rowid, 'update', json_object('id', OLD.id, 'person_id', OLD.person_id, 'position_id', OLD.position_id, 'parent_item_id', OLD.parent_item_id, 'kind', OLD.kind, 'title', OLD.title, 'detail', OLD.detail, 'outputs', OLD.outputs, 'organization', OLD.organization, 'from_whom', OLD.from_whom, 'start_date', OLD.start_date, 'end_date', OLD.end_date, 'source', OLD.source, 'notes', OLD.notes, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'person_id', x.person_id, 'position_id', x.position_id, 'parent_item_id', x.parent_item_id, 'kind', x.kind, 'title', x.title, 'detail', x.detail, 'outputs', x.outputs, 'organization', x.organization, 'from_whom', x.from_whom, 'start_date', x.start_date, 'end_date', x.end_date, 'source', x.source, 'notes', x.notes, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM items x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER item_metrics_no_delete BEFORE DELETE ON item_metrics
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER item_metrics_need_by_ins BEFORE INSERT ON item_metrics WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER item_metrics_need_by_upd BEFORE UPDATE ON item_metrics WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER item_metrics_after_ins AFTER INSERT ON item_metrics
  BEGIN
    UPDATE item_metrics SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'item_metrics', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'item_id', x.item_id, 'label', x.label, 'value', x.value, 'unit', x.unit, 'as_of', x.as_of, 'sort', x.sort, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM item_metrics x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER item_metrics_after_upd AFTER UPDATE ON item_metrics WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE item_metrics SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'item_metrics', NEW.rowid, 'update', json_object('id', OLD.id, 'item_id', OLD.item_id, 'label', OLD.label, 'value', OLD.value, 'unit', OLD.unit, 'as_of', OLD.as_of, 'sort', OLD.sort, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'item_id', x.item_id, 'label', x.label, 'value', x.value, 'unit', x.unit, 'as_of', x.as_of, 'sort', x.sort, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM item_metrics x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER item_originals_no_delete BEFORE DELETE ON item_originals
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER item_originals_need_by_ins BEFORE INSERT ON item_originals WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER item_originals_need_by_upd BEFORE UPDATE ON item_originals WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER item_originals_after_ins AFTER INSERT ON item_originals
  BEGIN
    UPDATE item_originals SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'item_originals', NEW.rowid, 'insert', NULL, json_set(json_object('item_id', x.item_id, 'original_id', x.original_id, 'note', x.note, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM item_originals x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER item_originals_after_upd AFTER UPDATE ON item_originals WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE item_originals SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'item_originals', NEW.rowid, 'update', json_object('item_id', OLD.item_id, 'original_id', OLD.original_id, 'note', OLD.note, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('item_id', x.item_id, 'original_id', x.original_id, 'note', x.note, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM item_originals x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER tracks_no_delete BEFORE DELETE ON tracks
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER tracks_need_by_ins BEFORE INSERT ON tracks WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER tracks_need_by_upd BEFORE UPDATE ON tracks WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER tracks_after_ins AFTER INSERT ON tracks
  BEGIN
    UPDATE tracks SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'tracks', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'name', x.name, 'color', x.color, 'sort', x.sort, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM tracks x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER tracks_after_upd AFTER UPDATE ON tracks WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE tracks SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'tracks', NEW.rowid, 'update', json_object('id', OLD.id, 'name', OLD.name, 'color', OLD.color, 'sort', OLD.sort, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'name', x.name, 'color', x.color, 'sort', x.sort, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM tracks x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER bullet_variants_no_delete BEFORE DELETE ON bullet_variants
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER bullet_variants_need_by_ins BEFORE INSERT ON bullet_variants WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER bullet_variants_need_by_upd BEFORE UPDATE ON bullet_variants WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER bullet_variants_after_ins AFTER INSERT ON bullet_variants
  BEGIN
    UPDATE bullet_variants SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'bullet_variants', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'item_id', x.item_id, 'wording', x.wording, 'angle', x.angle, 'length', x.length, 'track', x.track, 'source', x.source, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM bullet_variants x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER bullet_variants_after_upd AFTER UPDATE ON bullet_variants WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE bullet_variants SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'bullet_variants', NEW.rowid, 'update', json_object('id', OLD.id, 'item_id', OLD.item_id, 'wording', OLD.wording, 'angle', OLD.angle, 'length', OLD.length, 'track', OLD.track, 'source', OLD.source, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'item_id', x.item_id, 'wording', x.wording, 'angle', x.angle, 'length', x.length, 'track', x.track, 'source', x.source, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM bullet_variants x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER skills_no_delete BEFORE DELETE ON skills
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER skills_need_by_ins BEFORE INSERT ON skills WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER skills_need_by_upd BEFORE UPDATE ON skills WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER skills_after_ins AFTER INSERT ON skills
  BEGIN
    UPDATE skills SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'skills', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'person_id', x.person_id, 'name', x.name, 'category', x.category, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM skills x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER skills_after_upd AFTER UPDATE ON skills WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE skills SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'skills', NEW.rowid, 'update', json_object('id', OLD.id, 'person_id', OLD.person_id, 'name', OLD.name, 'category', OLD.category, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'person_id', x.person_id, 'name', x.name, 'category', x.category, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM skills x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER skill_links_no_delete BEFORE DELETE ON skill_links
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER skill_links_need_by_ins BEFORE INSERT ON skill_links WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER skill_links_need_by_upd BEFORE UPDATE ON skill_links WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER skill_links_after_ins AFTER INSERT ON skill_links
  BEGIN
    UPDATE skill_links SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'skill_links', NEW.rowid, 'insert', NULL, json_set(json_object('skill_id', x.skill_id, 'item_type', x.item_type, 'item_id', x.item_id, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM skill_links x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER skill_links_after_upd AFTER UPDATE ON skill_links WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE skill_links SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'skill_links', NEW.rowid, 'update', json_object('skill_id', OLD.skill_id, 'item_type', OLD.item_type, 'item_id', OLD.item_id, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('skill_id', x.skill_id, 'item_type', x.item_type, 'item_id', x.item_id, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM skill_links x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER education_no_delete BEFORE DELETE ON education
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER education_need_by_ins BEFORE INSERT ON education WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER education_need_by_upd BEFORE UPDATE ON education WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER education_after_ins AFTER INSERT ON education
  BEGIN
    UPDATE education SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'education', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'person_id', x.person_id, 'kind', x.kind, 'name', x.name, 'institution', x.institution, 'location', x.location, 'year', x.year, 'start_date', x.start_date, 'end_date', x.end_date, 'expires', x.expires, 'credential_url', x.credential_url, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM education x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER education_after_upd AFTER UPDATE ON education WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE education SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'education', NEW.rowid, 'update', json_object('id', OLD.id, 'person_id', OLD.person_id, 'kind', OLD.kind, 'name', OLD.name, 'institution', OLD.institution, 'location', OLD.location, 'year', OLD.year, 'start_date', OLD.start_date, 'end_date', OLD.end_date, 'expires', OLD.expires, 'credential_url', OLD.credential_url, 'status', OLD.status, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'person_id', x.person_id, 'kind', x.kind, 'name', x.name, 'institution', x.institution, 'location', x.location, 'year', x.year, 'start_date', x.start_date, 'end_date', x.end_date, 'expires', x.expires, 'credential_url', x.credential_url, 'status', x.status, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM education x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER settings_no_delete BEFORE DELETE ON settings
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER settings_need_by_ins BEFORE INSERT ON settings WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER settings_need_by_upd BEFORE UPDATE ON settings WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER settings_after_ins AFTER INSERT ON settings
  BEGIN
    UPDATE settings SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'settings', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'key', x.key, 'label', x.label, 'value', x.value, 'note', x.note, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM settings x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER settings_after_upd AFTER UPDATE ON settings WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE settings SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'settings', NEW.rowid, 'update', json_object('id', OLD.id, 'key', OLD.key, 'label', OLD.label, 'value', OLD.value, 'note', OLD.note, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'key', x.key, 'label', x.label, 'value', x.value, 'note', x.note, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM settings x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER qa_no_delete BEFORE DELETE ON qa
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER qa_need_by_ins BEFORE INSERT ON qa WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER qa_need_by_upd BEFORE UPDATE ON qa WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER qa_after_ins AFTER INSERT ON qa
  BEGIN
    UPDATE qa SET updated_at = coalesce(NEW.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'qa', NEW.rowid, 'insert', NULL, json_set(json_object('id', x.id, 'person_id', x.person_id, 'question', x.question, 'category', x.category, 'common_wordings', x.common_wordings, 'answer', x.answer, 'status', x.status, 'sort', x.sort, 'seeded', x.seeded, 'notes', x.notes, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM qa x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER qa_after_upd AFTER UPDATE ON qa WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE qa SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT 'qa', NEW.rowid, 'update', json_object('id', OLD.id, 'person_id', OLD.person_id, 'question', OLD.question, 'category', OLD.category, 'common_wordings', OLD.common_wordings, 'answer', OLD.answer, 'status', OLD.status, 'sort', OLD.sort, 'seeded', OLD.seeded, 'notes', OLD.notes, 'updated_by', OLD.updated_by, 'updated_at', OLD.updated_at), json_set(json_object('id', x.id, 'person_id', x.person_id, 'question', x.question, 'category', x.category, 'common_wordings', x.common_wordings, 'answer', x.answer, 'status', x.status, 'sort', x.sort, 'seeded', x.seeded, 'notes', x.notes, 'updated_by', x.updated_by, 'updated_at', x.updated_at), '$.updated_by', NEW.updated_by), NEW.updated_by
      FROM qa x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit
  BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;

-- One person per install.
CREATE TRIGGER people_one_ins BEFORE INSERT ON people
  WHEN NEW.status = 'Active' AND EXISTS (SELECT 1 FROM people WHERE status = 'Active')
  BEGIN SELECT RAISE(ABORT, 'One person per install'); END;
CREATE TRIGGER people_one_upd BEFORE UPDATE OF status ON people
  WHEN NEW.status = 'Active' AND EXISTS (SELECT 1 FROM people WHERE status = 'Active' AND id <> NEW.id)
  BEGIN SELECT RAISE(ABORT, 'One person per install'); END;
-- The seeded questions exist before the person does; the first person claims them.
CREATE TRIGGER people_claims_qa AFTER INSERT ON people
  BEGIN UPDATE qa SET person_id = NEW.id, updated_by = 'app' WHERE person_id IS NULL; END;

CREATE TRIGGER people_claims_originals AFTER INSERT ON people
  BEGIN UPDATE originals SET person_id = NEW.id, updated_by = 'app' WHERE person_id IS NULL; END;

-- Typed text must not be blank; dates are YYYY or YYYY-MM (an open end date is NULL, shown as Present).
CREATE TRIGGER people_name_text_ins BEFORE INSERT ON people WHEN length(trim(coalesce(NEW.name, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'Name cannot be empty'); END;
CREATE TRIGGER people_name_text_upd BEFORE UPDATE OF name ON people WHEN length(trim(coalesce(NEW.name, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'Name cannot be empty'); END;
CREATE TRIGGER positions_title_text_ins BEFORE INSERT ON positions WHEN length(trim(coalesce(NEW.title, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'Job title cannot be empty'); END;
CREATE TRIGGER positions_title_text_upd BEFORE UPDATE OF title ON positions WHEN length(trim(coalesce(NEW.title, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'Job title cannot be empty'); END;
CREATE TRIGGER employers_name_text_ins BEFORE INSERT ON employers WHEN length(trim(coalesce(NEW.name, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'Employer cannot be empty'); END;
CREATE TRIGGER employers_name_text_upd BEFORE UPDATE OF name ON employers WHEN length(trim(coalesce(NEW.name, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'Employer cannot be empty'); END;
CREATE TRIGGER items_text_ins BEFORE INSERT ON items
  WHEN length(trim(coalesce(NEW.title, ''))) = 0 AND length(trim(coalesce(NEW.detail, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'Give the item a title or say what was done'); END;
CREATE TRIGGER items_text_upd BEFORE UPDATE OF title, detail ON items
  WHEN length(trim(coalesce(NEW.title, ''))) = 0 AND length(trim(coalesce(NEW.detail, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'Give the item a title or say what was done'); END;
CREATE TRIGGER item_metrics_value_text_ins BEFORE INSERT ON item_metrics WHEN length(trim(coalesce(NEW.value, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'The metric value cannot be empty'); END;
CREATE TRIGGER item_metrics_value_text_upd BEFORE UPDATE OF value ON item_metrics WHEN length(trim(coalesce(NEW.value, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'The metric value cannot be empty'); END;
CREATE TRIGGER bullet_variants_wording_text_ins BEFORE INSERT ON bullet_variants WHEN length(trim(coalesce(NEW.wording, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'The wording cannot be empty'); END;
CREATE TRIGGER bullet_variants_wording_text_upd BEFORE UPDATE OF wording ON bullet_variants WHEN length(trim(coalesce(NEW.wording, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'The wording cannot be empty'); END;
CREATE TRIGGER qa_question_text_ins BEFORE INSERT ON qa WHEN length(trim(coalesce(NEW.question, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'The question cannot be empty'); END;
CREATE TRIGGER qa_question_text_upd BEFORE UPDATE OF question ON qa WHEN length(trim(coalesce(NEW.question, ''))) = 0
  BEGIN SELECT RAISE(ABORT, 'The question cannot be empty'); END;
CREATE TRIGGER positions_start_date_ins BEFORE INSERT ON positions
  WHEN NOT (NEW.start_date IS NULL OR NEW.start_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.start_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.start_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;
CREATE TRIGGER positions_start_date_upd BEFORE UPDATE OF start_date ON positions
  WHEN NOT (NEW.start_date IS NULL OR NEW.start_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.start_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.start_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;
CREATE TRIGGER positions_end_date_ins BEFORE INSERT ON positions
  WHEN NOT (NEW.end_date IS NULL OR NEW.end_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.end_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.end_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;
CREATE TRIGGER positions_end_date_upd BEFORE UPDATE OF end_date ON positions
  WHEN NOT (NEW.end_date IS NULL OR NEW.end_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.end_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.end_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;
CREATE TRIGGER education_start_date_ins BEFORE INSERT ON education
  WHEN NOT (NEW.start_date IS NULL OR NEW.start_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.start_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.start_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;
CREATE TRIGGER education_start_date_upd BEFORE UPDATE OF start_date ON education
  WHEN NOT (NEW.start_date IS NULL OR NEW.start_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.start_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.start_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;
CREATE TRIGGER education_end_date_ins BEFORE INSERT ON education
  WHEN NOT (NEW.end_date IS NULL OR NEW.end_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.end_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.end_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;
CREATE TRIGGER education_end_date_upd BEFORE UPDATE OF end_date ON education
  WHEN NOT (NEW.end_date IS NULL OR NEW.end_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.end_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.end_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;
CREATE TRIGGER items_start_date_ins BEFORE INSERT ON items
  WHEN NOT (NEW.start_date IS NULL OR NEW.start_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.start_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.start_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;
CREATE TRIGGER items_start_date_upd BEFORE UPDATE OF start_date ON items
  WHEN NOT (NEW.start_date IS NULL OR NEW.start_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.start_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.start_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;
CREATE TRIGGER items_end_date_ins BEFORE INSERT ON items
  WHEN NOT (NEW.end_date IS NULL OR NEW.end_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.end_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.end_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;
CREATE TRIGGER items_end_date_upd BEFORE UPDATE OF end_date ON items
  WHEN NOT (NEW.end_date IS NULL OR NEW.end_date GLOB '[0-9][0-9][0-9][0-9]' OR (NEW.end_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]' AND substr(NEW.end_date, 6, 2) BETWEEN '01' AND '12'))
  BEGIN SELECT RAISE(ABORT, 'Dates are YYYY or YYYY-MM, like 2021 or 2021-06'); END;

-- No loops: an item cannot sit inside itself, directly or through its parents.
CREATE TRIGGER items_parent_loop_ins BEFORE INSERT ON items WHEN NEW.parent_item_id IS NOT NULL AND NEW.parent_item_id = NEW.id
  BEGIN SELECT RAISE(ABORT, 'An item cannot sit inside itself'); END;
CREATE TRIGGER items_parent_loop_upd BEFORE UPDATE OF parent_item_id ON items WHEN NEW.parent_item_id IS NOT NULL
  AND EXISTS (WITH RECURSIVE up(id) AS (SELECT NEW.parent_item_id
                                          UNION SELECT i.parent_item_id FROM items i JOIN up ON i.id = up.id
                                          WHERE i.parent_item_id IS NOT NULL)
              SELECT 1 FROM up WHERE id = NEW.id)
  BEGIN SELECT RAISE(ABORT, 'An item cannot sit inside itself'); END;

-- A rename carries the audit actor to the rewritten lines (the guard needs updated_by).
CREATE TRIGGER tracks_rename AFTER UPDATE OF name ON tracks WHEN OLD.name IS NOT NEW.name
  BEGIN UPDATE bullet_variants SET track = NEW.name, updated_by = NEW.updated_by WHERE track = OLD.name; END;
CREATE TRIGGER bullet_variants_track_ins BEFORE INSERT ON bullet_variants
  WHEN NOT EXISTS (SELECT 1 FROM tracks WHERE name = NEW.track)
  BEGIN SELECT RAISE(ABORT, 'Unknown track: add it under Settings first'); END;
CREATE TRIGGER bullet_variants_track_upd BEFORE UPDATE OF track ON bullet_variants
  WHEN NOT EXISTS (SELECT 1 FROM tracks WHERE name = NEW.track)
  BEGIN SELECT RAISE(ABORT, 'Unknown track: add it under Settings first'); END;

CREATE TRIGGER settings_years_order BEFORE UPDATE OF value ON settings
  WHEN (NEW.key = 'recent_years' AND CAST(NEW.value AS INTEGER) >= (SELECT CAST(value AS INTEGER) FROM settings WHERE key = 'older_years'))
    OR (NEW.key = 'older_years' AND CAST(NEW.value AS INTEGER) <= (SELECT CAST(value AS INTEGER) FROM settings WHERE key = 'recent_years'))
  BEGIN SELECT RAISE(ABORT, 'The "Recent" years must be fewer than the older cutoff'); END;

-- Full-text index of the wording a job description is matched against (store.search ranks it with bm25).
-- The *_search_* triggers keep it current. A retired row is DELETEd from the index: the index is derived data,
-- so the no-delete rule (which protects records) does not apply to it.
CREATE VIRTUAL TABLE search_index USING fts5(source_table UNINDEXED, source_id UNINDEXED, text, tokenize='porter unicode61');

CREATE TRIGGER items_search_ins AFTER INSERT ON items WHEN NEW.status <> 'Deprecated'
  BEGIN INSERT INTO search_index (source_table, source_id, text) VALUES ('items', NEW.id, coalesce(NEW.title, '') || ' ' || coalesce(NEW.detail, '') || ' ' || coalesce(NEW.outputs, '')); END;
CREATE TRIGGER items_search_upd AFTER UPDATE OF title, detail, outputs, status ON items
  BEGIN
    DELETE FROM search_index WHERE source_table = 'items' AND source_id = OLD.id;
    INSERT INTO search_index (source_table, source_id, text) SELECT 'items', NEW.id, coalesce(NEW.title, '') || ' ' || coalesce(NEW.detail, '') || ' ' || coalesce(NEW.outputs, '') WHERE NEW.status <> 'Deprecated';
  END;
CREATE TRIGGER bullet_variants_search_ins AFTER INSERT ON bullet_variants WHEN NEW.status <> 'Deprecated'
  BEGIN INSERT INTO search_index (source_table, source_id, text) VALUES ('bullet_variants', NEW.id, coalesce(NEW.wording, '')); END;
CREATE TRIGGER bullet_variants_search_upd AFTER UPDATE OF wording, status ON bullet_variants
  BEGIN
    DELETE FROM search_index WHERE source_table = 'bullet_variants' AND source_id = OLD.id;
    INSERT INTO search_index (source_table, source_id, text) SELECT 'bullet_variants', NEW.id, coalesce(NEW.wording, '') WHERE NEW.status <> 'Deprecated';
  END;
CREATE TRIGGER skills_search_ins AFTER INSERT ON skills WHEN NEW.status <> 'Deprecated'
  BEGIN INSERT INTO search_index (source_table, source_id, text) VALUES ('skills', NEW.id, coalesce(NEW.name, '')); END;
CREATE TRIGGER skills_search_upd AFTER UPDATE OF name, status ON skills
  BEGIN
    DELETE FROM search_index WHERE source_table = 'skills' AND source_id = OLD.id;
    INSERT INTO search_index (source_table, source_id, text) SELECT 'skills', NEW.id, coalesce(NEW.name, '') WHERE NEW.status <> 'Deprecated';
  END;
CREATE TRIGGER qa_search_ins AFTER INSERT ON qa WHEN NEW.status <> 'Deprecated'
  BEGIN INSERT INTO search_index (source_table, source_id, text) VALUES ('qa', NEW.id, coalesce(NEW.question, '') || ' ' || coalesce(NEW.answer, '')); END;
CREATE TRIGGER qa_search_upd AFTER UPDATE OF question, answer, status ON qa
  BEGIN
    DELETE FROM search_index WHERE source_table = 'qa' AND source_id = OLD.id;
    INSERT INTO search_index (source_table, source_id, text) SELECT 'qa', NEW.id, coalesce(NEW.question, '') || ' ' || coalesce(NEW.answer, '') WHERE NEW.status <> 'Deprecated';
  END;
CREATE TRIGGER item_metrics_search_ins AFTER INSERT ON item_metrics WHEN NEW.status <> 'Deprecated'
  BEGIN INSERT INTO search_index (source_table, source_id, text) VALUES ('item_metrics', NEW.id, coalesce(NEW.label, '') || ' ' || coalesce(NEW.value, '')); END;
CREATE TRIGGER item_metrics_search_upd AFTER UPDATE OF label, value, status ON item_metrics
  BEGIN
    DELETE FROM search_index WHERE source_table = 'item_metrics' AND source_id = OLD.id;
    INSERT INTO search_index (source_table, source_id, text) SELECT 'item_metrics', NEW.id, coalesce(NEW.label, '') || ' ' || coalesce(NEW.value, '') WHERE NEW.status <> 'Deprecated';
  END;
CREATE TRIGGER positions_search_ins AFTER INSERT ON positions WHEN NEW.status <> 'Deprecated'
  BEGIN INSERT INTO search_index (source_table, source_id, text) VALUES ('positions', NEW.id, coalesce(NEW.title, '') || ' ' || coalesce(NEW.department, '')); END;
CREATE TRIGGER positions_search_upd AFTER UPDATE OF title, department, status ON positions
  BEGIN
    DELETE FROM search_index WHERE source_table = 'positions' AND source_id = OLD.id;
    INSERT INTO search_index (source_table, source_id, text) SELECT 'positions', NEW.id, coalesce(NEW.title, '') || ' ' || coalesce(NEW.department, '') WHERE NEW.status <> 'Deprecated';
  END;
CREATE TRIGGER employers_search_ins AFTER INSERT ON employers WHEN NEW.status <> 'Deprecated'
  BEGIN INSERT INTO search_index (source_table, source_id, text) VALUES ('employers', NEW.id, coalesce(NEW.name, '')); END;
CREATE TRIGGER employers_search_upd AFTER UPDATE OF name, status ON employers
  BEGIN
    DELETE FROM search_index WHERE source_table = 'employers' AND source_id = OLD.id;
    INSERT INTO search_index (source_table, source_id, text) SELECT 'employers', NEW.id, coalesce(NEW.name, '') WHERE NEW.status <> 'Deprecated';
  END;

PRAGMA user_version = 4;  -- keep equal to store.SCHEMA_VERSION

-- ux_v2 triggers
-- A row the AI adds is not trusted until the person has seen it: once its insert is audited it is flipped to
-- 'Needs review'. A status the AI chose (anything but the table's default) is kept; the Verified-default tables
-- cannot tell an explicit 'Verified' from the default. (Hooked on audit because the *_after_ins triggers
-- clear updated_by, and an earlier-firing flip would make their own stamping update fail.)
CREATE TRIGGER employers_ai_review AFTER INSERT ON audit
  WHEN NEW.op = 'insert' AND NEW.actor = 'ai' AND NEW.table_name = 'employers' AND json_extract(NEW.new_json, '$.status') = 'Verified'
  BEGIN UPDATE employers SET status = 'Needs review', updated_by = 'ai' WHERE rowid = NEW.row_id; END;
CREATE TRIGGER positions_ai_review AFTER INSERT ON audit
  WHEN NEW.op = 'insert' AND NEW.actor = 'ai' AND NEW.table_name = 'positions' AND json_extract(NEW.new_json, '$.status') = 'Verified'
  BEGIN UPDATE positions SET status = 'Needs review', updated_by = 'ai' WHERE rowid = NEW.row_id; END;
CREATE TRIGGER skills_ai_review AFTER INSERT ON audit
  WHEN NEW.op = 'insert' AND NEW.actor = 'ai' AND NEW.table_name = 'skills' AND json_extract(NEW.new_json, '$.status') = 'Verified'
  BEGIN UPDATE skills SET status = 'Needs review', updated_by = 'ai' WHERE rowid = NEW.row_id; END;
CREATE TRIGGER education_ai_review AFTER INSERT ON audit
  WHEN NEW.op = 'insert' AND NEW.actor = 'ai' AND NEW.table_name = 'education' AND json_extract(NEW.new_json, '$.status') = 'Verified'
  BEGIN UPDATE education SET status = 'Needs review', updated_by = 'ai' WHERE rowid = NEW.row_id; END;
-- An unanswered question stays 'Needs answer'; an answer the AI wrote needs review.
CREATE TRIGGER qa_ai_review AFTER INSERT ON audit
  WHEN NEW.op = 'insert' AND NEW.actor = 'ai' AND NEW.table_name = 'qa' AND json_extract(NEW.new_json, '$.status') = 'Needs answer'
    AND json_extract(NEW.new_json, '$.answer') IS NOT NULL
  BEGIN UPDATE qa SET status = 'Needs review', updated_by = 'ai' WHERE rowid = NEW.row_id; END;
