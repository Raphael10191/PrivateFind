# PrivateFind — Task Checklist

Source: `PrivateFind_Project_Proposal_v2.pdf` (WBS, Gantt, milestones), updated with `PrivateFind_Revised_Project_Proposal.pdf` (Week 5 version).
Format: `WBS id — task — owner + support (planned hours)`. Week start dates follow the Gantt chart.

Owners: **Z** = Zohidjon (lead, AI/backend) · **M** = Muslimbek (UI/frontend) · **S** = Simon (DB/matching) · **R** = Raphael (IoT/locker)

Critical chains (no float):
- Software: 4.4 → 5.2 → 6.3 → 6.6 → 6.9 → MVP → 9.1 → 9.3 → Security → Feature complete
- Hardware: 3.4 → 5.5 → 6.8 → 7.3 → 9.4 → 9.5

---

## Ongoing
- [ ] 1.1 — Weekly meeting & coordination — Z + All (65 h, W3–W15)

## Week 3 (15.09) — Requirements & SDLC
- [ ] 2.1 — Finalize SRS — Z + All (15 h)
- [ ] 2.2 — SDLC justification — Z + S (5 h)
- [ ] **M1 — Requirements and SDLC approved**

## Week 4 (22.09) — Estimation & planning
- [ ] 3.1 — COCOMO estimation — S + Z (7 h)
- [ ] 3.2 — Work breakdown structure — Z + All (6 h)
- [ ] 3.3 — Initial schedule & staffing — S + Z (6 h)
- [ ] 3.4 — Order locker hardware — R (2 h) ⚠ critical (hardware chain)
  - [x] ESP32, keypad, 1 servo, breadboards bought (W5)
  - [ ] 2nd servo, 2 IR sensors, 16x2 I2C LCD (W6)
- [ ] 4.5 — Figma wireframes (start, W4–W5) — M + All (15 h)
- [ ] **M2 — Estimation, WBS and initial schedule agreed**

## Week 5 (29.09) — Design  ← current week
- [ ] 4.1 — System architecture — Z + R (4 h)
- [ ] 4.2 — REST API contracts — Z + R (4 h)
- [ ] 4.3 — AI input/output schema — Z + S (4 h)
- [ ] 4.4 — ER diagram & DB design — S + Z (7 h) ⚠ critical
- [ ] 4.5 — Figma wireframes (finish) — M + All
- [ ] 4.6 — Locker hardware design — R + S (5 h)
- [ ] 5.5 — ESP32 breadboard test (start, W5–W6) — R (8 h) · ESP32 + keypad + 1st servo already running
- [ ] Align revised proposal with architecture decisions (FR3 → any e-mail, no embeddings, Python 3.13) — Z
- [ ] **M3 — Design approved** (architecture, ER model, AI data contract, wireframes reviewed)

## Week 6 (06.10) — Scheduling & setup
- [ ] 5.1 — Git repo & dev environment — Z + All (6 h)
- [ ] 5.2 — MySQL schema & SQLAlchemy models / Alembic — S + Z (9 h) ⚠ critical
- [ ] 5.3 — FastAPI skeleton & AI mock — Z (5 h)
- [ ] 5.4 — Frontend base templates — M (6 h)
- [ ] 5.5 — ESP32 breadboard test (finish) — R ⚠ critical
- [ ] **M4 — Schedule, repository and database baseline ready**

## Week 7 (13.10) — Increment 1: core
- [ ] 3.5 — Proposal presentation (13 & 15 Oct, moved from W5) — Z + All (9 h)
- [ ] 6.1 — Authentication & roles — Z + S (8 h)
- [ ] 6.2 — QR finder flow & photo upload — M + Z (8 h)
- [ ] 6.3 — Item persistence & photos — S + Z (7 h) ⚠ critical
- [ ] 6.4 — Lost-item report form — M + S (6 h)
- [ ] 6.5 — AI attribute extraction (W7–W8) — Z + M (9 h)
- [ ] 6.6 — Match Score v1 (W7–W8) — S (9 h) ⚠ critical
- [ ] 6.7 — Locker API & code lifecycle (W7–W8) — R + Z (10 h)
- [ ] 6.8 — ESP32 firmware v1 (W7–W8) — R (8 h) ⚠ critical
- [ ] **M5 — First running increment** (QR reporting, owner reporting, DB persistence via FastAPI)

## Week 8 (20.10) — MVP checkpoint
- [ ] Finish 6.5, 6.6, 6.7, 6.8
- [ ] 6.9 — Candidate & claim screens — M + Z (10 h) ⚠ critical
- [ ] **M6 — MVP / midterm demo** (photo → attributes → candidate → claim, mock locker)
- [ ] Re-estimate remaining effort and update the Gantt chart

## Week 9 (27.10) — Integration & reuse
- [ ] 7.1 — Integrate reused libraries — Z + M (7 h, float +1 wk)
- [ ] 7.2 — Semantic similarity — S + Z (8 h, float +2 wk)
- [ ] 7.3 — ESP32 libs & REST contract — R + Z (7 h) ⚠ critical
- [ ] 7.4 — UI/UX fixes from midterm (W9–W10) — M (6 h)
- [ ] 9.1 — Verification Engine (W9–W11) — Z + S (15 h) ⚠ critical
- [ ] 9.4 — Physical locker build (W9–W11) — R + S (14 h) ⚠ critical

## Week 10 (03.11) — Security
- [ ] 8.1 — Access & private-photo rules — Z + M (6 h)
- [ ] 8.2 — Input validation & SQL-injection protection — S + M (7 h)
- [ ] 8.3 — Attempt & rate limits — S + Z (6 h)
- [ ] 8.4 — ESP32 device authentication — R + Z (6 h)
- [ ] 8.5 — Security audit document — Z + All (5 h)

## Week 11 (10.11) — Final feature development
- [ ] Finish 9.1 Verification Engine and 9.4 Physical locker build
- [ ] 9.2 — Audit log — S (5 h)
- [ ] 9.3 — Admin review screens — M + Z (9 h) ⚠ critical
- [ ] 9.5 — Locker–backend integration — R + Z (8 h) ⚠ critical
- [ ] **M7 — Feature complete** (matching, verification, review, physical locker work together)

## Week 12 (17.11) — Integration & review
- [ ] 10.1 — End-to-end scenarios — Z + All (9 h)
- [ ] 10.2 — Score evaluation (synthetic match/non-match cases) — S + Z (6 h)
- [ ] 10.3 — Peer code reviews — All (8 h)
- [ ] 10.4 — Bug fixing — All (12 h)
- [ ] **M8 — Release candidate**

## Week 13 (24.11) — Quality assurance
- [ ] 11.1 — Unit, API & AI-failure tests — Z + S (5 h)
- [ ] 11.2 — DB & transaction tests — S (4 h)
- [ ] 11.3 — UI tests — M (4 h)
- [ ] 11.4 — Locker/device failure tests — R + S (5 h)
- [ ] 11.5 — Test report — Z + All (5 h)
- [ ] **M9 — Project complete** (testing done, no high-severity defect open; final source, executable, test report)

## Week 14 (01.12) — Deployment & handover
- [ ] 12.1 — Deployment package & setup scripts — S + Z (6 h)
- [ ] 12.2 — User & maintenance manuals — M + R (7 h)
- [ ] 12.3 — Final presentation & demo prep (W14–W15) — All (12 h)

## Week 15 (08.12) — Final showcase
- [ ] 12.3 — Live demonstration & presentation — All
- [ ] **M10 — Final showcase**
