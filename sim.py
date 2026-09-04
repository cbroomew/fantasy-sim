#!/usr/bin/env python3
"""
sim.py — Monte Carlo fantasy football matchup simulator.

Reads weekly projections from projections.csv, simulates the head-to-head
matchup N times (default 10,000), and reports win probability, projected
score ranges, and a start/sit verdict for the closest roster decision.

Every player gets his own fixed stream of random draws, so alternate lineups
are graded against the *same* simulated weeks (common random numbers). Only a
handful of weeks actually flip when you swap one flex player, which is why a
0.6-point win-probability edge can be reported with a real error bar instead
of being buried in sampling noise.

Usage:  python3 sim.py [--sims 10000] [--csv projections.csv] [--seed 1234]
"""

import argparse
import csv
import math
import random
import sys
import textwrap
from collections import OrderedDict

# ─── model ────────────────────────────────────────────────────────────────────

STARTING_SLOTS = ["QB", "RB1", "RB2", "WR1", "WR2", "TE", "FLEX", "K", "DST"]

# which lineup slots each position may legally fill
ELIGIBLE = {
    "QB":  ["QB"],
    "RB":  ["RB1", "RB2", "FLEX"],
    "WR":  ["WR1", "WR2", "FLEX"],
    "TE":  ["TE", "FLEX"],
    "K":   ["K"],
    "DST": ["DST"],
}


class Player:
    def __init__(self, row):
        self.team = row["fantasy_team"].strip()
        self.slot = row["slot"].strip()
        self.name = row["player"].strip()
        self.pos = row["pos"].strip()
        self.nfl = row["team"].strip()
        self.opp = row["opp"].strip()
        self.proj = float(row["proj"])
        self.std = float(row["std"])
        self.source = (row.get("source") or "").strip()

    @property
    def matchup(self):
        return "%s %s" % (self.nfl, self.opp)

    @property
    def cv(self):
        """Coefficient of variation — how boom/bust this player is."""
        return self.std / self.proj if self.proj else 0.0


def draw_samples(player, n, seed):
    """
    Simulate n weeks for one player.

    Skill positions use a lognormal matched to (proj, std): fantasy scoring is
    right-skewed — the floor is zero, the ceiling is a three-touchdown game.
    Kickers and defenses use a normal, since their range is tighter and roughly
    symmetric (defenses are allowed to go negative, because they do).
    """
    rng = random.Random(seed)
    m, s = player.proj, player.std

    if player.pos in ("K", "DST"):
        floor = -4.0 if player.pos == "DST" else 0.0
        return [max(floor, rng.gauss(m, s)) for _ in range(n)]

    sigma = math.sqrt(math.log(1.0 + (s / m) ** 2))
    mu = math.log(m) - 0.5 * sigma ** 2
    return [math.exp(rng.gauss(mu, sigma)) for _ in range(n)]


def total_scores(lineup, samples):
    """Week-by-week sum of the nine starters' sample streams."""
    return [sum(week) for week in zip(*[samples[p.name] for p in lineup.values()])]


def win_flags(a, b):
    """1.0 win / 0.5 tie / 0.0 loss, per simulated week."""
    return [1.0 if x > y else (0.5 if x == y else 0.0) for x, y in zip(a, b)]


def mean(xs):
    return sum(xs) / len(xs)


def paired_se(base, alt):
    """
    Standard error of the *difference* in win rate between two lineups.

    Because both lineups ran against identical weeks, the per-week differences
    are almost all exactly zero — so this error bar is far tighter than the
    error on either win probability on its own.
    """
    d = [x - y for x, y in zip(alt, base)]
    m = mean(d)
    var = sum((x - m) ** 2 for x in d) / (len(d) - 1)
    return math.sqrt(var / len(d))


def pct(sorted_vals, q):
    """Linear-interpolated percentile of an already-sorted list."""
    k = (len(sorted_vals) - 1) * (q / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


# ─── presentation ─────────────────────────────────────────────────────────────

W = 78                      # total output width
INNER = W - 4               # width inside the 2-space indent
BLOCKS = " ▁▂▃▄▅▆▇█"


def p(line=""):
    print(line.rstrip())


def pp(v):
    """Format a percentage-point value, keeping a second decimal when it matters."""
    return ("%+.2f" if abs(v) < 1.0 else "%+.1f") % v


def banner(text):
    p()
    p("  " + text)
    p("  " + "─" * INNER)


def bar(frac, width):
    filled = int(round(frac * width))
    return "█" * filled + "░" * (width - filled)


def histogram(values, lo, hi, bins, rows):
    """Multi-row vertical block histogram."""
    counts = [0] * bins
    span = hi - lo
    for v in values:
        if v < lo or v > hi:
            continue          # tails fall off the axis rather than piling up on it
        counts[min(int((v - lo) / span * bins), bins - 1)] += 1
    peak = max(counts) or 1
    eighths = [int(round(c / peak * rows * 8)) for c in counts]

    out = []
    for r in range(rows):
        base = (rows - 1 - r) * 8
        out.append("".join(BLOCKS[min(max(e - base, 0), 8)] for e in eighths))
    return out


def place(width, items):
    """Lay `items` of (position, text, align) onto a blank row of `width`."""
    row = [" "] * width
    for pos, text, align in items:
        start = pos if align == "l" else (pos - len(text) + 1 if align == "r"
                                          else pos - len(text) // 2)
        start = min(max(start, 0), width - len(text))
        for i, ch in enumerate(text):
            row[start + i] = ch
    return "".join(row)


def boxed(head, body_lines):
    """Heavy-ruled callout box, left-aligned, hard-wrapped to fit."""
    inner = INNER - 2
    p("  ┏" + "━" * inner + "┓")
    p("  ┃" + (" ▶  " + head).ljust(inner) + "┃")
    p("  ┃" + " " * inner + "┃")
    for line in body_lines:
        for wrapped in textwrap.wrap(line, inner - 6) or [""]:
            p("  ┃" + ("    " + wrapped).ljust(inner) + "┃")
    p("  ┗" + "━" * inner + "┛")


def print_lineups(name_a, lu_a, name_b, lu_b):
    half = 40

    def rows(lu):
        return ["%-4s %-18s %-10s %5.1f" % (s, lu[s].name[:18], lu[s].matchup, lu[s].proj)
                for s in STARTING_SLOTS]

    banner("STARTING LINEUPS")
    p("  %-*s  %-*s" % (half, name_a.upper(), half, name_b.upper()))
    p("  %-*s  %-*s" % (half, "─" * half, half, "─" * half))
    for ra, rb in zip(rows(lu_a), rows(lu_b)):
        p("  %-*s  %-*s" % (half, ra, half, rb))
    p("  %-*s  %-*s" % (half, "─" * half, half, "─" * half))
    tot = lambda lu: "%-33s %5.1f" % ("PROJECTED TOTAL", sum(x.proj for x in lu.values()))
    p("  %-*s  %-*s" % (half, tot(lu_a), half, tot(lu_b)))


# ─── start/sit analysis ───────────────────────────────────────────────────────

class Swap:
    """One legal bench-for-starter substitution, graded against the same weeks."""

    def __init__(self, team, slot, out_p, in_p, base_flags, alt_flags):
        self.team, self.slot, self.out, self.inn = team, slot, out_p, in_p
        self.wp_before = mean(base_flags)
        self.wp_after = mean(alt_flags)
        self.se = paired_se(base_flags, alt_flags)
        self.flipped = sum(1 for x, y in zip(base_flags, alt_flags) if x != y)

    @property
    def d_proj(self):
        return self.inn.proj - self.out.proj

    @property
    def d_wp(self):
        return self.wp_after - self.wp_before

    @property
    def significant(self):
        """Two standard errors clear of zero, and big enough to bother acting on."""
        return abs(self.d_wp) > 2 * self.se and abs(self.d_wp) * 100 >= 0.25


def evaluate_swaps(team, lineup, bench, opp_totals, samples, base_flags):
    out = []
    for cand in bench:
        for slot in ELIGIBLE.get(cand.pos, []):
            alt = OrderedDict(lineup)
            alt[slot] = cand
            alt_flags = win_flags(total_scores(alt, samples), opp_totals)
            out.append(Swap(team, slot, lineup[slot], cand, base_flags, alt_flags))
    return out


# ─── main ─────────────────────────────────────────────────────────────────────

def load(path):
    try:
        with open(path, newline="") as fh:
            return [Player(r) for r in csv.DictReader(fh)]
    except FileNotFoundError:
        sys.exit("error: could not find %s" % path)


def main():
    ap = argparse.ArgumentParser(description="Monte Carlo fantasy matchup simulator")
    ap.add_argument("--csv", default="projections.csv")
    ap.add_argument("--sims", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--week", default="Week 1, 2026")
    args = ap.parse_args()

    players = load(args.csv)
    teams = list(OrderedDict.fromkeys(x.team for x in players))
    if len(teams) != 2:
        sys.exit("error: expected exactly 2 fantasy teams in %s, found %d"
                 % (args.csv, len(teams)))
    name_a, name_b = teams

    lineups, benches = {}, {}
    for t in teams:
        roster = [x for x in players if x.team == t]
        lu = OrderedDict()
        for slot in STARTING_SLOTS:
            match = [x for x in roster if x.slot == slot]
            if len(match) != 1:
                sys.exit("error: %s needs exactly one player in slot %s (found %d)"
                         % (t, slot, len(match)))
            lu[slot] = match[0]
        lineups[t] = lu
        benches[t] = [x for x in roster if x.slot == "BN"]

    # One fixed random stream per player, so every lineup variant sees the same week.
    samples = {x.name: draw_samples(x, args.sims, args.seed + i)
               for i, x in enumerate(players)}

    tot_a = total_scores(lineups[name_a], samples)
    tot_b = total_scores(lineups[name_b], samples)
    flags_a = win_flags(tot_a, tot_b)
    flags_b = win_flags(tot_b, tot_a)
    wp_a, wp_b = mean(flags_a), mean(flags_b)
    margins = [x - y for x, y in zip(tot_a, tot_b)]
    sa, sb, sm = sorted(tot_a), sorted(tot_b), sorted(margins)

    # ── header ──
    p()
    p("┌" + "─" * (W - 2) + "┐")
    for line in ("MONTE CARLO MATCHUP SIMULATOR",
                 "%s   vs.   %s" % (name_a, name_b),
                 "%s simulations · %s" % (format(args.sims, ","), args.week)):
        p("│" + line.center(W - 2) + "│")
    p("└" + "─" * (W - 2) + "┘")

    print_lineups(name_a, lineups[name_a], name_b, lineups[name_b])

    # ── win probability ──
    banner("WIN PROBABILITY")
    for nm, wp in ((name_a, wp_a), (name_b, wp_b)):
        p("  %-21s %s  %5.1f%%" % (nm[:21], bar(wp, 42), wp * 100))
    fav = name_a if wp_a >= wp_b else name_b
    edge = abs(wp_a - wp_b) * 100
    tone = ("a dead heat" if edge < 4 else
            "a slight edge" if edge < 15 else
            "a comfortable edge" if edge < 35 else "a commanding edge")
    p()
    if edge < 4:
        p("  A dead heat — %s wins by just %.1f points on average."
          % (fav, abs(mean(margins))))
    else:
        p("  %s holds %s, winning by %.1f points on average."
          % (fav, tone, abs(mean(margins))))

    # ── score ranges ──
    banner("PROJECTED SCORE RANGES")
    p("  %-21s %7s %8s %16s %16s"
      % ("", "PROJ", "MEDIAN", "LIKELY 25–75%", "RANGE 5–95%"))
    for nm, vals, lu in ((name_a, sa, lineups[name_a]), (name_b, sb, lineups[name_b])):
        p("  %-21s %7.1f %8.1f %16s %16s" % (
            nm[:21], sum(x.proj for x in lu.values()), pct(vals, 50),
            "%.0f – %.0f" % (pct(vals, 25), pct(vals, 75)),
            "%.0f – %.0f" % (pct(vals, 5), pct(vals, 95))))

    # ── margin distribution ──
    banner("MARGIN OF VICTORY  (%s − %s)" % (name_a, name_b))
    lim = max(abs(pct(sm, 1)), abs(pct(sm, 99)))
    bins, zero = 44, 22
    for row in histogram(margins, -lim, lim, bins, rows=5):
        p("  " + row)
    p("  " + "".join("┼" if i == zero else "─" for i in range(bins)))
    p("  " + place(bins, [(0, "%+.0f" % -lim, "l"),
                          (zero, "TIE", "c"),
                          (bins - 1, "%+.0f" % lim, "r")]))
    close = sum(1 for m in margins if abs(m) <= 5) / len(margins)
    blow = sum(1 for m in margins if abs(m) > 30) / len(margins)
    p()
    p("  Decided by 5 points or fewer in %.0f%% of weeks · 30+ point blowout in %.0f%%."
      % (close * 100, blow * 100))

    # ── start / sit ──
    swaps = (evaluate_swaps(name_a, lineups[name_a], benches[name_a], tot_b, samples, flags_a)
             + evaluate_swaps(name_b, lineups[name_b], benches[name_b], tot_a, samples, flags_b))
    call = min(swaps, key=lambda s: (round(abs(s.d_proj), 2), -s.out.proj,
                                     s.team, s.slot, s.inn.name))

    banner("START / SIT VERDICT  —  closest call on the board")
    p("  %s · %s slot · the projections are %.1f point apart"
      % (call.team, call.slot, abs(call.d_proj)))
    p()
    p("  %-24s %6s %6s %7s %9s" % ("", "PROJ", "STD", "BOOM%", "WIN PROB"))
    for who, wp, tag in ((call.out, call.wp_before, "currently starting"),
                         (call.inn, call.wp_after, "on the bench")):
        boom = sum(1 for v in samples[who.name] if v >= who.proj * 1.5) / args.sims
        p("  %-24s %6.1f %6.1f %6.0f%% %8.1f%%   %s"
          % (who.name[:24], who.proj, who.std, boom * 100, wp * 100, tag))
    p()

    keep, swap_in = call.out, call.inn
    if call.significant:
        if call.d_wp > 0:
            head = "START %s" % swap_in.name.upper()
            body = ["Benching %s for %s is worth %s pp of win probability "
                    "(±%s pp)." % (keep.name, swap_in.name, pp(call.d_wp * 100),
                                   pp(2 * call.se * 100).lstrip("+"))]
        else:
            head = "STICK WITH %s" % keep.name.upper()
            body = ["Starting %s instead costs %s pp of win probability "
                    "(±%s pp)." % (swap_in.name, pp(abs(call.d_wp) * 100).lstrip("+"),
                                   pp(2 * call.se * 100).lstrip("+"))]
        body.append("The swap changes the result in %d of %s simulated weeks, and "
                    "the losses outnumber the gains." % (call.flipped, format(args.sims, ",")))
    else:
        head = "TRUE COIN FLIP — DEFAULT TO %s" % keep.name.upper()
        body = ["The gap is %s pp against an error bar of ±%s pp, so the "
                "simulation cannot separate them."
                % (pp(call.d_wp * 100), pp(2 * call.se * 100).lstrip("+")),
                "Break the tie on news, not math: whoever has the better late-week "
                "injury and weather report."]
    boxed(head, body)

    riskier = swap_in if swap_in.cv > keep.cv else keep
    steadier = keep if riskier is swap_in else swap_in
    if abs(swap_in.cv - keep.cv) < 0.03:
        why = ("Why: these two carry near-identical risk profiles (%.0f%% and %.0f%% "
               "coefficient of variation), so there is no ceiling-vs-floor tradeoff to "
               "exploit — the call rests on the %.1f-point projection edge alone, which "
               "moves %s from %.1f%% to %.1f%%."
               % (keep.cv * 100, swap_in.cv * 100, abs(call.d_proj), call.team,
                  call.wp_before * 100, call.wp_after * 100))
    else:
        why = ("Why: %s is the boom/bust side (%.0f%% coefficient of variation vs %.0f%% "
               "for %s). %s sits at %.1f%% to win, and moving to %s takes that to %.1f%% "
               "— the wider range %s its ceiling in a matchup this %s."
               % (riskier.name, riskier.cv * 100, steadier.cv * 100, steadier.name,
                  call.team, call.wp_before * 100, swap_in.name, call.wp_after * 100,
                  "earns" if call.d_wp > 0 else "does not earn",
                  "tight" if abs(call.wp_before - 0.5) < 0.1 else "lopsided"))
    p()
    for line in textwrap.wrap(why, INNER):
        p("  " + line)

    # ── the decision that actually matters ──
    best = max(swaps, key=lambda s: s.d_wp)
    if best is not call and best.d_wp > 0 and best.significant:
        banner("BIGGEST EDGE ON THE BOARD  —  points left on the bench")
        p("  %s · %s slot" % (best.team, best.slot))
        p()
        p("  %-24s %6s %6s %7s %9s" % ("", "PROJ", "STD", "BOOM%", "WIN PROB"))
        for who, wp, tag in ((best.out, best.wp_before, "currently starting"),
                             (best.inn, best.wp_after, "on the bench")):
            boom = sum(1 for v in samples[who.name] if v >= who.proj * 1.5) / args.sims
            p("  %-24s %6.1f %6.1f %6.0f%% %8.1f%%   %s"
              % (who.name[:24], who.proj, who.std, boom * 100, wp * 100, tag))
        p()
        boxed("START %s" % best.inn.name.upper(),
              ["Over %s, worth %s pp of win probability (±%s pp) — the single "
               "biggest gain available to either roster."
               % (best.out.name, pp(best.d_wp * 100), pp(2 * best.se * 100).lstrip("+")),
               "%s is projected %.1f points higher and swings %s of %s simulated "
               "weeks." % (best.inn.name, best.d_proj, format(best.flipped, ","),
                           format(args.sims, ","))])

    # ── runners-up ──
    others = sorted((s for s in swaps if s is not call and abs(s.d_proj) <= 2.5),
                    key=lambda s: abs(s.d_proj))[:4]
    if others:
        banner("OTHER CLOSE CALLS")
        p("  %-19s %-5s %-19s %-19s %7s"
          % ("TEAM", "SLOT", "STARTING", "ALTERNATIVE", "Δ WIN%"))
        for s in others:
            d = s.d_wp * 100
            p("  %-19s %-5s %-19s %-19s %+6.1f%s"
              % (s.team[:19], s.slot, s.out.name[:19], s.inn.name[:19],
                 0.0 if abs(d) < 0.05 else d, "*" if s.significant else " "))
        p()
        p("  * statistically separable at 2 standard errors; the rest are noise.")

    p()
    p("  " + "─" * INNER)
    p("  %s sims · seed %d · lognormal skill scoring · common random numbers"
      % (format(args.sims, ","), args.seed))
    tally = OrderedDict()
    for x in players:
        if x.source:
            tally[x.source] = tally.get(x.source, 0) + 1
    if tally:
        p("  projections: " + " · ".join("%d %s" % (n, k) for k, n in tally.items())
          + "  (every number above is read from %s)" % args.csv)
    unverified = [x.name for x in players if x.source.upper().startswith("ESTIMATE")]
    if unverified:
        for line in textwrap.wrap(
                "! %d of these are UNVERIFIED ESTIMATES, not consensus data: %s."
                % (len(unverified), ", ".join(unverified)), INNER):
            p("  " + line)
    p()


if __name__ == "__main__":
    main()
