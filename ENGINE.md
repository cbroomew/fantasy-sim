# ENGINE.md

Technical specification and self-audit of the Monte Carlo engine behind
`sim.py` and `index.html`.

This document exists to make the model's weaknesses legible. Every number in it
was measured against the shipped code and the shipped `projections.csv`, not
asserted from intuition — the commands are given so you can re-run them. Where
the model is wrong, the section says so and estimates the size of the error.
The last section lists, for each design choice, the specific evidence that
would overturn it.

**Summary judgement up front:** the *statistical machinery* is sound and
measurably calibrated. The *distributional assumptions* are not validated
against real game logs, and at least one of them — the absence of any
zero-score mass — is demonstrably wrong in a way that biases the model toward
overconfidence. Treat the win probabilities as well-computed answers to a
somewhat idealised question.

---

## 1. What the engine computes

Given two nine-slot fantasy lineups and a per-player `(proj, std)`, it
estimates:

- P(team A beats team B) this week
- the distribution of each team's score, and of the margin
- for every legal bench-for-starter substitution, the change in win
  probability, with an error bar
- a verdict on the closest such decision, which refuses to commit when the
  change is inside the error bar

Everything is single-week. There is no season context, no playoff leverage, no
opponent modelling, no waiver or trade logic.

## 2. Pipeline

```
roster (CSV)
  └─ per player: draw N scores from a fixed, player-specific random stream
      └─ sum the nine starting slots per team          → team totals
          ├─ compare totals week by week               → win probability
          ├─ sort totals                               → percentiles, ranges
          ├─ difference totals                         → margin distribution
          └─ for each legal swap:
               alt = base − out + in                   → paired delta + SE
                 └─ significance test                  → verdict or coin flip
```

The default is N = 10,000. Cost is ~28 × N draws plus ~24 × N additions.

---

## 3. Distribution choices

### 3.1 Skill positions (QB/RB/WR/TE): lognormal

A lognormal matched by moments to the projection and its standard deviation:

```
sigma = sqrt(ln(1 + (std/proj)^2))
mu    = ln(proj) − sigma^2 / 2
score = exp(mu + sigma·Z),   Z ~ N(0,1)
```

**Why.** Weekly fantasy scoring is bounded below by zero and unbounded above:
the floor is a quiet game, the ceiling is three touchdowns. A normal
distribution matched to the same moments puts real probability mass below zero
— for a 14.3-point receiver with std 7.4 that is a 2.7% chance of a *negative*
score, which is impossible for a skill position. The lognormal is the simplest
two-parameter family that is positive, right-skewed, and closes in form under
moment matching.

**What it gets right.** The boom side looks reasonable. The model's implied
P(score > 1.5 × projection) sits at 13–14% for RB/WR/TE starters and 7.7% for
the two quarterbacks, which is in the range most people would accept for a
"he went off" week.

**What it gets wrong — the important one.** The lognormal assigns essentially
zero probability to a zero-ish game:

| player | proj | std | P(<1 pt) | P(<5 pts) |
|---|---|---|---|---|
| Josh Allen | 19.5 | 6.4 | 0.000% | 0.00% |
| Ja'Marr Chase | 20.0 | 10.4 | 0.000% | 0.48% |
| Jahmyr Gibbs | 22.1 | 10.6 | 0.000% | 0.12% |
| Brock Bowers | 15.1 | 7.9 | 0.000% | 2.27% |
| Garrett Wilson | 14.3 | 7.4 | 0.000% | 2.78% |

Mean across the fourteen skill starters: **P(<1 point) = 0.0000%**,
**P(<5 points) = 0.99%**.

Reality is not like this. A starter is inactive, ruled out pre-game, exits on
the first series, or is game-scripted into two touches several percent of weeks
— call it 3–6% for the "essentially nothing" outcome alone. The model says it
never happens.

**Consequence.** The left tail is too thin. The engine understates the chance
of a lopsided loss, understates how often a projection collapses, and therefore
*overstates its own confidence*. For start/sit specifically it cannot represent
the single most common real reason one option beats another — that the other
one didn't play.

The honest fix is a zero-inflated mixture: with probability `p_out` the player
scores ~0, otherwise draw from the lognormal, with the lognormal re-centred so
the blend still matches `proj`. That needs a per-player `p_out`, which needs
data the CSV does not carry. It is not implemented.

Reproduce: `python3 -c` block in §11.

### 3.2 Kickers and defenses: normal, hard-floored

```
score = max(floor, proj + std·Z)      floor = 0 for K, −4 for DST
```

**Why.** Their ranges are tighter and closer to symmetric than skill positions,
and defenses genuinely can go negative, so a positive-only family is wrong for
them.

**What it gets wrong.** `max()` is not a truncation, it is a *clamp*: all the
mass below the floor piles onto a single point.

| unit | proj | std | floor | mass on the floor |
|---|---|---|---|---|
| Brandon Aubrey (K) | 8.3 | 3.7 | 0.0 | 1.24% |
| Jake Bates (K) | 8.2 | 3.7 | 0.0 | 1.33% |
| Browns D/ST | 6.0 | 4.2 | −4.0 | 0.86% |
| Steelers D/ST | 7.1 | 5.0 | −4.0 | 1.32% |

So roughly 1% of kicker weeks come back as *exactly* 0.00 and 1% of defense
weeks as *exactly* −4.00. That is an artifact of the clamp, not a claim about
football. It also means the fitted mean is slightly above `proj`, since mass is
moved up rather than discarded.

Separately, defenses are strongly right-skewed in reality — a defensive
touchdown is a large, rare jump — and a symmetric normal cannot represent that.

### 3.3 The standard deviations are not data

`std` is a **modelling parameter**, not a published quantity. No projection
source publishes a spread. The shipped values are position-level coefficients
of variation applied to each projection:

| pos | CV | pos | CV |
|---|---|---|---|
| QB | 0.33 | TE | 0.52 |
| RB | 0.48 | K | 0.45 |
| WR | 0.52 | DST | 0.70 |

The consequence is structural: **two players at the same position with the same
projection are identical to the model.** A touchdown-dependent deep threat and
a high-volume possession receiver get the same distribution. The report detects
this case and says so rather than inventing a distinction — when the featured
call is between two same-position players it prints "near-identical risk
profiles … the call rests on the projection edge alone" — but detecting the
degeneracy is not the same as fixing it.

---

## 4. Paired comparison and common random numbers

Each player gets a random stream keyed to `seed + index·7919`, fixed for the
run. Two consequences follow.

**The swap identity.** A substitution changes exactly one slot, so

```
alt_total[i] = base_total[i] − out[i] + in[i]
```

The other eight starters are bit-identical in every simulated week. This is
~9× less arithmetic than re-summing the lineup (240k additions instead of
2.16M for 24 swaps at N=10,000), but the speed is the lesser benefit.

**The variance reduction.** Because the comparison is paired, most weeks
produce a delta of exactly zero and contribute nothing to the variance. Only
weeks where the swap actually flips the result matter.

| estimator | SE of the delta at N=10,000 |
|---|---|
| paired, common random numbers (what we do) | **0.278 pp** |
| unpaired, two independent runs | 0.707 pp |

That is a **6.4× variance reduction**. An unpaired design would need
**64,479** simulations to match the precision of 10,000 paired ones.

## 5. Error bars, and whether they are honest

For a swap, the per-week difference in outcome is
`d_i = winflag_alt(i) − winflag_base(i)`, taking values in {−1, −0.5, 0, +0.5, +1}.
The reported bar is `2 · SE` where `SE = sd(d) / sqrt(N)`, using the sample
(N−1) variance.

**This was tested, not assumed.** Running the featured call 150 times at
N=10,000 with independent seeds:

| quantity | value |
|---|---|
| true spread of the estimate (empirical SD over 150 runs) | 0.280 pp |
| mean SE the report claims | 0.278 pp |
| **claimed / true** | **0.99** |

The error bar is calibrated. When the report says ±0.56 pp, that is the real
uncertainty of the estimate, not a decoration.

Note what this does and does not establish. It shows the engine correctly
quantifies its *Monte Carlo* uncertainty — how much the answer would wobble if
you re-ran it. It says nothing about whether the underlying model is right.
A precisely-computed answer to the wrong question is still wrong, and §3.1 is
the wrong question.

### 5.1 The significance rule, and its two arbitrary constants

```
significant  ⟺  |delta| > 2·SE   AND   |delta|·100 ≥ 0.25
```

Both thresholds are choices, not derivations:

- **2·SE** is roughly a 95% two-sided interval. Conventional, but conventional
  is not principled.
- **0.25 pp** is a practical-relevance floor with no justification beyond taste.
  It exists so that a huge simulation cannot certify a change too small to care
  about. The number is made up.

### 5.2 Multiple comparisons — an uncorrected flaw

The shipped matchup tests **24 swaps** per run. Every one is evaluated against
the same 2·SE threshold, with **no correction for multiple comparisons.**

At α ≈ 0.0455 per test, the expected number of swaps marked significant purely
by chance is **24 × 0.0455 ≈ 1.1 per run.**

This directly affects the `*` markers in the OTHER CLOSE CALLS table. On a
typical run you should expect about one starred row to be noise. The featured
verdict is less exposed — it is selected before the simulation is consulted
(§6), so it is a single pre-registered test rather than a winner picked from 24
— but the table is not, and it is not currently labelled as such.

A Holm or Benjamini–Hochberg correction across the 24 tests would fix this and
is not implemented.

## 6. Which decision gets featured

The featured call is the legal swap with the **smallest projection gap**, ties
broken by the starter's projection, then team, slot, and incoming player name.

Crucially, **this key never touches the simulation.** An earlier version broke
ties on simulated impact, and the featured decision flickered between two
equally-close calls depending on `--sims`, because the tiebreak key was itself
noisy. Selecting on the data you are about to test is a garden-of-forking-paths
error; selecting on the projections alone avoids it.

The BIGGEST EDGE section is different: it *is* selected by maximum simulated
gain, so it is subject to selection bias and should be read as "the best-looking
of 24" rather than as a pre-registered test.

---

## 7. Independence, and what it costs

Every player is drawn independently. There is no stack correlation, no
game-script coupling, no negative correlation between a player and an opposing
defense.

**The shipped matchup is not actually free of this.** Six starter-or-bench
pairs on a single roster are drawn from the same NFL game, and one of them is
a **starter–starter pair**: Jahmyr Gibbs (RB1) and Jake Bates (K), both Detroit
against New Orleans, both in Play Action Jackson's active lineup. A running
back and his own kicker are not independent — they share an offense.

Measured sensitivity, injecting a shared latent factor between exactly that
pair, at N=200,000 per row:

| ρ | Team B std | P(blowout >30) | win% A |
|---|---|---|---|
| 0.0 (shipped) | 23.67 | 35.51% | 50.04% |
| 0.2 | 24.00 | 35.85% | 50.04% |
| 0.4 | 24.31 | 36.20% | 50.02% |
| 0.6 | 24.61 | 36.54% | 50.09% |

**Read this carefully, because it cuts both ways.**

- For **head-to-head win probability**, independence is nearly harmless here:
  0.05 pp across the whole range. Correlation inflates a team's variance
  roughly symmetrically, and in a balanced matchup that mostly cancels.
- For **score ranges and blowout rates**, it is not harmless: +4% on team
  standard deviation and +1.0 pp on blowout probability from a single
  moderately-correlated pair.
- This is the *smallest interesting case*. A genuine QB + WR1 + WR2 stack, with
  three players sharing one offense at ρ ≈ 0.3–0.5, would move these numbers
  substantially further, and would matter most exactly when a manager is
  deliberately stacking to raise their ceiling — the situation where they most
  need the model to be right.

So: the independence assumption is defensible for the headline number on an
unstacked roster, and misleading for the distribution shape on a stacked one.
The report does not currently detect stacks or warn about them. It could — the
same-game pairs are computable from the `team` and `opp` columns already in
the CSV.

## 8. Data provenance

The engine computes only from the CSV. It holds no roster, no player database,
no fitted weights. This is deliberate: a language model's memory of rosters
goes stale the moment a trade happens, and keeping every fact in data means the
*code* cannot hallucinate one. It also means the CSV's defects are the model's
defects.

The shipped `projections.csv` is a **frozen snapshot verified 2026-09-04**. It
does not update. Its rows carry a `source` column:

| source | count | what it means |
|---|---|---|
| `consensus` | 18 | taken directly from a public Week 1 consensus table |
| `derived` | 6 | computed from a published full-season projection |
| `ESTIMATE-UNVERIFIED` | 4 | **no published number found — a reasoned placeholder** |

Three specific defects:

1. **Four projections are invented.** Kenneth Walker III, Browns D/ST, Kyren
   Williams and Malik Nabers had no retrievable Week 1 number (free tables cut
   off at the top ten; full tables are paywalled). Two of them — Browns D/ST
   and Kyren Williams — feed a starting lineup and a live bench alternative
   respectively, so they move the headline win probability.

2. **The six `derived` rows carry a systematic downward bias.** They were
   computed as season total ÷ 17. But published season projections already
   price in expected missed games. If a season line assumes 15 of 17 games, the
   true per-game rate is ~13% higher than season ÷ 17:

   | player | shipped | implied true rate at 15/17 games |
   |---|---|---|
   | Bo Nix | 17.5 | ~19.8 |
   | Garrett Wilson | 14.3 | ~16.2 |
   | Ladd McConkey | 12.8 | ~14.5 |
   | Rome Odunze | 12.1 | ~13.7 |
   | Xavier Worthy | 9.8 | ~11.1 |
   | Dalton Kincaid | 9.4 | ~10.7 |

   Garrett Wilson is a **starter** in the shipped lineup. This bias is not
   corrected, because the games-played assumption behind each season line was
   not published either.

3. **`std` is invented for every row** (§3.3), including the 18 `consensus`
   ones. The projections are sourced; their spreads are not.

Editing any row's numbers in the web app flips its `source` to `edited` and the
footer tally counts it, so the report stops claiming verified provenance over
figures a user typed.

## 9. Numerical details

- **PRNG.** `sim.py` uses Python's Mersenne Twister. `index.html` uses `sfc32`
  seeded through `splitmix32`, discarding the first 12 outputs. Normals come
  from the Marsaglia polar method in both.
- **These are not bit-identical.** The same seed produces different draws in
  each. At 800,000 sims the featured call converges to **−0.39 pp** in Python
  and **−0.355 ± 0.062 pp** in the browser — the same answer, different digits.
  `tools/parity.js` runs the browser core in Node for comparison and verifies
  the embedded roster still matches `projections.csv`.
- **Precision.** Player samples are `Float32Array`; team totals accumulate into
  `Float64Array`. Float32 is ample for values under ~100 with one decimal of
  meaning.
- **Ties.** A tie credits 0.5 to each side. In practice this never fires:
  **0 exact ties in 500,000 simulations.** The branch is defensive, not load-bearing.
- **Percentiles.** Linear interpolation on the sorted totals.
- **Histogram.** Bins span the 1st to 99th percentile of the margin; the ~2% of
  weeks outside that fall off the axis rather than piling into the end bins.
  This is a display choice and it makes the tails look thinner than they are.
- **Boom%.** Defined as P(score ≥ 1.5 × projection). The 1.5 is arbitrary.
- **Floor/ceiling.** The `10–90%` column on each lineup row is the 10th and 90th
  percentile of that player's own draws, taken by quickselect rather than a full
  sort, and rounded to whole points. It is empirical, not analytic, though the
  two agree: sampled and closed-form lognormal percentiles match to one decimal
  at 200,000 sims. Rounding means a floor shown as `9` is anywhere in [8.5, 9.5).
- **Close calls.** Swaps with |Δproj| ≤ 2.5, top four by projection gap. Both
  constants are arbitrary.

## 10. Two implementations

`sim.py` and `index.html` implement the same model in different languages. They
will drift; `tools/parity.js` detects drift but cannot prevent it. A bug fixed
in one does not reach the other. This is a real maintenance liability accepted
in exchange for a CLI that scripts and a web app that needs no install.

---

## 11. What would falsify each choice

Each row names the specific evidence that would overturn the design, and what
it would take to gather it. Most require the same input: **three or more
seasons of weekly per-player PPR game logs**, which the project does not
currently have.

| # | Design choice | What would falsify it | Predicted outcome |
|---|---|---|---|
| 1 | **Lognormal for skill positions** | Fit per-position lognormals to weekly game logs; compare empirical P(score < 1) against the model's ~0.000%. If the empirical rate exceeds ~1%, the un-inflated lognormal is falsified. | **Expected to fail.** Real starters zero out several percent of weeks. Fix: zero-inflated mixture with a per-player `p_out`. |
| 2 | **Position-level constant CV** | Compute per-player CV from game logs. If the interquartile range of CV within a position exceeds roughly ±0.10, the constant is hiding real variation. | **Expected to fail** for WR and TE, where touchdown dependence varies enormously between players. |
| 3 | **Normal for K/DST** | Test the skewness of empirical DST weekly scores. Skew > 0.5 falsifies symmetry. Also check what fraction of real DST weeks land below −4. | **Expected to fail** for DST — defensive touchdowns make the right tail fat. Kickers are probably fine. |
| 4 | **Player independence** | Compute empirical correlation between same-team QB–WR pairs, and RB–K pairs, in the same week. ρ > 0.15 falsifies independence for stacked rosters. | **Expected to fail** for QB–WR stacks. §7 shows the cost is small for win probability and material for score ranges. |
| 5 | **Paired SE is the true uncertainty** | Re-run the featured call many times at fixed N and compare the empirical SD of the estimate against the mean claimed SE. Ratio far from 1.0 falsifies it. | **Tested and passed: 0.99** (150 reps, N=10,000). Re-run after any change to the swap evaluator. |
| 6 | **Common random numbers help** | Compare paired SE against the unpaired two-run SE at equal N. A ratio near 1.0 would mean the pairing buys nothing. | **Tested and passed: 6.4× variance reduction.** |
| 7 | **The 2·SE + 0.25 pp significance rule** | Back-test: collect the engine's START/STICK recommendations across many real weeks, and check whether the recommended side actually wins the matchup at the predicted excess rate. | Untested. Requires a season of logged recommendations plus outcomes. |
| 8 | **The whole model's calibration** | Bucket predicted win probabilities into deciles across many real matchups and compare against realized frequencies. If the 60% bucket does not win ~60% of the time, the model is miscalibrated regardless of what any component test says. | **The master test. Entirely untested.** Everything above is a component check; this is the only one that validates the output people actually act on. |
| 9 | **Uncorrected multiple comparisons in the close-calls table** | Simulate matchups with all swaps genuinely null and count starred rows. Rate materially above zero confirms the flaw. | **Expected to confirm the flaw** at ~1.1 false stars per run (§5.2), by construction. |

### Commands

```bash
# error-bar calibration and the CRN gain (§4, §5)
node tools/parity.js 100000 1234
python3 sim.py --sims 100000

# convergence between the two implementations (§9)
node tools/parity.js 800000 1234
python3 sim.py --sims 800000
```

---

## 12. What this should not be used for

- **Betting or any wagering.** The left tail is wrong (§3.1), four inputs are
  invented (§8), and the output has never been calibration-tested against real
  outcomes (§11 row 8).
- **Decisions where a sub-1-pp edge matters.** The engine will report such
  edges with honest Monte Carlo error bars, but model error dwarfs simulation
  error and is not quantified anywhere.
- **Stacked rosters, for anything other than the headline win probability**
  (§7).
- **Any week other than the one in the CSV.** The bundled data is frozen at
  2026-09-04 and does not update itself.

What it is reasonable for: comparing two lineups you have honest projections
for, understanding how wide the plausible score range really is, and — most of
all — learning when a start/sit decision is genuinely too close to call. The
engine's most defensible output is the coin flip, because that is the one place
it declines to manufacture confidence it has not earned.
