# fantasy-sim

A Monte Carlo head-to-head fantasy football simulator. It reads a CSV of weekly
projections, plays the matchup 10,000 times, and prints win probability,
projected score ranges, and a start/sit verdict with a real error bar.

```bash
python3 sim.py
```

No dependencies — Python 3 standard library only. No install step, no virtualenv.

> **The bundled `projections.csv` is a frozen snapshot, not live data.** It holds
> a sample Week 1 2026 matchup verified on 2026-09-04 and it never updates
> itself. Anyone reading this after that date is looking at historical numbers,
> and four of its rows are unverified estimates (see
> [The four unverified rows](#the-four-unverified-rows)). It exists to
> demonstrate the format — replace it with your own league's projections before
> drawing any conclusion from the output.

## What it does

For each simulated week it draws a score for every starter, sums the nine
starting slots, and compares the two totals.

- **Skill positions** (QB/RB/WR/TE) draw from a **lognormal** matched to each
  player's `proj` and `std`. Weekly fantasy scoring is right-skewed: the floor is
  zero and the ceiling is a three-touchdown game. A normal distribution would put
  real mass below zero and understate the ceiling.
- **K and DST** draw from a normal, since their range is tighter and roughly
  symmetric. DST is allowed to go negative, because it does.

Every player gets his **own fixed stream of random draws**, so alternate lineups
are graded against the *same* simulated weeks. This is the standard variance
reduction trick (common random numbers), and it is what makes the start/sit
section trustworthy: when you swap one flex player, the other eight starters are
bit-for-bit identical in every week, so the win-probability difference is a
*paired* comparison. The report prints a 2-standard-error bar on that difference
and marks a call as decided only when it clears the bar. Calls that don't clear
it are labelled a coin flip rather than dressed up as insight.

## It computes only from the CSV

`sim.py` reads player names, teams, opponents, projections and standard
deviations **exclusively from the CSV**. It contains no player database, no
hardcoded rosters, and no model weights. Point it at a file listing players who
retired a decade ago and it will happily simulate them.

This matters because the program was written with AI assistance, and a language
model's memory of NFL rosters goes stale the moment a trade happens — it has a
training cutoff and no awareness of what changed after it. Keeping every fact in
the CSV means **the code cannot hallucinate a roster**: there is nothing for it
to remember incorrectly. If a player is on the wrong team in the output, the CSV
is wrong, and you fix it by editing one line of data rather than auditing code.

The tradeoff is that the CSV's accuracy is entirely on whoever maintains it.

### About the bundled `projections.csv`

The included file is a **sample**, not a live feed. It is a Week 1 2026 matchup
between two invented teams, and the numbers were checked against public sources
on **2026-09-04**. It does not update itself. The `source` column records where
each projection came from, and the simulator prints a tally of these in its
footer:

| `source` | meaning |
| --- | --- |
| `consensus` | Week 1 consensus projection taken directly from a public projection table |
| `derived` | computed from a published full-season projection (converted to PPR, divided by 17) |
| `ESTIMATE-UNVERIFIED` | no published number found; a reasoned placeholder — **do not trust it** |

The `note` column records the specific provenance of every row, including why
each estimate could not be verified.

#### The four unverified rows

These projections are **not sourced from anything**. Free projection tables cut
off at the top ten and full tables are paywalled, so no published Week 1 number
could be found for them. They are my own reasoned placeholders, and they are the
first thing to replace if you use this file for anything real:

| player | value used | why it is unverified |
| --- | --- | --- |
| Kenneth Walker III | 14.0 | No Week 1 or season projection found after his free-agency move to KC. Placeholder for a lead back. |
| Browns D/ST | 6.0 | Fell outside the published top-10 DST table; set just below the 7.1 that ranked tenth. |
| Kyren Williams | 14.2 | Season total was published in standard scoring only. Receptions unavailable, so ~40 were assumed to convert to PPR. |
| Malik Nabers | 13.8 | Same standard-scoring problem, ~75 receptions assumed. Separately, he is returning from a torn ACL, which makes any projection for him unusually soft. |

Two of the four (Walker, Nabers) sit on benches and only matter to the start/sit
section; the Browns D/ST and Kyren Williams estimates feed a starting lineup and
a bench alternative respectively, so they move the headline win probability.

`sim.py` prints a tally of the `source` column in its footer and names the
unverified players explicitly, so the caveat travels with the output rather than
living only in this file.

Player-team pairings and all Week 1 opponents **were** verified, against the
published 2026 Week 1 schedule. Replace the file with your own league's numbers
and the `source` and `note` columns can be dropped or repurposed; both are
optional.

## CSV format

One row per player. Nine starters (`QB`, `RB1`, `RB2`, `WR1`, `WR2`, `TE`,
`FLEX`, `K`, `DST`) plus any number of bench players per team, and exactly two
teams in the file.

| column | meaning |
| --- | --- |
| `fantasy_team` | Team name. Exactly two distinct values in the file. |
| `slot` | `QB`, `RB1`, `RB2`, `WR1`, `WR2`, `TE`, `FLEX`, `K`, `DST`, or `BN` for bench. Each starting slot must appear exactly once per team. |
| `player` | Display name. |
| `pos` | `QB`, `RB`, `WR`, `TE`, `K`, or `DST`. Drives both the scoring distribution and which slots the player may fill. |
| `team` | NFL team abbreviation, e.g. `BUF`. Display only. |
| `opp` | Opponent as you want it shown, e.g. `@HOU` or `vs TB`. Display only. |
| `proj` | Projected fantasy points. The mean of the player's distribution. |
| `std` | Standard deviation of that projection — see below. |
| `source` | Optional. Free-text provenance label, tallied in the footer. A value starting with `ESTIMATE` also triggers a named warning line under the tally. |
| `note` | Optional. Free-text provenance detail. Never parsed by the simulator. |

Flex eligibility: `RB`, `WR` and `TE` may fill `FLEX`. `QB`, `K` and `DST` may
only fill their own slot.

### Choosing `std`

`std` is a **modelling parameter, not projection data** — public sources publish
a mean, not a spread. In the bundled file it is derived from position-typical
coefficients of variation:

| position | CV | e.g. a 15-point projection |
| --- | --- | --- |
| QB | 0.33 | ±5.0 |
| RB | 0.48 | ±7.2 |
| WR | 0.52 | ±7.8 |
| TE | 0.52 | ±7.8 |
| K | 0.45 | ±6.8 |
| DST | 0.70 | ±10.5 |

If you have per-player game logs, use the real spread instead — a
touchdown-dependent deep threat and a high-volume possession receiver can share a
projection while having very different weekly shapes.

## Flags

| flag | default | what it does |
| --- | --- | --- |
| `--sims N` | `10000` | Number of simulated weeks. Raise it to tighten the error bar on close start/sit calls; 400,000 runs in a few seconds. |
| `--seed N` | `1234` | Random seed. Output is fully reproducible for a given seed, so the same CSV always gives the same numbers. Change it to confirm a marginal verdict isn't an artefact of one seed. |
| `--csv PATH` | `projections.csv` | Which projections file to read. |
| `--week TEXT` | `Week 1, 2026` | Label printed in the header. Cosmetic only — it does not select or filter any data. |

```bash
python3 sim.py --csv my-league-week3.csv --week "Week 3, 2026" --sims 100000
```

## Reading the start/sit section

The report features the **closest call on the board** — the legal bench-for-starter
swap with the smallest projection gap. That selection is deliberately independent
of the simulation (ties break on the starter's projection, not on simulated
impact) so the featured decision doesn't flicker between runs.

A verdict is only stated as decided when the win-probability change clears two
standard errors. Borderline effects genuinely can land on either side of that
line at low `--sims`; if a call matters to you, re-run it with `--sims 400000`
and a couple of different `--seed` values before trusting it.

## Known limitations

- **Player scores are independent.** There is no correlation between a QB and his
  own receivers, and no game-script coupling. Stacks will read as
  lower-variance than they really are, and a player facing your own defense
  won't show the negative correlation he should.
- **Variance is modelled per position, not per player.** Two players at the same
  position with the same projection are statistically identical to the model, so
  the ceiling-vs-floor reasoning has nothing to work with in that case. The
  report detects this and says so rather than inventing a distinction.
- **One swap at a time.** The start/sit search evaluates single substitutions,
  not the jointly optimal lineup.
- **No in-game state**, injuries, weather, or late-breaking news. The CSV is the
  whole world.
