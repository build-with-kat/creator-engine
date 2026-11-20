#!/usr/bin/env python3
"""Weighted overall, priority and rank for every row in scores.csv, using rules.yaml.

Usage: python score.py            # rescore in place, keep previous rank in rank_before
       python score.py --dry-run  # print the table, write nothing
Writes a snapshot to runs/<UTC timestamp>-scores.csv. Never touches pool.csv.
Needs: PyYAML (pip install pyyaml).
"""
import csv, sys, os, datetime, yaml

SUBS = ["dev_audience_fit", "building_evidence", "creative_product_fit",
        "organic_performance", "community_intent"]
HERE = os.path.dirname(os.path.abspath(__file__))

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)

def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def cond(row, w):
    v = row.get(w["column"], "")
    op, target = w.get("op", "eq"), w.get("value")
    if op == "contains":
        return str(target).lower() in str(v).lower()
    if op in ("eq", "ne"):
        hit = str(v).strip().lower() == str(target).strip().lower()
        return hit if op == "eq" else not hit
    a, b = num(v), num(target)
    if a is None or b is None:
        return False
    return {"gt": a > b, "lt": a < b, "gte": a >= b, "lte": a <= b}[op]

def main():
    dry = "--dry-run" in sys.argv
    rules = yaml.safe_load(open(os.path.join(HERE, "rules.yaml")))
    weights = dict(rules["weights"])
    learned = rules.get("rules") or []
    for r in learned:
        if r.get("kind") == "weight":
            weights.update(r["weights"])
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        sys.exit(f"weights sum to {total}, not 1.0")
    fields, rows = load_csv(os.path.join(HERE, "scores.csv"))
    pool = {}
    pp = os.path.join(HERE, "pool.csv")
    if os.path.exists(pp):
        for p in load_csv(pp)[1]:
            pool[p["creator_id"]] = p
    for row in rows:
        ctx = {**pool.get(row["creator_id"], {}), **row}
        subs = [num(row.get(s)) for s in SUBS]
        excluded = bool(ctx.get("exclusion_flags", "").strip())
        if None in subs:
            row["overall"], row["priority"] = "", "Unscored"
            continue
        o = sum(weights[s] * v for s, v in zip(SUBS, subs))
        for r in learned:
            if r.get("kind") == "adjust" and cond(ctx, r["when"]):
                o += float(r["delta"])
            if r.get("kind") == "exclude" and cond(ctx, r["when"]):
                excluded = True
        o = max(1.0, min(5.0, o))
        row["overall"] = f"{o:.1f}"
        if excluded:
            row["priority"] = "Excluded"
        elif o >= rules["priority"]["high"]:
            row["priority"] = "High"
        elif o >= rules["priority"]["medium"]:
            row["priority"] = "Medium"
        else:
            row["priority"] = "Low"
    ranked = sorted([r for r in rows if r["priority"] not in ("Excluded", "Unscored")],
                    key=lambda r: (-float(r["overall"]), r["name"].lower()))
    for r in rows:
        r["rank_before"] = r.get("rank", "")
        r["rank"] = ""
    for i, r in enumerate(ranked, 1):
        r["rank"] = str(i)
    for r in rows:
        r["rules_version"] = str(rules["version"])
    if dry:
        for r in sorted(ranked, key=lambda r: int(r["rank"])):
            print(r["rank"], r["overall"], r["priority"], r["name"], r["platform"])
        return
    def write(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    write(os.path.join(HERE, "scores.csv"))
    os.makedirs(os.path.join(HERE, "runs"), exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snap = os.path.join(HERE, "runs", f"{stamp}-v{rules['version']}-scores.csv")
    write(snap)
    print(f"scored {len(ranked)} ranked, {len(rows) - len(ranked)} excluded/unscored; snapshot {snap}")

if __name__ == "__main__":
    main()
