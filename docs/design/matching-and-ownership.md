# Matching and ownership verification

The previous category filter excluded valid finds before ranking. A fixed top three hid plausible alternatives. The owner response showed a numerical rank and reused the model's summary. The purple iPhone summary disclosed the cracked front and back, and the claim counted both cracks as one because they shared a detail type. The old 60/40 rule also let search relevance contribute directly to a pickup decision.

## Decisions

1. Retrieve stored items across categories within a seven-day allowance before the reported loss. Rank using category families, item attributes, time, location and optional text similarity. Unknown signals are neutral. Downweight common observations and uncertain visual estimates. Display five results per page and only allowlisted candidate fields. Start with the existing provider and current database. A calibrated record-linkage model needs representative labels and an evaluation set first.
2. Capture the finder's photos and review broad facts before reserving a locker. Keep uncertain observations internal and preserve the original photos. The owner can still be served when photo analysis fails. A failed provider call is visible and can be retried.
3. Save the owner's initial description and optional distinguishing details before showing candidates. Check those details against the original finder photos. Require independent features on identifiable parts or components. Repeating a feature adds no evidence. Search rank cannot authorize a pickup.
4. The backend issues pickup codes only for sufficient evidence or an authorized documented decision. Where the identifier is readable, an operator can compare it to an older record. A supervised device check can use a fresh message displayed on the actual device. The locker has no trusted screen-reading channel. The app never requests credentials or unlock codes.
5. Unresolved claims go to an authorized operator. For low-value, low-risk items an operator may complete a documented face-to-face handover after assessing competing claims. Identity records the recipient and by itself does not establish ownership. A competing unresolved claim blocks this exception. Identical goods with competing claims stay in storage until corroboration or the site's retention procedure. The operator handles physical access separately from an owner pickup code.

## Acceptance scenarios

| # | Find and claim | Expected |
| --- | --- | --- |
| 1 | Purple iPhone with front and back damage | Distinct, undisclosed details on both parts can qualify. Repeating one crack cannot. |
| 2 | Pristine black iPhone | An identifying record or supervised device proof can resolve it. Common description alone yields no code. |
| 3 | Identical black caps | All plausible caps can surface. No automatic code. An authorized operator may document a face-to-face handover when there is no competing claim. |
| 4 | Keys with sparse photos | Tell the owner how to seek operator help if no distinct features can be compared. |
| 5 | Headphones with full serial | Operator compares the device to an independent dated record. A number typed by itself yields no code. |
| 6 | Backpack with few details | A single characteristic feature can prompt the next feasible proof. Normal color and size cannot authorize pickup. |
| 7 | Matching find in wrong category | Still retrieved and ranked using the other evidence. |
| 8 | Blur or missing attributes | Unknown fields stay neutral. Unreadable photos neither confirm nor contradict. |
| 9 | Impostor reusing public fields | No code. Repeated guesses limited. |
| 10 | Two people claiming one item | No second active pickup authorization. Competing unresolved claims require operator handling. |

## Ranking and release rules

- Candidate retrieval starts from physically stored items. A known loss date allows finds up to
  seven days earlier. An unknown date leaves the retrieval window open. A candidate is excluded
  for an observed category conflict only when text similarity also indicates a mismatch and the
  structured attributes give no positive support.
- Ranking combines category family, location, time, structured fields and text similarity.
  Missing values are neutral. Estimates have reduced influence. Color contributes less than model
  and brand, and common colors receive less weight in a sufficiently sized candidate pool. The
  owner sees a ranked page of five and can load more.
- Verification uses the original finder photos and immutable owner statements. A visual
  authorization can use one clearly confirmed, highly specific feature described before seeing
  the candidate. Otherwise two independently confirmed distinctive parts can qualify, including
  one documented before seeing the candidate. Repeated
  descriptions of one mark, ordinary colors or branding, guesses and unobservable parts add no
  proof. The model must quote the owner's statement and identify the supporting photo. The
  backend validates this structure and issues the code using its existing locker transaction.
- Clear contradictions without corroboration can refute a claim. A contradiction alongside
  credible positive evidence goes to review. A documented device record is a feasible route when
  photos are sparse. Implausible or absent image responses cannot authorize release. The data
  migration flags older candidates whose text may have been exposed for operator review.
- New claims are limited by item and claimant. A photo check from one account cannot issue a
  second pickup code for a report with an existing authorization. Competing claims for an item
  go to review if they arrive before release. Any successful release closes other pending claims
  for the item. Reports and submitted statements are retained, including prior attempts.

## Operator procedure

1. Locate the claim number in the admin queue. Check whether another person claimed the same item.
2. Compare a readable device identifier against a dated record or confirm control on the actual
   physical device. For a device in a supported lost mode the operator can supply a fresh,
   unpredictable phrase and observe it on the device. Availability depends on device options,
   account setup and connectivity. The operator records which check was performed and why
   it supports ownership. Never ask for sign-in credentials or an unlock code.
3. For a verified ownership claim, authorize pickup in the admin queue. The owner can then request
   a code. For a genuinely low-risk and low-value cap, bottle, umbrella, or book with no competing
   claim, use the site operator's physical access to hand over the item in person. Record the
   recipient account and the disposition. Keep identity documents and credentials out of notes.
4. Record a supervised handover only after physically removing and handing over the item. A handover
   marks the report resolved, clears available access codes and records the operator. It issues no
   owner code.
5. When two claims remain credible and no independent evidence exists, retain the item under the
   site's retention procedure. Each site needs a staffed contact and physical operator access.

Apple and Google document an owner-controlled lost-mode message, which supports an attended
device check where available. PrivateFind has no way to read the phone screen in a closed locker.
[Apple Find Devices](https://support.apple.com/en-ca/guide/icloud/-mmfc0f0165/icloud)
[Google Find Hub](https://support.google.com/android/answer/6160491?hl=en)

## Test strategy and remaining limits

The ranking fixture contains 15 finds, including near-matches and identical items. It exercises
the existing provider interface with controlled text comparisons. The verification tests cover
positive photo evidence, guesses, poor photos, a typed serial, an independently reviewed device
record, old data, and competing claims. The device simulation exercises the actual backend code
validation and occupancy API. It covers deposit, code authorization, pickup and compartment
release. The browser run uses an iPhone viewport, an isolated MySQL 8.4 database and a deterministic
visual fixture. Migration tests exercise existing rows, upgrade, downgrade and re-upgrade.

These tests measure software behavior on known cases. They cannot establish the false-release
rate of a generative vision model in deployment. Live Qwen, a physical ESP32 and servo, and a
pilot with owners remain separate checks. Measure completed legitimate returns, wrong releases,
unresolved claims, abandonment and elapsed time with actual owners. Keep the report, model
assessment and release outcomes separate when measuring them.

### Recorded results

| Check | Result |
|---|---|
| Backend test suite | 104 passed |
| Target ranks by scenario 1–8 | 1, 2, 5, 1, 1, 1, 1, 1 |
| Recall at 3 and 5 on the fixture | 7/8 and 8/8 |
| MySQL 8.4 migration | Upgrade, old summary backfill, downgrade and re-upgrade passed |
| Simulated pickup with mobile browser | Deposit, positive claim, code validation and compartment release passed |
| Operator review in browser | Signed-in operator recorded an independent check and authorized pickup. |
| Concurrent requests in MySQL | Two accounts tried simultaneously. Exactly one request received a pickup code. |
| Live Qwen | Configured hostnames did not resolve. The known Tailscale IP timed out. |

The indistinguishable cap at rank five could not be identified from its description. The
automation tests issued no codes for the specified impostor, unobservable-photo and typed-serial
cases. These are fixture results. No live estimates of legitimate return rate, false-release rate,
abandonment or time are available.

The current ranking uses the existing database and text provider. [Splink term-frequency
adjustments](https://moj-analytical-services.github.io/splink/topic_guides/comparisons/term-frequency.html)
are worth evaluating with a representative catalog and labeled pairs. Collecting independent
ownership outcomes remains a separate part of the evaluation.
