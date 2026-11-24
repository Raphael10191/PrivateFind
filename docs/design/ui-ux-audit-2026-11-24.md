# PrivateFind UI/UX audit

Date: 2026-11-24. Review only; no application code changed during this audit.

Implementation update: F1–F9 and the additional polish items have now been addressed in the frontend. See the [fix verification](ux-fixes-verification-2026-11-24.md) for implementation details, screenshots, and test limits. The original findings below are retained as the audit record.

## Scope and evidence

Reviewed the owner/finder journeys on desktop (1440 × 1000 CSS pixels) and mobile (390 × 844): dashboard, lost reporting, found-item entry, reports, possible matches, ownership verification, claims, and combined search/status filters. Screenshots were captured and inspected in this audit run; previous visual-QA screenshots were not reused.

Owner screens use the isolated read-only sample server on port 8003. Found-item entry was inspected against the real frontend/backend on port 8002. The sample server intentionally reports AI unavailable, and the live finder currently shows the same service-unavailable state. Successful reporting, claim submission, physical deposit, and pickup were not exercised. Admin and authentication flows were not included in this focused audit. This is not a WCAG compliance assessment.

The primary lost/found actions are easy to spot. Navigation labels remain visible, the mobile bottom navigation is persistent, and the empty claims screen explains how to start a claim. The most important gaps are explanation and recovery when a task is blocked, clearer action labels, and mobile report usability.

## Prioritized findings

### F1 — High: Ownership verification has no visible explanation for its unavailable action

- Evidence: captures 06 and 10. The screen shows a faded `Check Ownership` control and no service warning. The inspected DOM contains an AI-unavailable notice with `hidden` set; the form's action is absent from the interactive accessibility tree.
- Impact: users cannot tell whether they should provide more information, wait, or return to the previous step.
- Work on: `owner_claim.html`, shared availability presentation, and the claim action panel. Keep the availability guard. Always show the reason beside the blocked action, plus a status recheck and a clear return route.

### F2 — High: Reporting outages end with “try again later” and no practical recovery

- Evidence: captures 02, 03, and 11. Both lost and found reporting show a paused form. The warning provides no recheck action or fallback guidance. Fading the entire form also fades its instructions.
- Impact: users reach a prominent primary action and then cannot complete or recover from it.
- Work on: the shared service notice, lost-report form, and finder entry. Add a clearly labeled availability recheck using the existing service-status endpoint. Keep explanatory text readable. Provide a return link and verified campus hand-in guidance if available. Do not enable submissions while the service is unavailable.

### F3 — Medium: The found-item entry assumes the user already understands locker codes

- Evidence: captures 03 and 11. The heading says `Choose the locker`, but the screen offers a printed-code input rather than a choice of lockers. The preceding dashboard action only says `Report a Found Item`.
- Impact: a finder starting away from a locker can enter a flow without knowing its physical prerequisite.
- Work on: the dashboard found-item card and finder introduction. State that this flow returns an item through a campus locker, label the field section `Enter the locker code`, show where the printed code/QR is located, and label the next action `Continue to photos` or `Check locker`, according to its actual result.

### F4 — Medium: Mobile report cards have weak tap affordances

- Evidence: capture 08. Tapping the `Headphones` title left the user on the dashboard; only the arrow opens the report. The mobile visual label `View Details` is replaced by an arrow.
- Impact: a natural tap on the main card content appears unresponsive, and the next destination is less explicit.
- Work on: `owner_dashboard.html` and dashboard-card styling. Make the report title or entire card a clear link, preserve a generous touch target, and use a short visible label such as `View report` or `View matches` where appropriate.

### F5 — Medium: Item names and status language change across screens

- Evidence: capture 01 calls report 3 `Water Bottle`; capture 04 calls the same report `Black Bottle`. The list filter says `Completed`, while the card state says `Resolved`.
- Impact: users must reconcile different names for the same item and infer which statuses belong under each filter.
- Work on: shared frontend item-title formatting and status labels in the dashboard, reports list, and detail screen. Use one display name per report. Explain the difference if `Resolved`, `Closed`, and `Collected` represent different outcomes; do not relabel them as collected without backend confirmation.

### F6 — Medium: Matches and the claim/pickup journey are not obvious from entry labels

- Evidence: captures 01, 04, 05, and 07. Users enter possible matches through a generic `View Details` action under reports. `My Claims` is separate, and its empty screen explains that a claim starts from a report's possible match.
- Impact: first-time users may not know where to check whether an item was found or what a claim means.
- Work on: dashboard row actions, report detail links, and navigation copy. Use `View report & matches` where matches are part of that destination. Consider `Claims & Pickup` and a short `Report → Match → Verify → Collect` explanation without implying all claims are already approved.

### F7 — Medium: Ownership verification drops the selected-item context

- Evidence: captures 06 and 10. The page says `selected item`, but does not show its public category, location, date, or the associated lost-report name before the action.
- Impact: the user cannot confirm which item they are about to verify, particularly after returning later or opening several reports.
- Work on: the ownership page header. Add a compact summary using only already-authorized public/report data. Keep private found-item photos, distinctive marks, and ownership evidence protected.

### F8 — Medium: Search plus a status filter can produce an unclear dead end

- Evidence: capture 09. Searching `wallet` shows one report. Selecting `Completed` shows `0 reports matching “wallet”`; the empty message suggests changing or clearing the search but does not mention the status filter. No explicit `Clear filters` action appears.
- Impact: users can conclude that the report is missing when it is only excluded by the current combination.
- Work on: `privatefind-ui.js` and the reports empty state. Say `No completed reports match “wallet”`, show the active constraints, and offer `Clear filters` / `Show all reports` controls. Keep query and filter state understandable when navigating back.

### F9 — Medium: The mobile dashboard spends its first screen on welcome content

- Evidence: capture 08. The first report begins around 640 pixels down; the welcome block and two large report actions occupy most of the first viewport. Status/date/location text is much smaller than the headings.
- Impact: returning users must scroll to inspect existing work and scan small text to find its status.
- Work on: the mobile dashboard layout and typography. Use a compact returning-user welcome, reduce the height of the creation actions, and move actionable report/claim information upward. Increase essential metadata toward 13–14 pixels and test long item names and larger text settings.

## Additional polish

- Capture 01: the shield-only header help link looks like a security/status symbol. A help icon or visible `Help` label would better predict its `How it works` destination.
- Capture 05: public candidate cards have no photos or distinctive details by design. Explain that those details stay private for ownership verification so the limited information feels intentional. Do not expose private fields to make the cards more descriptive.
- Capture 04: report list cards use substantially more vertical space than dashboard cards. A more compact shared card pattern would improve scanning.
- Capture 02: the item/place/date disclosure is easy to overlook. Test whether a short visible optional location/date summary improves report quality while preserving the current request schema. This is a usability hypothesis, not an observed submission failure.

## Flow steps and health

| Step | Surface | Health and notes | Evidence |
|---|---|---|---|
| 1 | Desktop dashboard | Clear primary entry actions; generic report actions and inconsistent terminology need work. | 01 |
| 2 | Lost-report entry | Blocked by availability; warning is visible but recovery is weak. Normal validation could not be tested. | 02 |
| 3 | Found-item entry | Blocked by availability; locker prerequisite and next-action labels need clarification. | 03 |
| 4 | Reports list | Usable filters and detail links; naming and card density need consistency. | 04 |
| 5 | Report details / possible matches | Clear ownership action; match discovery and privacy explanation can improve. | 05 |
| 6 | Ownership check | Blocked action with its reason hidden; selected-item context is missing. | 06 |
| 7 | Claims empty state | Understandable instructions and a link back to reports; navigation terminology can be clearer. | 07 |
| 8 | Mobile dashboard / card tapping | Clear creation actions and persistent navigation; reports are low on the screen and title taps do nothing. | 08 |
| 9 | Mobile search plus status filter | Filtering works; zero-results explanation and reset controls need work. | 09 |
| 10 | Mobile ownership check | Confirms the unexplained unavailable action and missing item summary. | 10 |
| 11 | Mobile found-item entry | Confirms faded instructions, paused action, and weak recovery. | 11 |

## Screenshot evidence

All captures are in `docs/design/ux-audit/`. The overview is a crop/contact sheet of accepted current-run captures; individual screenshots below remain the evidence of record.

![Audit overview](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/audit-overview.jpg)

### 01 — Desktop dashboard
![01 dashboard](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/01-dashboard-desktop.jpg)

### 02 — Lost report
![02 lost reporting](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/02-lost-report-paused.jpg)

### 03 — Found-item entry
![03 finder entry](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/03-found-item-entry.jpg)

### 04 — Reports list
![04 reports](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/04-reports-list.jpg)

### 05 — Matches
![05 possible matches](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/05-report-details.jpg)

### 06 — Ownership
![06 ownership](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/06-ownership-check.jpg)

### 07 — Claims
![07 empty claims](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/07-claims-empty.jpg)

### 08 — Mobile dashboard
![08 mobile dashboard](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/08-dashboard-mobile.jpg)

### 09 — Search and filters
![09 search filters](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/09-search-filter-empty-mobile.jpg)

### 10 — Mobile ownership
![10 mobile ownership](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/10-ownership-mobile.jpg)

### 11 — Mobile finder
![11 mobile finder](C:/Users/MSI/Downloads/projectsrepoclone/PrivateFind/docs/design/ux-audit/11-found-item-mobile.jpg)

## Recommended work order

1. Fix ownership availability messaging and reporting recovery (F1–F2).
2. Make report actions and the match/claim journey explicit (F4, F6, F7).
3. Fix combined-search recovery and consistent names/statuses (F5, F8).
4. Clarify locker entry and refine mobile hierarchy/readability (F3, F9).
5. Re-audit successful submission, ownership, and pickup states when the required AI/device services are available. These were not validated by this audit.

Recommendations can preserve the existing backend endpoints and payloads. No recommendation requires weakening availability checks or ownership privacy.

## Resolution checklist

- [x] F1: Availability notices update when asynchronous forms become visible; blocked ownership actions show a reason and recovery controls.
- [x] F2: Added an availability recheck and return route; paused form instructions remain readable.
- [x] F3: Clarified the campus-locker prerequisite, printed code/QR guidance, and next-action label.
- [x] F4: Made dashboard report cards/title areas links and added visible report/match action labels.
- [x] F5: Unified item names across server-rendered cards and client-rendered details; explained completed/resolved/closed terminology without inventing collection status.
- [x] F6: Clarified report/match entry points and renamed navigation to Claims & Pickup.
- [x] F7: Added selected-item context using only the existing owner report and public candidate endpoints, with fallback guidance.
- [x] F8: Added specific combined-filter feedback, a clear/reset action, URL state, and Back restoration.
- [x] F9: Compacted the returning-user mobile dashboard and increased essential metadata sizes.
- [x] Additional polish: visible Help label, match privacy explanation, denser report cards, and clearer optional-field guidance.

Live successful submission and physical locker verification remain dependent on the existing AI/device configuration; the fixes preserve those availability guards.
