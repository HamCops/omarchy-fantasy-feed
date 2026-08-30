# Release checklist

This checklist separates repeatable repository checks from the compositor and
publication steps that require operator review.

## Automated gate

- [ ] Run `python3 -m compileall -q scripts tests`.
- [ ] Run `python3 -m unittest discover -s tests -v`.
- [ ] Run `python3 scripts/feed.py --fixture fixtures/replays/demo.json` and
  inspect the reception, correction/void, negative rush, interception,
  catch-fumble, and two-point events.
- [ ] Run `omarchy plugin validate "$PWD"` from a clean checkout.
- [ ] Confirm `git diff --check` and a credential/cache scan are clean.

## Runtime gate

- [ ] Install from the committed local clone with
  `omarchy plugin add "file://$PWD" --enable --yes`.
- [ ] Confirm live, scheduled/final, demo, and stale-cache states.
- [ ] Confirm the adaptive refresh countdown for live, near/far kickoff,
  final/idle, and failure-backoff states, and that compact panel plus standalone
  window share one helper process.
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

- [ ] Confirm a new competition has opened and review its current rules and
  permitted provider use; this repository assumes no submission URL.
- [ ] Have the operator approve `preview.png`, repository metadata, and
  submission copy.
- [ ] Replace the generic install URL only after the public repository exists.
- [ ] Repeat the automated and runtime gates from a clean checkout.
- [ ] Tag `v0.3.4` only after every release gate passes.
