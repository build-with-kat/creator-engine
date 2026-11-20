#!/usr/bin/env python3
"""Before/after: who moved and why, plus prediction match rate.

Usage: python diff.py runs/<before>-scores.csv runs/<after>-scores.csv [--min-move 3]
Writes runs/<after-stem>-diff.md. Only real numbers from the two files; nothing estimated.
"""
import csv, sys, os, yaml

HERE = os.path.dirname(os.path.abspath(__file__))

def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {r["creator_id"]: r for r in csv.DictReader(f)}

def rank(r):
    try:
        return int(r.get("rank") or 0) or None
    except ValueError:
        return None

def main():
    argv = sys.argv[1:]
    min_move = 3
    if "--min-move" in argv:
        i = argv.index("--min-move")
        min_move = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    args = argv
    if len(args) != 2:
        sys.exit(__doc__)
    before, after = load(args[0]), load(args[1])
    rules = yaml.safe_load(open(os.path.join(HERE, "rules.yaml")))
    moves = []
    for cid, a in after.items():
        b = before.get(cid, {})
        rb, ra = rank(b), rank(a)
        if rb != ra:
            delta = (rb - ra) if (rb and ra) else None
            moves.append((cid, a["name"], rb, ra, delta, a.get("moved_because", "")))
    big = [m for m in moves if m[4] is None or abs(m[4]) >= min_move]
    big.sort(key=lambda m: -(abs(m[4]) if m[4] is not None else 999))
    decided = [r for r in after.values() if r.get("decision", "").strip()]
    judged = [r for r in decided if r.get("prediction_correct", "").strip().lower() in ("yes", "no")]
    correct = sum(1 for r in judged if r["prediction_correct"].strip().lower() == "yes")
    out = [f"# Diff: {os.path.basename(args[0])} -> {os.path.basename(args[1])}", "",
           f"Rules version: {rules['version']} · rows compared: {len(after)} · rank changed: {len(moves)} · moved >= {min_move} (or in/out of ranking): {len(big)}",
           f"Prediction match: {correct}/{len(judged)} decisions" + (f" ({100*correct/len(judged):.0f}%)" if judged else " (no decisions yet)"), "",
           "| Creator | Rank before | Rank now | Change | Moved because |", "|---|---|---|---|---|"]
    for cid, name, rb, ra, d, why in big:
        ch = "out" if ra is None else ("new" if rb is None else f"{d:+d}")
        out.append(f"| {name} | {rb or '-'} | {ra or '-'} | {ch} | {why} |")
    path = os.path.join(HERE, "runs", os.path.splitext(os.path.basename(args[1]))[0] + "-diff.md")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("\n".join(out[:4]))
    print(f"wrote {path}")

if __name__ == "__main__":
    main()
