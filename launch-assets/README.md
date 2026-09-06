# launch-assets

PNG sticker cards for overlaying on 9:16 vertical video (CapCut etc.).

Regenerate with:

```bash
python3 launch-assets/render_cards.py
```

`render_cards.py` shells out to `sim.py` and slices the cards out of **real
stdout captured at render time**, so a card can never drift from what the
simulator actually prints. Change the CSV or the code, re-run, and the cards
follow.

| file | contents | from |
| --- | --- | --- |
| `01-title.png` | Title header | default run |
| `02-win-probability.png` | Win probability bars + summary line | default run |
| `03-verdict-stick-with.png` | `STICK WITH JAYDEN DANIELS` verdict | default run |
| `04-verdict-coin-flip.png` | `TRUE COIN FLIP` verdict | `--seed 7` |
| `05-footer-warning.png` | Footer + unverified-estimate warning | default run |
| `06-full-report.png` | The entire report | default run |

All are RGBA with transparent corners, `#0d0d0d` ground, Menlo, ≥1080px wide.

## Two things to know before using these

**`04-verdict-coin-flip.png` comes from `--seed 7`, not the default seed.** That
verdict is real output, but the headline call in this matchup is genuinely
borderline — about `-0.4 pp` against an error bar of similar size. The default
seed (1234) lands just past the significance threshold and prints
`STICK WITH JAYDEN DANIELS`; seeds 1, 7 and 99 land just short and print
`TRUE COIN FLIP`. Both cards are honest renderings of the same underlying
near-tie. Use them together rather than picking whichever is more convenient.

**There is no "START NICO COLLINS +3.3 pp" card.** That verdict came from an
earlier synthetic dataset that has since been replaced with verified Week 1 2026
data. In the current data Nico Collins is a *starter*, and no lineup change
improves either roster: the best available swap is `-0.02 pp`. Both lineups are
already optimal, so no `START X` verdict exists to render at any seed. Producing
that card would mean fabricating a number the simulator does not output.

## Rendering liberties

The cards are the report's text, with two presentation changes:

- The report's own ASCII frames (`┏━┓`, `┌─┐`) are stripped, and the PNG's
  rounded edge takes their place — a box inside a box wastes space, and the
  vertical `┃` runs render as broken dashes at this line height.
- The footer is re-wrapped to 62 columns so it fits a phone screen. Every
  character is preserved.

Win-probability bars are drawn as solid rectangles rather than `█`/`░` glyphs,
which read as noise at this size. The margin histogram is deliberately left as
glyphs, since its shape depends on partial block characters.
