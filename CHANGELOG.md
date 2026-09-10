# Changelog

All notable changes to Fantasy Feed are documented here.

## [1.1.0] - 2026-09-08 (HamCops fork)

- Parse plays ESPN wraps in extra text: a "reported in as eligible" preamble
  (which hid a passing touchdown), formation notes such as `(No Huddle,
  Shotgun)` on runs, runs and catches ending `ran ob at`, and stray
  whitespace. Parser version is now `espn-narrative-v2`, and a play rejected
  by an older parser is fetched and parsed again on the next refresh instead
  of staying hidden. A play first seen after such a retry arrives as
  `current`, not `corrected`.
- Add a points filter to the feed lists (`ALL` / `3+` / `6+` / `TD`, key `f`),
  beside the scoring menu in both the panel and the standalone window. Every
  carry and catch scores something, so the full feed is busy; the filter
  keeps plays worth at least that much to someone in the selected scoring, or
  touchdowns. Bar, rail, leaderboard, matchup totals and alerts still count
  every play. Persisted with the other settings.
- Acknowledge a clip click at once: the play flashes in the accent colour,
  pulses and reads `▶ OPENING…` for three seconds while mpv starts.
- Open Reddit-hosted clips through their DASH manifest instead of the HLS
  playlist: ffmpeg's HLS demuxer stops a few seconds into Reddit's byte-range
  CMAF segments, so clips ended early. Cached posts are rewritten on load.
- Only open highlight clips hosted on v.redd.it, streamable, x.com/twitter or
  YouTube over https. Any r/nfl poster could otherwise hand an arbitrary URL to
  mpv and yt-dlp; such posts are now dropped instead of matched.
- Watch the favorites file so an external league sync applies live, and keep
  the `side`, `slot` and `league` fields it writes.
- Add league scoring: `points.league` on every play and weekly total, from the
  synced rules, with ESPN's floor-bucket yardage honoured in weekly totals.
- Add a `LEAGUE` scoring mode to both scoring menus and the `p` cycle.
- Show the head-to-head in the bar (`ME 41.2 – 37.9 TM2`), preferring ESPN's
  live totals from `~/.cache/fantasy-feed/league.json` when fresh.
- Split the My Players rail into my starters and the opponent's; opponent
  gains pulse red; chips show lineup slots.
- Add a `⚔ MATCHUP` tab (key `4`) to the standalone window with both lineups.
- Headline opponent-player alerts with `⚔ OPP`.
- Match plays to r/nfl `[Highlight]` posts (Atom feed, throttled, cached);
  badge them `▶ CLIP`, open in mpv on click or `Enter`/`v`, and send one
  follow-up alert per clip for plays the alert policy covers.

## [1.0.1] - 2026-08-30

- Keep the submitted plugin tree production-only while retaining the small
  deterministic fixture required by the user-facing offline Demo mode.
- Preserve development and load-testing assets on the separate development
  branch.

## [1.0.0] - 2026-08-30

- Follow fantasy-relevant NFL plays across an arbitrary game selection.
- Insert the selected PPR or standard score beside each affected player in the
  original play sentence.
- Add a sortable weekly QB/RB/WR/TE leaderboard with player and team search.
- Add persistent favorites, a My Players pulse rail, and a favorites-only feed.
- Add favorite-player desktop alerts with all-play, touchdown, three-point, and
  six-point policies.
- Highlight favorite-team red-zone possessions and expose down-and-distance.
- Stage multi-game arrivals into a readable live tape with independent scroll
  position on every surface.
- Add a normal tileable standalone window, adaptive polling, last-good caching,
  correction/void handling, and system-local kickoff times.

[1.0.1]: https://github.com/studioxvii/omarchy-fantasy-feed/releases/tag/v1.0.1
[1.0.0]: https://github.com/studioxvii/omarchy-fantasy-feed/releases/tag/v1.0.0
