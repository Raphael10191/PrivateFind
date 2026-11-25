# Floating bubbles implementation — 2026-11-25

Implemented locally on `feature/iot-ui-redesign`, using the uploaded `bubbles.docx` as an interaction reference and the user's native-frontend requirements as the implementation authority. No React, Tailwind, TypeScript, Framer Motion, shadcn, dependencies or demo content were introduced.

## Page intensity

| Page | Desktop | Tablet up to 1100px | Phone up to 760px | Layer opacity |
| --- | ---: | ---: | ---: | ---: |
| My Reports, Claims & Pickup, Profile | 16 | 10 | 6 | 0.65 |
| Populated Reports and Claims | 16 | 10 | 6 | 0.35 |
| Landing, Sign In, Registration | 12 | 10 | 6 | 0.50 |
| Owner Home | 6 | 6 | 4 | 0.28 |
| Reporting forms/details, claim verification, Finder, Admin, How It Works | 0 | 0 | 0 | Existing backgrounds retained |

The layer opacity multiplies each bubble's 0.18–0.32 animated opacity. Colors are lavender `#C7B9F1`, sky blue `#B4DEFA`, soft purple `#D5CDF9` and pale cyan `#BCE9F8`. Movement takes 25–43 seconds in alternating directions, with 0.96–1.06 scaling and deterministic negative delays. Mobile diameters are reduced to 70%. The gradients are static and faint; existing atmospheric artwork and mascots are preserved.

## Controls and behavior

The existing desktop owner cat Pause animation control shares pause state with the bubbles and decorative companions. A reserved 44 × 44 header slot provides an accessible Pause/Resume icon button on public pages and owner phones without inserting space into the page content. Reduced motion disables the control and leaves a static background. Manual pause survives document visibility changes and back/forward cache lifecycle events within the page. There is no new storage or cross-page preference persistence.

CSS handles movement; JavaScript only changes state on control, visibility, media-preference, intersection and page-lifecycle events. With JavaScript or IntersectionObserver unavailable, bubbles remain static. The layer is hidden from assistive technology, ignores pointer input and clips decorations within the existing main region. Bubble positions don't influence layout. Public short pages fill available space with a one-pixel rounding allowance to avoid introducing an unnecessary scrollbar. Existing form/card backgrounds remain opaque enough to keep inputs and data dominant.

## Exact files changed for this feature

Production templates:

- `frontend/templates/floating_bubbles.html` — new reusable background/control macros and deterministic circle parameters.
- `frontend/templates/base.html` — shared rendering and header control placement.
- `frontend/templates/icons.html` — pause/play glyphs in the existing SVG icon macro.
- `frontend/templates/owner_reports.html`
- `frontend/templates/owner_claims.html`
- `frontend/templates/owner_account.html`
- `frontend/templates/owner_home.html`
- `frontend/templates/owner_login.html`
- `frontend/templates/owner_register.html`
- `frontend/templates/public_home.html`

The seven page templates above opt in explicitly with a one-line mode block. Shared navigation identifiers do not enable bubbles on report or verification forms.

Assets and motion integration:

- `frontend/assets/privatefind.css` — palette, sizes, intensity, keyframes, clipping, responsive counts, control layout, static/high-contrast/print fallbacks.
- `frontend/assets/privatefind-ui.js` — small background lifecycle controller and shared cat Pause integration.
- `frontend/assets/privatefind.js` — only the existing Scout/companion motion section changes: shared pause checks and notifications. API/authentication/reporting code is unchanged.

Checks:

- `frontend/tests/floating_bubbles.test.cjs` — new lifecycle, accessible controls, reduced-motion and static-fallback behavior checks.
- `frontend/tests/peek_cat.test.cjs` — shared cat/background pause regression.
- `frontend/tests/companion_motion.test.cjs` — shared companion pause regression.
- `frontend/tests/redesign_preview.py` — checks the page allowlist and excludes forms/Finder/Admin despite shared navigation state.

Documentation/evidence: this report, `design-qa.md`, and `docs/design/floating-bubbles-2026-11-25/` screenshots/JSON measurements. Earlier uncommitted changes in other files are preserved and are not part of this feature's file list.

## Performance and verification

At most 16 decorative spans are rendered; responsive CSS hides surplus circles. No new assets, network requests, timers, continuous JavaScript rendering loops, blur filters or dependencies are added. Only transforms and opacity animate. Existing mascot rendering loops are preserved and now honor shared pause. This is an implementation/lifecycle check, not a formal GPU/FPS benchmark.

All seven enabled pages were captured/measured at 1440 × 900 desktop, 900 × 900 tablet, 390 × 844 and 320 × 844 phones. No horizontal overflow was measured. Public layouts were recaptured after the fractional-height fix; short Sign In/Registration pages retain the viewport height without decoration-induced scrolling. Fresh metrics are in `layout-checks.json` and `public-layout-final.json`; scrollbar gutters explain client/scroll-width differences.

Browser interactions verified the desktop sidebar Pause/Resume, phone header Pause/Resume on populated Claims, and public Pause/Resume on Registration. A paused bubble's computed transform stayed identical across observations and its CSS play state was paused. The cat returned to its neutral pose while paused. The Sign In mascot still responds to keyboard focus on the password field without reading any field values. Populated Claims at 320px retained the 0.35 intensity and readable opaque cards. Browser error log: empty at final verification.

All 48 frontend regression/contrast checks pass, including all existing checks and eight additional shared-motion checks. All 38 route/state renders pass, including duplicate-ID and explicit bubble-scope checks. `git diff --check` passes. Reduced-motion changes, hidden/offscreen suspension, missing-observer fallback and page lifecycle are behavior-tested in the dependency-free harness; OS-level reduced-motion/high-contrast settings were not changed during browser verification.

No backend, API contract/request, authentication, reporting, matching, ownership verification, sandbox, database, Docker or hardware change. No commit, push, merge or deployment.
