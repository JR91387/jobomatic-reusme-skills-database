BEGIN;
INSERT INTO settings (key, label, value, note, updated_by) VALUES
  ('recent_years', 'Recent years', '10', 'Jobs that ended fewer years ago than this count as Recent.', 'app'),
  ('older_years', 'Older cutoff', '15', 'Jobs that ended this many years ago or more count as the oldest group.', 'app');

INSERT INTO tracks (name, updated_by) VALUES ('Original', 'app');

INSERT INTO qa (question, category, sort, seeded, status, updated_by) VALUES
  ('Tell me about yourself / Walk me through your resume.', 'About you', 1, 1, 'Needs answer', 'app'),
  ('What do you know about our company and why do you want to work here?', 'Motivation', 2, 1, 'Needs answer', 'app'),
  ('Why are you leaving your current job and what are you looking for in your next role?', 'Motivation', 3, 1, 'Needs answer', 'app'),
  ('What is your greatest strength and what are your weaknesses?', 'Strengths', 4, 1, 'Needs answer', 'app'),
  ('What motivates you in your professional life?', 'Motivation', 5, 1, 'Needs answer', 'app'),
  ('What are your career goals and where do you see yourself in 5 years?', 'Motivation', 6, 1, 'Needs answer', 'app'),
  ('Tell me about a time you failed or made a mistake. How did you handle it?', 'Behavioral', 7, 1, 'Needs answer', 'app'),
  ('Describe a time you had a conflict with a coworker or difficult customer and how you resolved it.', 'Behavioral', 8, 1, 'Needs answer', 'app'),
  ('Give an example of when you had to adapt to change, manage stress, or lead a project under pressure.', 'Behavioral', 9, 1, 'Needs answer', 'app'),
  ('How do you prioritize tasks, stay organized, and handle remote or hybrid work?', 'Situational', 10, 1, 'Needs answer', 'app');
COMMIT;
