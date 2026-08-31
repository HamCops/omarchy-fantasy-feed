# Release checklist

This checklist separates repeatable repository checks from the compositor and
publication steps that require operator review.

## Automated gate

- [ ] Run `python3 -m compileall -q scripts`.
- [ ] Run `python3 scripts/feed.py --fixture fixtures/replays/demo.json` and
  inspect the reception, correction/void, negative rush, interception,
  catch-fumble, and two-point events.
- [ ] Run `omarchy plugin validate "$PWD"` from a clean checkout.
- [ ] Confirm `git diff --check` and a credential/cache scan are clean.

## Runtime gate

- [ ] Install from the committed local clone with
  `omarchy plugin add "file://$PWD" --enable --yes`.
- [ ] Confirm live, scheduled/final, demo, and stale-cache states.
- [ ] Confirm adaptive refresh decisions through IPC status for live, near/far
  kickoff, final/idle, and failure-backoff states, and that no refresh countdown
  appears in the UI. Confirm compact panel plus standalone window share one
  helper process.
- [ ] Confirm left click, middle-click refresh, pop-out, panel buttons, and every
  documented key.
- [ ] Confirm the header PPR/STD menu updates inline play scores and leaderboard
  sorting; confirm all four position filters, favorite
  persistence after shell restart, favorites-only feed filtering, and arbitrary
  multi-game selection shared by every view. Confirm player/team search narrows
  the leaderboard without changing favorite state.
- [ ] Confirm two monitors share one helper process while keeping independent
  panel selection/scroll.
- [ ] Check horizontal and vertical bars under two Omarchy themes for QML
  warnings, clipping, binding loops, and contrast.
- [ ] Confirm dense feed cards show full play text, annotate every scoring
  player once with the selected PPR/STD value, and retain lifecycle labels.
- [ ] Confirm structured stat deltas and favorite controls remain available on
  standalone leaderboard rows.
- [ ] Confirm newly discovered plays enter one at a time, favorite plays hold
  with a green `★`, scrolling away shows `NEW ↑` without jumping, and the
  button returns both feed surfaces to the live edge.
- [ ] Confirm compact game chips show matchup/score on line one and game
  status/remaining clock on line two at the smallest supported panel width.
- [ ] Confirm the My Players rail shows weekly PPR/STD totals, latest deltas,
  green/red pulses, and click-to-play navigation.
- [ ] Confirm favorite-team possession produces the amber `★ RZ` game-chip
  state and down-and-distance tooltip, then clears when possession changes.
- [ ] Exercise `OFF`, all-play, touchdown-only, 3+, and 6+ alert presets. Confirm
  hidden games stay quiet, Do Not Disturb is honored, and clicking a toast opens
  the exact favorite play. Restore `OFF` before capturing submission media.
- [ ] Disable and remove the plugin, confirming no helper remains.

## Preview capture

1. Install the committed plugin under Omarchy and switch to the bundled demo.
2. Use a horizontal bar and open the panel at a size that shows the reception
   and reviewed/voided play together; retain enough desktop context to prove it
   is running inside Omarchy.
3. Use the active Omarchy screenshot command under the compositor. Do not
   render HTML, generate a mockup, or composite provider/team artwork.
4. Crop only empty desktop space, preserve the bar and panel relationship, and
   check text at repository-preview scale.
5. Capture the standalone leaderboard as a second proof image if competition
   rules permit more than one preview.
6. Save the approved capture as `preview.png`, update the README preview slot
   to embed it, and verify that no private notification or account data appears.

## Publication gate

- [ ] Review current marketplace or competition rules and permitted provider
  use before submission.
- [ ] Have the operator approve `preview.png`, repository metadata, and
  submission copy.
- [ ] Replace the generic install URL only after the public repository exists.
- [ ] Repeat the automated and runtime gates from a clean checkout.
- [ ] Tag the release only after every release gate passes.
