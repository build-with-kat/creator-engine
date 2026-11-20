# Creator Engine

**Independent prototype from public research, not affiliated with Cognition.**

A self-learning engine that finds developer creators on YouTube and Instagram, scores them for paid-social tests, predicts a human reviewer's approve/reject calls, learns from the reasons, and reranks everyone automatically. Human approval gates at every step; nothing is ever sent to a creator.

## Flow
1. **Discover** (Devin Bot): searches YouTube + Instagram and writes `candidates.csv`.
2. **Enrich** (`enrich.py`, run outside Devin): public metadata and comment samples into `pool.csv`. No media downloads.
3. **Score** (Devin Bot): 1-5 sub-scores, reason, confidence and a *predicted decision* per creator into `scores.csv`; `score.py` computes overall, priority and rank.
4. **Learn**: reviewer decisions + reasons become rules in `rules.yaml`; `score.py` reranks all; `diff.py` reports movers and prediction match rate.
5. **Plan / outreach drafts** for approved creators only (drafts, never sent).

## Files
| File | Written by | Notes |
|---|---|---|
| `candidates.csv` | Devin Bot | handle, URL, platform, why found, source URL |
| `pool.csv` | `enrich.py` | read-only for the Devin Bot; blanks where data is missing |
| `scores.csv` | Devin Bot + `score.py` | scores, reasons, predictions, decisions, ranks |
| `rules.yaml` | approved rules only | weights + learned rules, versioned |
| `score.py` | | `python score.py` (needs `pip install pyyaml`) |
| `diff.py` | | `python diff.py runs/<before>.csv runs/<after>.csv` |
| `enrich.py` | | `python enrich.py --youtube` (yt-dlp) / `--instagram` (Apify, `APIFY_TOKEN` env var, spend cap `--max-usd`) |
| `runs/` | | snapshots and diffs per run |

## Rubric (weights in `rules.yaml`)
Developer audience fit 30% · Authentic building evidence 25% · Creative & product fit 20% · Organic performance 15% · Community intent 10%. High >= 4.0, Medium 3.0-3.9, Low < 3.0.

Comment tags in `pool.csv` (`explicit` / `inferred` / `unknown`) are a first-pass keyword heuristic and must be checked. Creators flagged for a brand partnership with the product being tested are recorded but never picked. Public data only; no numbers are estimated or invented.
