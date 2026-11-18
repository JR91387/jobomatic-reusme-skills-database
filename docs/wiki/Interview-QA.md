# Interview Q&A

The `qa` table holds interview questions and the person's answers. Good answers also feed resumes and cover letters.

## Table
Columns: `id`, `person_id`, `question`, `category`, `common_wordings`, `answer`, `status`, `sort`, `seeded`, `notes`.
- `category`: `About you`, `Behavioral`, `Strengths`, `Motivation`, `Situational`, `Logistics`, `Other`.
- `status`: `Needs answer` (default), `Needs review`, `Verified`, `Deprecated`.
- `seeded`: 1 for the ten questions every install starts with (`sort` 1 to 10); 0 for questions added later (`sort` NULL unless you set it).
- `UNIQUE (person_id, question)`: no duplicate question. `question` cannot be blank.
- `answer` is NULL until answered.

The ten seeded questions start unanswered: tell me about yourself; what you know about our company; why you are leaving; strengths and weaknesses; what motivates you; career goals; a failure; a conflict; adapting under pressure; prioritizing and remote work.

## `qa_open`
MCP tool, no arguments. Returns every `qa` row with status `Needs answer` or `Needs review`, ordered by `sort` then `id`. SQL: `SELECT * FROM qa WHERE status IN ('Needs answer','Needs review') ORDER BY sort IS NULL, sort, id`.

`search` leaves out seeded questions with no answer unless you pass `include_unanswered=true`.

## How to help
1. Call `qa_open`. Pick one question. Work one at a time.
2. Read the facts first: `get_profile`, or `search` with the question text.
3. Draft an answer from the person's own facts and numbers. Show it. Let them change it.
4. Save it:
```
save("qa", {"id": 1, "answer": "...", "status": "Needs review"}, expected_updated_at="<value you read>")
```
   or `UPDATE qa SET answer='...', status='Needs review', updated_by='ai' WHERE id=1`. An answer you write is held at `Needs review` (trigger `qa_ai_review`). Set `Verified` only after the person approves.
5. Ask which other questions they keep meeting. Add them:
```
save("qa", {"question": "Why do you want to work in logistics?", "category": "Motivation", "seeded": 0})
```
   `seeded` is not an editable column through `save`: it defaults to 0, which is what you want. `common_wordings` can hold other ways the question gets asked.
6. Question 2 ("What do you know about our company ...") changes per company. Store a reusable frame in `answer`, and tailor it each time in the reply, not in the stored row.

To retire a question: `retire("qa", id)` (sets `Deprecated`).

Related: [[Rules-and-Invariants]], [[Table-Reference]].
