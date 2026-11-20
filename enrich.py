#!/usr/bin/env python3
"""Enrich candidates.csv (written by MeerKat) into pool.csv (read-only for MeerKat).

Runs on Grok Bot's computer, never inside Devin. Public data only: metadata and
comment samples, no video/media downloads. Missing data stays blank; nothing is estimated.

  python enrich.py --youtube                      # YouTube rows via yt-dlp (no API key)
  python enrich.py --instagram --max-usd 4.5      # Instagram rows via Apify (needs APIFY_TOKEN env var)
  python enrich.py --instagram --ig-profiles p.json --ig-comments c.json   # merge Apify exports instead
  python enrich.py --youtube --only C001,C002     # a few rows (testing)
  python enrich.py --youtube --instagram --round 2 # only candidates.csv rows with round == 2 (lookalikes)

Existing pool.csv rows are updated in place (keyed by creator_id), so the two
platforms can run separately. Apify pricing is checked against --max-usd before any run.
"""
import csv, json, os, re, statistics, subprocess, sys, datetime, urllib.request, time

HERE = os.path.dirname(os.path.abspath(__file__))
CAND = os.path.join(HERE, "candidates.csv")
POOL = os.path.join(HERE, "pool.csv")
POOL_FIELDS = ["creator_id", "name", "platform", "youtube_url", "youtube_subscribers",
    "instagram_handle", "instagram_url", "instagram_followers", "why_found", "found_because", "round", "source_url",
    "pool", "type", "yt_videos", "yt_median_views_long", "yt_median_views_shorts",
    "ig_posts", "ig_median_views_reels", "ig_median_likes", "comments", "n_comments",
    "n_explicit", "n_inferred", "devin_evidence", "exclusion_flags", "notes", "collected_date"]
YT_VIDEOS, YT_COMMENT_VIDEOS, YT_COMMENTS_EACH = 10, 2, 10
IG_COMMENT_POSTS, IG_COMMENTS_EACH = 2, 10
# Apify official actors, free-tier per-event prices (USD) read 21 Nov 2026 from the actor pages.
PRICE_PROFILE, PRICE_COMMENT = 0.0026, 0.0026

EXPLICIT = re.compile(r"\b(i(?:'m| am) a (?:dev|developer|engineer|programmer|swe)|as a (?:dev|developer|engineer|programmer|swe)|i (?:code|coded|built|build|ship|shipped|deploy(?:ed)?)|my (?:repo|codebase|app|project|startup|side project|team's code|pr|stack)|our codebase|at work we|in production)\b", re.I)
INFERRED = re.compile(r"\b(api|repo|github|git|pr|pull request|deploy|backend|frontend|typescript|python|react|next\.?js|docker|kubernetes|sql|supabase|cli|terminal|ide|vs ?code|cursor|claude code|codex|windsurf|devin|mcp|context window|tokens?|prompt|agent|bug|debug|refactor|test(?:s|ing)?|lint|framework|library|sdk|llm|rate limit)\b", re.I)
DEVIN = re.compile(r"\bdevin\b", re.I)
DEVIN_CTX = re.compile(r"cognition|ai|agent|software engineer|coding|windsurf|deepwiki|devin\.ai", re.I)
EXCL = re.compile(r"#cognitionpartner|(sponsor|partner|paid|#ad\b|collab)\w*.{0,60}\b(cognition|devin)\b|\b(cognition|devin)\b.{0,60}(sponsor|partner|paid partnership)", re.I | re.S)

def tag(text):
    if EXPLICIT.search(text or ""): return "explicit"
    if INFERRED.search(text or ""): return "inferred"
    return "unknown"

def med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return int(statistics.median(xs)) if xs else ""

def ytdlp(args, timeout=240):
    r = subprocess.run(["yt-dlp", "--no-warnings", "--skip-download", "-J"] + args,
                       capture_output=True, text=True, timeout=timeout)
    if not r.stdout.strip():
        raise RuntimeError((r.stderr or "no output").strip().splitlines()[-1][:200])
    d = json.loads(r.stdout)
    if not isinstance(d, dict):
        raise RuntimeError("yt-dlp returned no data")
    return d

def read_csv(path):
    if not os.path.exists(path): return []
    with open(path, newline="", encoding="utf-8") as f: return list(csv.DictReader(f))

def flags_for(texts):
    hits = [t[1] for t in texts if EXCL.search(t[0] or "")]
    return ("possible Cognition partnership: " + " ".join(hits[:3])) if hits else ""

def devin_hits(texts):
    return [u for t, u in texts if DEVIN.search(t or "") and DEVIN_CTX.search(t or "")]

def enrich_youtube(row):
    url = row["youtube_url"].rstrip("/")
    for tab in ("/videos", "/shorts", "/streams", "/featured"):
        if url.endswith(tab): url = url[: -len(tab)]
    out = {}
    d = ytdlp(["--playlist-end", str(YT_VIDEOS), url + "/videos"], timeout=600)
    out["youtube_url"] = d.get("channel_url") or url
    out["youtube_subscribers"] = d.get("channel_follower_count") or ""
    vids = []
    for e in d.get("entries") or []:
        if not e: continue
        vids.append({"title": e.get("title"), "url": e.get("webpage_url"), "format": "long",
                     "published": e.get("upload_date"), "duration_s": e.get("duration"),
                     "views": e.get("view_count"), "likes": e.get("like_count"),
                     "comments": e.get("comment_count"), "_desc": e.get("description") or ""})
    try:
        s = ytdlp(["--flat-playlist", "--playlist-end", "10", url + "/shorts"], timeout=120)
        for e in s.get("entries") or []:
            if not e: continue
            vids.append({"title": e.get("title"), "url": e.get("url"), "format": "short",
                         "published": "", "duration_s": e.get("duration"), "views": e.get("view_count"),
                         "likes": "", "comments": "", "_desc": ""})
    except Exception:
        pass  # channel has no Shorts tab
    texts = [(v["title"] + "\n" + v["_desc"], v["url"]) for v in vids]
    out["yt_median_views_long"] = med([v["views"] for v in vids if v["format"] == "long"])
    out["yt_median_views_shorts"] = med([v["views"] for v in vids if v["format"] == "short"])
    n_long = sum(v["format"] == "long" for v in vids); n_short = len(vids) - n_long
    out["type"] = "YouTube long-form" if n_short == 0 else ("YouTube Shorts-first" if n_short > n_long * 2 else "YouTube mixed")
    cutoff = (datetime.date.today() - datetime.timedelta(days=14)).strftime("%Y%m%d")
    old = [v for v in vids if v["format"] == "long" and v["published"] and v["published"] <= cutoff]
    picks = sorted(old, key=lambda v: -(v["views"] or 0))[:YT_COMMENT_VIDEOS]
    comments = []
    for v in picks:
        try:
            c = ytdlp(["--write-comments", "--extractor-args",
                       f"youtube:max_comments={YT_COMMENTS_EACH * 2},{YT_COMMENTS_EACH * 2},0,0;comment_sort=top", v["url"]])
        except Exception as e:
            continue
        n = 0
        for cm in c.get("comments") or []:
            if not cm: continue
            if cm.get("is_pinned") or cm.get("author_is_uploader") or cm.get("parent", "root") != "root": continue
            text = (cm.get("text") or "").strip()
            if not text: continue
            comments.append({"text": text[:400], "url": f"{v['url']}&lc={cm.get('id')}", "likes": cm.get("like_count"), "tag": tag(text), "on": v["url"]})
            n += 1
            if n >= YT_COMMENTS_EACH: break
        time.sleep(1)
    for v in vids: v.pop("_desc", None)
    out["yt_videos"] = json.dumps(vids, ensure_ascii=False)
    return out, comments, texts

def apify(actor, body, max_usd):
    tok = os.environ.get("APIFY_TOKEN")
    if not tok: sys.exit("APIFY_TOKEN not set; or pass --ig-profiles/--ig-comments exports")
    q = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?maxTotalChargeUsd={max_usd}&timeout=900"
    req = urllib.request.Request(q, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=960) as r: return json.loads(r.read())

def enrich_instagram(rows, max_usd, prof_file=None, com_file=None):
    handles = [r["instagram_handle"].lstrip("@").strip() for r in rows if r.get("instagram_handle")]
    est = len(handles) * PRICE_PROFILE + len(handles) * IG_COMMENT_POSTS * IG_COMMENTS_EACH * PRICE_COMMENT
    print(f"Instagram: {len(handles)} profiles; estimated max cost ${est:.2f} (cap ${max_usd})")
    if not prof_file and est > max_usd: sys.exit("estimate over cap; stopping before any Apify run")
    profs = json.load(open(prof_file)) if prof_file else apify("apify~instagram-profile-scraper", {"usernames": handles}, round(len(handles) * PRICE_PROFILE + 0.05, 2))
    if isinstance(profs, dict): profs = profs.get("items", [])
    by = {p.get("username", "").lower(): p for p in profs}
    res, post_urls = {}, []
    for h in handles:
        p = by.get(h.lower())
        if not p or p.get("error"):
            res[h] = ({"notes": f"Instagram: {(p or {}).get('error', 'not returned')}"}, [], []); continue
        posts = []
        for x in p.get("latestPosts") or []:
            posts.append({"url": x.get("url"), "type": x.get("productType") or x.get("type"), "published": (x.get("timestamp") or "")[:10],
                          "views": x.get("videoViewCount") or x.get("videoPlayCount"), "likes": x.get("likesCount"),
                          "comments": x.get("commentsCount"), "caption": (x.get("caption") or "")[:200]})
        reels = [q for q in posts if q["views"]]
        cutoff = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
        top = sorted([q for q in posts if q["published"] and q["published"] <= cutoff], key=lambda q: -(q["comments"] or 0))[:IG_COMMENT_POSTS]
        post_urls += [q["url"] for q in top if q["url"]]
        out = {"instagram_handle": h, "instagram_url": f"https://www.instagram.com/{h}/", "instagram_followers": p.get("followersCount", ""),
               "ig_posts": json.dumps(posts, ensure_ascii=False), "ig_median_views_reels": med([q["views"] for q in reels]),
               "ig_median_likes": med([q["likes"] for q in posts])}
        texts = [((p.get("biography") or "") + "\n" + q["caption"], q["url"]) for q in posts]
        res[h] = (out, [], texts)
    if com_file:
        coms = json.load(open(com_file))
    elif post_urls:
        coms = apify("apify~instagram-comment-scraper", {"directUrls": post_urls, "resultsLimit": IG_COMMENTS_EACH},
                     round(len(post_urls) * IG_COMMENTS_EACH * PRICE_COMMENT + 0.05, 2))
    else:
        coms = []
    if isinstance(coms, dict): coms = coms.get("items", [])
    owner = {}
    for h, (out, _, _) in res.items():
        for q in json.loads(out.get("ig_posts") or "[]"): owner[(q["url"] or "").rstrip("/")] = h
    for c in coms:
        src = (c.get("postUrl") or c.get("inputUrl") or "").rstrip("/")
        h = owner.get(src)
        text = (c.get("text") or "").strip()
        if h and text:
            res[h][1].append({"text": text[:400], "url": src, "likes": c.get("likesCount"), "tag": tag(text), "on": src})
    return res

def main():
    a = sys.argv
    only = set(a[a.index("--only") + 1].split(",")) if "--only" in a else None
    rnd = a[a.index("--round") + 1] if "--round" in a else None
    cands = [c for c in read_csv(CAND) if (not only or c["candidate_id"] in only) and (not rnd or c.get("round", "") == rnd)]
    pool = {r["creator_id"]: r for r in read_csv(POOL)}
    today = datetime.date.today().isoformat()
    def base(c):
        r = pool.get(c["candidate_id"]) or {k: "" for k in POOL_FIELDS}
        r.update({"creator_id": c["candidate_id"], "name": c["name"], "platform": c["platform"], "why_found": c["why_found"],
                  "found_because": c.get("found_because", ""), "round": c.get("round", ""),
                  "source_url": c["source_url"], "collected_date": today})
        if c.get("youtube_url"): r["youtube_url"] = c["youtube_url"]
        if c.get("instagram_handle"): r["instagram_handle"] = c["instagram_handle"].lstrip("@")
        return r
    def merge(r, out, comments, texts):
        r.update(out)
        if DEVIN.search(r.get("why_found") or ""): texts = texts + [(r["why_found"] + " ai", r["source_url"])]
        old = json.loads(r.get("comments") or "[]")
        plat = "instagram.com" if comments and "instagram.com" in comments[0]["url"] else "youtube.com"
        allc = [x for x in old if plat not in x["url"]] + comments
        r["comments"] = json.dumps(allc, ensure_ascii=False)
        r["n_comments"] = len(allc)
        r["n_explicit"] = sum(x["tag"] == "explicit" for x in allc)
        r["n_inferred"] = sum(x["tag"] == "inferred" for x in allc)
        dh = devin_hits(texts)
        prev = [u for u in (r.get("devin_evidence") or "").split() if u]
        r["devin_evidence"] = " ".join(dict.fromkeys(prev + dh))
        r["pool"] = "building with Devin (verify)" if r["devin_evidence"] else "net-new"
        fl = flags_for(texts)
        if fl: r["exclusion_flags"] = fl
    if "--youtube" in a:
        for c in cands:
            if not c.get("youtube_url"): continue
            r = base(c)
            try:
                out, com, texts = enrich_youtube(c)
                merge(r, out, com, texts)
                print(f"YT ok  {c['candidate_id']} {c['name']}: {len(json.loads(out['yt_videos']))} videos, {len(com)} comments")
            except Exception as e:
                import traceback; traceback.print_exc()
                r["notes"] = (r.get("notes", "") + f" YouTube error: {e}").strip()
                print(f"YT err {c['candidate_id']} {c['name']}: {e}")
            pool[c["candidate_id"]] = r
            time.sleep(2)
    if "--instagram" in a:
        max_usd = float(a[a.index("--max-usd") + 1]) if "--max-usd" in a else 4.5
        igc = [c for c in cands if c.get("instagram_handle")]
        pf = a[a.index("--ig-profiles") + 1] if "--ig-profiles" in a else None
        cf = a[a.index("--ig-comments") + 1] if "--ig-comments" in a else None
        res = enrich_instagram(igc, max_usd, pf, cf)
        for c in igc:
            r = base(c)
            out, com, texts = res.get(c["instagram_handle"].lstrip("@").strip(), ({}, [], []))
            merge(r, out, com, texts)
            pool[c["candidate_id"]] = r
            print(f"IG {c['candidate_id']} {c['name']}: followers {out.get('instagram_followers','')}, {len(com)} comments {out.get('notes','')}")
    for r in pool.values():
        if r.get("youtube_url") and r.get("instagram_handle"): r["platform"] = "Both"
        if r.get("instagram_handle") and r.get("youtube_url") and r.get("type") and "Instagram" not in r["type"]: r["type"] += " + Instagram"
        elif r.get("instagram_handle") and not r.get("type"): r["type"] = "Instagram"
    with open(POOL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=POOL_FIELDS, extrasaction="ignore")
        w.writeheader()
        for k in sorted(pool): w.writerow(pool[k])
    print(f"pool.csv: {len(pool)} rows")

if __name__ == "__main__":
    main()
