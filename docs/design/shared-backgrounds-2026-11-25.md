# Shared secondary-page background — 2026-11-25

## Scope and repair

User-confirmed problem: Reports, Claims & Pickup, Profile and How It Works used the same background asset at different scales and horizontal positions. Source screenshots were inspected in the requested order: 190441 (Reports), 190444 (Claims), 190446 (Profile), 190449 (guide). The screenshot browser chrome occupies about 150px of each 1920 × 1020 source, so the desktop check uses a 1920 × 870 content viewport.

The shared owner layout now renders the atmosphere once inside `main`, outside the narrower content sections. Existing content widths, mascot scenes, fonts, text, controls and interactions are preserved. Top and bottom images use the full shared workspace width, rather than different section widths or an inset 1440px bottom strip. Raster proportions are preserved. A stable scrollbar gutter keeps the artwork width consistent when moving between short and scrolling pages. Populated pages retain their quieter decoration opacity.

## Verification

1. **Reports — passed.** Background now reaches the workspace boundaries. The internal straight cutoffs from the capped bottom image are removed.
2. **Claims & Pickup — passed.** Narrow content remains centered; decoration now shares Reports' size and position.
3. **Profile — passed.** The account card and desk composition retain their layout; the atmosphere shares the workspace boundary rather than the 940px profile column.
4. **How It Works — passed.** Top artwork has the same width and anchor as the other pages. Bottom artwork remains at the end of the longer document and is therefore below the initial viewport, as intended.

Measured desktop artwork width is 1640.8 CSS px on all four routes, left edge 264px and top edge 88px. At a 900 × 900 tablet viewport, all four use 674.8px artwork and a 210px left edge. At 390 × 844, each uses a 339.2px clipped background container and the same 540px uniformly scaled decorative raster. Populated Claims at 320 × 844 has no horizontal overflow and retains 0.5 background opacity. Scroll width does not exceed client width on measured pages. The stable gutter can make scroll width smaller than client width on non-scrolling desktop pages.

Accepted screenshots and measured geometry are in [the evidence folder](shared-backgrounds-2026-11-25/). All four desktop captures and phone captures were opened and inspected; source/revised Claims and Profile were also opened together. Source account details differ from the read-only fixture's synthetic Student account. Saved screenshot dimensions can exclude scrollbar gutters; no pixel-equality claim is made.

Five-surface review: existing Montserrat/Nunito Sans typography and wrapping are retained, apart from the intentional scrollbar gutter allowance; content spacing and card widths are retained; existing color tokens and populated-state opacity are retained; the approved raster/mascots remain sharp and undistorted; product copy is unchanged. No P0/P1/P2 issue remains in this scoped background-consistency check. Screen-reader and system high-contrast testing were not repeated; decorative layers remain noninteractive and hidden from assistive technology, and existing forced-color/print rules remain.

All 40 existing frontend checks, all 38 route/state renders and `git diff --check` pass. Browser error log is empty. No backend/API, authentication, reporting, hardware, sandbox, dependency or JavaScript behavior changed. Earlier uncommitted refinements are preserved. No commit, push, merge or deployment.

final result: passed for shared background consistency
