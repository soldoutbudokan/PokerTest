# Daily poker-bot improvement routine

You are an autonomous engineer waking up to spend one bounded session trying to
make the PokerTest bot **objectively** better, and recording what happened.
Each run starts a **fresh session with no memory** — everything you need is in
the repo. Be rigorous: an "improvement" only counts if the numbers say so.

## Mission

Make exactly one well-scoped attempt to improve the bot, measure it against the
current bot with the project's objective evaluation, and:

- if it is a real improvement with **no regression**, keep the code change;
- either way, append today's metrics to the history and write up the experiment.

Never ship a regression. Never invent results — run the code and report what it
prints.

## 0. Orient (read these first, in order)

1. `README.md` — what the project is.
2. `DEPENDENCIES.md` — what depends on what. **Re-read the "If you change X" and
   "Invariants that must never break" sections before editing anything.**
3. `EVALUATION.md` — the current objective numbers.
4. `EXPERIMENTS.md` — the lab notebook: what's already been tried (don't repeat a
   failed idea without a new angle).
5. `metrics_history.csv` — the metric time series (may not exist on day 1).

The single source of truth for metrics is `pokerbot/metrics.py`
(`compute_metrics(level=...)` and `flatten(...)`). The visualizations
(`pokerbot/visualize.py`) and report (`pokerbot/evaluate.py`) read from it.

## 1. Environment + baseline

```bash
pip install -q numpy matplotlib pytest
git fetch origin main && git checkout main && git pull --ff-only origin main
git checkout -b daily/improve-$(date +%Y-%m-%d)
pytest -q                       # GATE: if this is red, fix or stop. Do not proceed on a broken tree.
```

Record the **baseline** (current bot) metrics and save them:

```bash
python -c "import json; from pokerbot.metrics import compute_metrics, flatten; \
m=compute_metrics(level='standard'); \
open('/tmp/baseline_metrics.json','w').write(json.dumps(m)); \
print(json.dumps(flatten(m), indent=2))"
```

`standard` level takes a few minutes. Use `quick` only for smoke-testing code
edits; always do the final comparison at `standard` (or `full` if time allows)
and **use the same level for baseline and candidate**.

## 2. Pick ONE improvement

Choose a single idea you have **not** already tried (check `EXPERIMENTS.md`).
Suggested backlog, roughly easy→hard:

1. **Train longer** — raise the bot's MCCFR deals. Only counts if exploitability
   actually drops (it converges ~O(1/√T), so confirm, don't assume).
2. **Richer bet sizing** — add a `0.5`-pot bet (`bet_sizes=(0.5, 1.0)`). Bigger
   tree, slower training; check it's a net win.
3. **More post-flop buckets** — `StrengthAbstraction(postflop_buckets=12)`.
4. **Draw-aware abstraction** — add a flush-draw / open-ended-straight-draw
   feature to the post-flop bucket so the bot stops treating draws as air. This
   is the most likely real strength win (the current abstraction is draw-blind).
5. **DCFR tuning** — sweep `(alpha, beta, gamma)` on Leduc (cheap, exact
   exploitability) and adopt the best for the NLHE trainer.
6. **Deeper stacks** — `stack=40` BB gives more room to out-play TAG.
7. **External-sampling MCCFR** — cheaper iterations, more of them.
8. **Potential-aware (equity) abstraction** — Monte-Carlo equity buckets instead
   of made-hand strength. Slow but the highest ceiling.

Keep the change small and localized (see `DEPENDENCIES.md` for blast radius).

## 3. Implement + smoke test

Make the change, then:

```bash
pytest -q                       # must stay green
python -m pokerbot.visualize --level quick   # smoke: does the pipeline still run?
```

If you changed `metrics.py`, update `flatten()`/`HISTORY_COLUMNS`, `visualize.py`
and `evaluate.py` to match (per `DEPENDENCIES.md`).

## 4. Measure the candidate vs baseline

Recompute candidate metrics at the **same level** as the baseline and compare:

```bash
python -c "import json; from pokerbot.metrics import compute_metrics, flatten; \
m=compute_metrics(level='standard'); \
open('/tmp/candidate_metrics.json','w').write(json.dumps(m)); \
print(json.dumps(flatten(m), indent=2))"
```

## 5. Decide (the objective gate)

An attempt is an **IMPROVEMENT** iff ALL hold (compare candidate vs baseline):

- `pytest -q` is green.
- The invariants in `DEPENDENCIES.md` still hold (Kuhn ≈ −1/18 & low
  exploitability; Leduc exploitability falls; bot still crushes random /
  call-station / maniac significantly; BR exploitability ≥ ~0).
- **Primary metric improves**: `nlhe_exploitability_bb100` is **lower** by more
  than noise, OR `win_vs_tight_aggressive` is **higher** by more than its CI.
- **No regression**: no baseline category (any `win_vs_*`) drops by more than its
  95% CI, and exploitability does not rise beyond noise.

Be honest about noise: MCCFR + Monte-Carlo evaluation are stochastic. A 1–2
bb/100 wiggle is noise, not signal. If it's within CIs, it's NOT an improvement.

## 6. Commit + record (always leave a trace)

Regardless of outcome, append a dated row to the history and a notebook entry:

```bash
python -c "import datetime, json; from pokerbot.metrics import flatten, append_history; \
m=json.load(open('/tmp/candidate_metrics.json' if KEPT else '/tmp/baseline_metrics.json')); \
append_history(flatten(m), datetime.date.today().isoformat())"
```
(set `KEPT` to whether you kept the change).

Add an `EXPERIMENTS.md` entry: date, idea tried, hypothesis, the before/after
flat metrics, the verdict (IMPROVEMENT / NO CHANGE / REGRESSION) and why.

Then:

- **If IMPROVEMENT:** keep the code. Regenerate outputs and commit to `main`:
  ```bash
  python -m pokerbot.evaluate --out EVALUATION.md
  python -m pokerbot.visualize --level standard
  git add -A && git commit -m "daily: <idea> — exploitability X→Y bb/100, TAG A→B"
  git checkout main && git merge --ff-only daily/improve-$(date +%Y-%m-%d) && git push origin main
  ```
- **If NO CHANGE / REGRESSION:** revert the code change (`git checkout -- <files>`
  or `git reset --hard`), but still commit the history row + `EXPERIMENTS.md`
  entry so the trail is continuous:
  ```bash
  git checkout main && git add metrics_history.csv EXPERIMENTS.md && \
  git commit -m "daily: <idea> — no improvement (see EXPERIMENTS.md)" && git push origin main
  ```

End your turn with a 3–5 line summary: idea, before→after numbers, verdict.

## Budget + safety

- One idea per run. Don't sprawl. If training/eval would take too long, drop to a
  smaller `level` for both baseline and candidate (kept comparable).
- Never push code that fails `pytest` or breaks an invariant.
- Never overwrite history rows; only append.
- If you're unsure whether something is noise, treat it as noise (don't ship).
- If the repo is mid-conflict or `main` won't fast-forward, stop and report
  rather than forcing anything.
