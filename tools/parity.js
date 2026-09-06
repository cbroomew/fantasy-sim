/*
 * parity.js — check the browser simulator against sim.py.
 *
 * index.html is a single file by design, so this pulls the DOM-free <script>
 * blocks out of it and runs them in Node. The two implementations use different
 * random number generators (Python: Mersenne Twister, browser: sfc32), so they
 * are statistically equivalent, NOT bit-identical. Win probability should agree
 * to within Monte Carlo error, which shrinks as --sims rises.
 *
 *   node tools/parity.js [sims] [seed]
 *   python3 sim.py --sims <same> | head -30      # compare by eye
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const sims = parseInt(process.argv[2] || "100000", 10);
const seed = parseInt(process.argv[3] || "1234", 10);

const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const blocks = [...html.matchAll(/<script(?![^>]*id="ui")[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (blocks.length < 2) throw new Error("expected the core and reporter script blocks in index.html");
const api = new Function(blocks.join("\n") + "\nreturn {simulate, renderReport, DEFAULT_ROSTER};")();

/* 1. the embedded roster must still match projections.csv */
const csv = fs.readFileSync(path.join(ROOT, "projections.csv"), "utf8").trim().split("\n");
const head = csv[0].split(",");
const rows = csv.slice(1).map(line => {
  const out = []; let f = "", q = false;
  for (let i = 0; i < line.length; i++){
    const c = line[i];
    if (q){ if (c === '"'){ if (line[i+1] === '"'){ f += '"'; i++; } else q = false; } else f += c; }
    else if (c === '"') q = true;
    else if (c === ","){ out.push(f); f = ""; }
    else f += c;
  }
  out.push(f);
  return Object.fromEntries(head.map((h, i) => [h, out[i]]));
});

let drift = 0;
if (rows.length !== api.DEFAULT_ROSTER.length){
  console.log(`MISMATCH  csv has ${rows.length} players, index.html has ${api.DEFAULT_ROSTER.length}`);
  drift++;
} else {
  rows.forEach((r, i) => {
    const p = api.DEFAULT_ROSTER[i];
    const same = p.name === r.player && p.team === r.fantasy_team && p.slot === r.slot
              && p.pos === r.pos && p.nfl === r.team && p.opp === r.opp
              && Math.abs(p.proj - parseFloat(r.proj)) < 1e-9
              && Math.abs(p.std - parseFloat(r.std)) < 1e-9
              && (p.source || "") === (r.source || "");
    if (!same){ console.log(`MISMATCH  row ${i + 1}: ${r.player}`); drift++; }
  });
}
console.log(drift === 0
  ? `embedded roster matches projections.csv  (${rows.length} players)`
  : `${drift} row(s) drifted from projections.csv`);

/* 2. run the browser simulator */
const t0 = Date.now();
const res = api.simulate(api.DEFAULT_ROSTER, sims, seed);
const ms = Date.now() - t0;
const [A, B] = res.teams;

console.log(`\nbrowser core · ${sims.toLocaleString()} sims · seed ${seed} · ${ms} ms`);
console.log(`  ${A.padEnd(24)} ${(res.wp[A] * 100).toFixed(2)}%`);
console.log(`  ${B.padEnd(24)} ${(res.wp[B] * 100).toFixed(2)}%`);
console.log(`  mean margin              ${res.meanMargin.toFixed(2)}`);
if (res.call){
  const c = res.call;
  console.log(`  featured call            ${c.team} ${c.slot}: ${c.out.name} vs ${c.in.name}`);
  console.log(`  delta win%               ${(c.dWp * 100).toFixed(3)} pp  +/- ${(2 * c.se * 100).toFixed(3)} pp`);
  console.log(`  verdict                  ${c.significant ? (c.dWp > 0 ? "START " + c.in.name : "STICK WITH " + c.out.name) : "TRUE COIN FLIP"}`);
}

if (process.env.SHOW_REPORT){
  console.log("\n" + api.renderReport(res, 78)
    .map(line => line.map(s => s.t).join("")).join("\n"));
}
process.exit(drift === 0 ? 0 : 1);
