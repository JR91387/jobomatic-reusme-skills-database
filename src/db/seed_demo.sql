-- Demo data: every name, employer, number and contact below is invented. Runs after seed_blank.sql.
BEGIN;

INSERT INTO people (id, name, full_name, first_name, last_name, headline, location, phone, email, summary,
                    work_authorization, work_auth_status, work_auth_country, updated_by) VALUES
  (1, 'Odalys Brannigan-Voss', 'Odalys Brannigan-Voss', 'Odalys', 'Brannigan-Voss',
   'Operations Coordinator - scheduling, inventory and vendor logistics',
   'Springfield Heights, Ohio', '+15555550142', 'odalys@example.com',
   'Operations coordinator with ten years in warehousing, dispatch and light manufacturing. Known for turning messy handoffs into simple daily routines that people actually follow.',
   'Authorized to work in the United States', 'Authorized', 'United States', 'app');

INSERT INTO links (person_id, kind, label, url, sort, updated_by) VALUES
  (1, 'LinkedIn', NULL, 'https://example.com/in/odalys-brannigan-voss', 0, 'app'),
  (1, 'Website', 'Personal site', 'https://odalys.example.com', 1, 'app'),
  (1, 'Portfolio', 'Process maps', 'https://odalys.example.com/process-maps', 2, 'app');

INSERT INTO tracks (name, sort, updated_by) VALUES ('Leadership', 20, 'app');

INSERT INTO employers (id, person_id, name, location, updated_by) VALUES
  (1, 1, 'Brightwater Appliance Co.', 'Springfield Heights, Ohio', 'app'),
  (2, 1, 'Lantern Row Logistics', 'Columbus, Ohio', 'app'),
  (3, 1, 'Cobblestone Print & Pack', 'Dayton, Ohio', 'app');

-- Lantern Row has two positions: a promotion from Dispatch Assistant to Dispatch Scheduler.
INSERT INTO positions (id, person_id, employer_id, title, department, start_date, end_date, sort_order, notes, updated_by) VALUES
  (1, 1, 1, 'Operations Coordinator', 'Distribution', '2023-03', NULL, 1, 'Current role.', 'app'),
  (2, 1, 2, 'Dispatch Scheduler', 'Dispatch', '2021-01', '2023-02', 2, NULL, 'app'),
  (3, 1, 3, 'Production Assistant', 'Production', '2016-08', '2019-05', 4, NULL, 'app'),
  (4, 1, 2, 'Dispatch Assistant', 'Dispatch', '2019-06', '2020-12', 3, NULL, 'app');

-- Items 1-12 are achievements; item 1 sits inside project 15; item 17 is not tied to a job.
-- Item 1's parent is set after project 15 exists (a parent must be inserted first).
INSERT INTO items (id, person_id, position_id, parent_item_id, kind, title, detail, outputs, organization, from_whom, start_date, end_date, source, status, updated_by) VALUES
  (1, 1, 1, NULL, 'Achievement', NULL, 'Rebuilt the daily dispatch board so orders move to the dock in priority order.', NULL, NULL, NULL, NULL, NULL, '2024 review', 'Verified', 'app'),
  (2, 1, 1, NULL, 'Achievement', NULL, 'Merged 14 inventory spreadsheets into one shared tracker.', NULL, NULL, NULL, NULL, NULL, NULL, 'Verified', 'app'),
  (3, 1, 1, NULL, 'Achievement', NULL, 'Ran a rate review across six regional carriers and renegotiated contracts.', NULL, NULL, NULL, NULL, NULL, NULL, 'Verified', 'app'),
  (4, 1, 1, NULL, 'Achievement', NULL, 'Trained nine new warehouse hires on the receiving checklist.', NULL, NULL, NULL, NULL, NULL, '2024 review', 'Verified', 'app'),
  (5, 1, 1, NULL, 'Achievement', NULL, 'Led the cross-team response to a three-week parts shortage.', NULL, NULL, NULL, NULL, NULL, NULL, 'Verified', 'app'),
  (6, 1, 2, NULL, 'Achievement', NULL, 'Scheduled drivers across three depots.', NULL, NULL, NULL, NULL, NULL, NULL, 'Verified', 'app'),
  (7, 1, 2, NULL, 'Achievement', NULL, 'Rescheduled route blocks to cut overtime.', NULL, NULL, NULL, NULL, NULL, NULL, 'Verified', 'app'),
  (8, 1, 2, NULL, 'Achievement', NULL, 'Introduced a morning handoff checklist between dispatch shifts.', NULL, NULL, NULL, NULL, NULL, NULL, 'Verified', 'app'),
  (9, 1, 2, NULL, 'Achievement', NULL, 'Resolved customer escalations about late or missed deliveries.', NULL, NULL, NULL, NULL, NULL, NULL, 'Needs review', 'app'),
  (10, 1, 3, NULL, 'Achievement', NULL, 'Tracked print jobs from quote to delivery.', NULL, NULL, NULL, NULL, NULL, NULL, 'Verified', 'app'),
  (11, 1, 3, NULL, 'Achievement', NULL, 'Standardized sheet sizes to reduce paper offcuts.', NULL, NULL, NULL, NULL, NULL, NULL, 'Verified', 'app'),
  (12, 1, 3, NULL, 'Achievement', NULL, 'Coordinated a four-person weekend crew through the holiday rush.', NULL, NULL, NULL, NULL, NULL, NULL, 'Verified', 'app'),
  (13, 1, 1, NULL, 'Review', '2024 annual performance review', 'Rated "Exceeds expectations"; praised the dispatch board rebuild and new-hire training.', NULL, 'Brightwater Appliance Co.', 'Priya Halvorsen', '2024-01', '2024-12', NULL, 'Verified', 'app'),
  (14, 1, 1, NULL, 'Award', 'Operations Excellence Award', 'Company-wide award for the parts-shortage response.', NULL, 'Brightwater Appliance Co.', NULL, '2025-03', NULL, NULL, 'Verified', 'app'),
  (15, 1, 1, NULL, 'Project', 'Dispatch board rebuild', 'Replaced the paper dispatch board with a shared priority board used by the floor and the dock.', 'Shared priority board; one-page dock guide', NULL, NULL, '2023-09', '2024-02', '2024 review', 'Verified', 'app'),
  (16, 1, 4, NULL, 'Responsibility', NULL, 'Answered driver calls and logged route changes for the day shift.', NULL, NULL, NULL, NULL, NULL, NULL, 'Verified', 'app'),
  (17, 1, NULL, NULL, 'Volunteer', 'Warehouse volunteer', 'Set up the intake shelving and sorting routine at the community food pantry.', 'Shelf map; volunteer sorting sheet', 'Springfield Heights Food Pantry', NULL, '2022-01', NULL, NULL, 'Verified', 'app');
UPDATE items SET parent_item_id = 15, updated_by = 'app' WHERE id = 1;

INSERT INTO item_metrics (item_id, value, sort, status, updated_by) VALUES
  (1, 'Order-to-ship time 5.2 to 3.4 days (-35%)', 1, 'Verified', 'app'),
  (2, '14 files to 1', 1, 'Verified', 'app'),
  (2, 'weekly reconciliation 6 h to 1.5 h', 2, 'Verified', 'app'),
  (3, '$86,000 saved per year', 1, 'Verified', 'app'),
  (4, '9 hires', 1, 'Verified', 'app'),
  (4, '30-day error rate down 40%', 2, 'Verified', 'app'),
  (5, '97% on-time delivery held', 1, 'Verified', 'app'),
  (6, '42 drivers, 3 depots', 1, 'Verified', 'app'),
  (7, 'Overtime hours down 22%', 1, 'Verified', 'app'),
  (8, 'Missed pickups 11 to 3 per month', 1, 'Verified', 'app'),
  (9, '~30 per month', 1, 'Needs review', 'app'),
  (9, '95% resolved same day', 2, 'Needs review', 'app'),
  (10, '120 jobs per week', 1, 'Verified', 'app'),
  (11, 'Paper waste -18%', 1, 'Verified', 'app'),
  (11, '$9,400 saved per year', 2, 'Verified', 'app'),
  (12, '100% of holiday orders on time', 1, 'Verified', 'app'),
  (17, '1,200 lb sorted per Saturday', 1, 'Verified', 'app');

INSERT INTO bullet_variants (item_id, wording, angle, length, track, status, updated_by) VALUES
  (1, 'Rebuilt the daily dispatch board, cutting order-to-ship time from 5.2 to 3.4 days (-35%).', 'Impact', 'Short', 'Original', 'Verified', 'app'),
  (2, 'Merged 14 inventory spreadsheets into one shared tracker, reducing weekly reconciliation from 6 hours to 90 minutes.', 'Efficiency', 'Short', 'Original', 'Verified', 'app'),
  (3, 'Reviewed rates with six regional carriers and renegotiated contracts, saving $86,000 a year without changing delivery windows.', 'Cost', 'Long', 'Original', 'Verified', 'app'),
  (4, 'Trained nine new warehouse hires on the receiving checklist; their 30-day error rate ran 40% below the previous cohort.', 'Training', 'Short', 'Original', 'Verified', 'app'),
  (5, 'When a parts shortage hit for three weeks, pulled purchasing, the floor and two carriers into a daily 10-minute check-in, re-sequenced open orders by customer deadline, and kept on-time delivery at 97%. The plan became the template for later supply disruptions.', 'Crisis', 'Story', 'Original', 'Verified', 'app'),
  (6, 'Scheduled 42 drivers across three depots.', 'Scope', 'Short', 'Original', 'Verified', 'app'),
  (7, 'Reworked route blocks to cut overtime hours by 22%.', 'Cost', 'Short', 'Original', 'Verified', 'app'),
  (8, 'Introduced a morning handoff checklist between dispatch shifts, which brought missed pickups down from 11 to 3 per month and gave the team a shared record of open issues.', 'Process', 'Long', 'Original', 'Verified', 'app'),
  (9, 'Resolved about 30 delivery escalations a month, 95% on the same day.', 'Service', 'Short', 'Original', 'Needs review', 'app'),
  (10, 'Tracked 120 print jobs a week from quote to delivery.', 'Scope', 'Short', 'Original', 'Verified', 'app'),
  (11, 'Standardized sheet sizes with customers and the press crew, cutting paper waste 18% and saving $9,400 a year while keeping quote prices unchanged.', 'Cost', 'Long', 'Original', 'Verified', 'app'),
  (12, 'Before the holiday rush, split a four-person weekend crew into quote, press and pack stations with a posted hourly target. Every holiday order shipped on time, and the station layout was reused the next season.', 'Teamwork', 'Story', 'Original', 'Verified', 'app'),
  (1, 'Redesigned how the dispatch team prioritizes orders, and cut order-to-ship time 35% across the distribution floor.', 'Leadership', 'Short', 'Leadership', 'Verified', 'app'),
  (3, 'Led a six-carrier rate review and negotiated new contracts worth $86,000 in annual savings.', 'Leadership', 'Short', 'Leadership', 'Verified', 'app'),
  (4, 'Onboarded and coached nine new warehouse hires; cohort errors in the first 30 days fell 40%.', 'Leadership', 'Long', 'Leadership', 'Verified', 'app'),
  (5, 'Led purchasing, floor and carrier teams through a three-week parts shortage and held 97% on-time delivery.', 'Leadership', 'Short', 'Leadership', 'Verified', 'app'),
  (6, 'Managed schedules for 42 drivers across three depots, balancing coverage, rest rules and customer windows.', 'Leadership', 'Long', 'Leadership', 'Verified', 'app'),
  (8, 'Set up the shift-handoff routine that cut missed pickups from 11 to 3 a month.', 'Leadership', 'Short', 'Leadership', 'Verified', 'app'),
  (9, 'Owned escalation follow-up for late deliveries, resolving 95% the same day.', 'Leadership', 'Short', 'Leadership', 'Needs review', 'app'),
  (12, 'Directed a four-person weekend crew through the holiday rush with every order on time.', 'Leadership', 'Short', 'Leadership', 'Verified', 'app');

INSERT INTO skills (id, person_id, name, category, updated_by) VALUES
  (1, 1, 'Shift scheduling', 'Skill', 'app'),
  (2, 1, 'Vendor management', 'Skill', 'app'),
  (3, 1, 'Inventory control', 'Method', 'app'),
  (4, 1, 'Spreadsheet modeling', 'System', 'app'),
  (5, 1, 'Warehouse management software', 'System', 'app'),
  (6, 1, 'Lean process mapping', 'Method', 'app'),
  (7, 1, 'ISO 9001 internal audits', 'Standard', 'app');

INSERT INTO skill_links (skill_id, item_type, item_id, updated_by) VALUES
  (1, 'position', 2, 'app'),
  (2, 'position', 1, 'app'),
  (3, 'position', 1, 'app'),
  (3, 'position', 3, 'app'),
  (4, 'position', 1, 'app'),
  (5, 'position', 1, 'app'),
  (5, 'position', 2, 'app'),
  (6, 'position', 3, 'app'),
  (7, 'education', 2, 'app'),
  (6, 'education', 2, 'app');

INSERT INTO education (id, person_id, kind, name, institution, location, year, updated_by) VALUES
  (1, 1, 'Degree', 'B.A. in Business Administration', 'Fairmont Valley College', 'Fairmont, Ohio', '2016', 'app'),
  (2, 1, 'Certification', 'Logistics Coordination Certificate', 'Northgate Continuing Education', 'Columbus, Ohio', '2020', 'app');

UPDATE qa SET status = 'Verified', updated_by = 'app', answer = 'I coordinate daily operations for a mid-size appliance distributor. I started in print production, moved to dispatch scheduling, and now run the dispatch board and inventory tracking. I like work where a clear routine saves people time.' WHERE sort = 1;
UPDATE qa SET status = 'Verified', updated_by = 'app', answer = 'I want a role with more ownership of the full order flow, from purchasing to delivery. My current team is strong, and I have taken the dispatch process as far as the role allows.' WHERE sort = 3;
UPDATE qa SET status = 'Verified', updated_by = 'app', answer = 'Strength: I make handoffs simple, such as the checklist that cut missed pickups from 11 to 3 a month. Weakness: I used to over-plan; now I ship a first version of a routine and adjust after a week.' WHERE sort = 4;
UPDATE qa SET status = 'Verified', updated_by = 'app', answer = 'During a three-week parts shortage I promised a delivery date before checking the supplier. We missed it by two days. I called the customer the same day, rebuilt the order sequence, and now confirm dates with the supplier first.' WHERE sort = 7;
UPDATE qa SET status = 'Verified', updated_by = 'app', answer = 'I keep one shared board with orders sorted by customer deadline and review it at the start of each shift. For hybrid weeks I put the desk work on the days I am off the floor.' WHERE sort = 10;

INSERT INTO qa (person_id, question, category, common_wordings, status, seeded, updated_by) VALUES
  (1, 'Are you open to relocating or traveling for work?', 'Logistics', 'Would you relocate? How much travel are you comfortable with?', 'Needs answer', 0, 'user');

COMMIT;
