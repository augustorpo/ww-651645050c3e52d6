#!/usr/bin/env python3
"""Publish an episode of "The Wealth Whisperer: A CPWA Casebook" to its private (unlisted) GitHub Pages feed.

This is a SEPARATE feed from Signal & Noise (own repo, own config). It never touches /home/box/podcast.

Usage:
  python3 /home/box/podcast-wealth-whisperer/publish_episode.py \
      --mp3 /workspace/cpwa-podcast/ep02-behavioral.mp3 --episode 2 \
      --title "Episode 2: Behavioral Finance" \
      --description-file notes.txt [--chapters ep02.chapters.json] [--pubdate "YYYY-MM-DD HH:MM"] [--wait]

  --slug defaults to "ep<NN>" + the MP3's base name, e.g. ep02-behavioral.mp3 -> ep02-behavioral.
  --chapters takes the renderer's chapters JSON ([{"title","start_seconds"}...]); it is published as
    podcast:chapters (chapters/<slug>.json) and the chapter list with timestamps is appended to the description.
  --replace [--file <slug>-v2.mp3]  replace an episode (same guid); a new file name cache-busts apps.
  --rebuild                          just regenerate feed.xml from episodes.json and push.
  --wait                             after pushing, poll until GitHub Pages serves the new feed + MP3 (<=10 min).

Config: /home/box/podcast-wealth-whisperer/config.json (override with WW_CONFIG).
"""
import argparse, json, os, re, shutil, subprocess, sys, time, urllib.request
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape, quoteattr
import xml.etree.ElementTree as ET

TZ = ZoneInfo("America/New_York")
CONFIG = Path(os.environ.get("WW_CONFIG", "/home/box/podcast-wealth-whisperer/config.json"))

def run(cmd, cwd=None, check=True):
    print("+", " ".join(cmd)); return subprocess.run(cmd, cwd=cwd, check=check)

def probe_seconds(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", str(p)]).decode().strip())

def hms(s):
    s = int(round(s)); return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

def mmss(s):
    s = int(s); return f"{s//3600}:{(s%3600)//60:02d}:{s%60:02d}" if s >= 3600 else f"{s//60}:{s%60:02d}"

def build_feed(cfg, episodes):
    base = cfg["base_url"].rstrip("/")
    show = cfg["show"]; cover = cfg.get("cover", "cover-v1.jpg")
    items = []
    for ep in sorted(episodes, key=lambda e: e["pub_iso"], reverse=True):
        pub = format_datetime(datetime.fromisoformat(ep["pub_iso"]))
        url = f"{base}/episodes/{ep['file']}"
        extra = ""
        if ep.get("episode") is not None:
            extra += f"\n      <itunes:episode>{int(ep['episode'])}</itunes:episode>"
        if ep.get("chapters"):
            extra += f"\n      <podcast:chapters url={quoteattr(base + '/chapters/' + ep['chapters'])} type=\"application/json+chapters\"/>"
        items.append(f"""    <item>
      <title>{escape(ep['title'])}</title>
      <itunes:title>{escape(ep['title'])}</itunes:title>
      <description>{escape(ep['description'])}</description>
      <itunes:summary>{escape(ep['description'])}</itunes:summary>
      <itunes:author>{escape(show['author'])}</itunes:author>
      <enclosure url={quoteattr(url)} length="{ep['length']}" type="audio/mpeg"/>
      <guid isPermaLink="false">{escape(ep['guid'])}</guid>
      <pubDate>{pub}</pubDate>
      <itunes:duration>{ep['duration']}</itunes:duration>
      <itunes:image href={quoteattr(base + '/' + cover)}/>
      <itunes:explicit>false</itunes:explicit>
      <itunes:episodeType>{escape(ep.get('episode_type', 'full'))}</itunes:episodeType>{extra}
    </item>""")
    last = format_datetime(datetime.now(TZ).replace(microsecond=0))
    cat = f'<itunes:category text={quoteattr(show.get("category", "Education"))}>'
    cat += (f'<itunes:category text={quoteattr(show["subcategory"])}/>' if show.get("subcategory") else "") + "</itunes:category>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:podcast="https://podcastindex.org/namespace/1.0" xmlns:googleplay="http://www.google.com/schemas/play-podcasts/1.0">
  <channel>
    <title>{escape(show['title'])}</title>
    <link>{escape(base)}/</link>
    <atom:link href={quoteattr(base + '/feed.xml')} rel="self" type="application/rss+xml"/>
    <description>{escape(show['summary'])}</description>
    <language>{escape(show.get('language', 'en-us'))}</language>
    <lastBuildDate>{last}</lastBuildDate>
    <itunes:author>{escape(show['author'])}</itunes:author>
    <itunes:summary>{escape(show['summary'])}</itunes:summary>
    <itunes:subtitle>{escape(show.get('subtitle', ''))}</itunes:subtitle>
    <itunes:owner><itunes:name>{escape(show['author'])}</itunes:name></itunes:owner>
    <itunes:explicit>false</itunes:explicit>
    <itunes:type>episodic</itunes:type>
    <itunes:image href={quoteattr(base + '/' + cover)}/>
    <image><url>{escape(base)}/{escape(cover)}</url><title>{escape(show['title'])}</title><link>{escape(base)}/</link></image>
    {cat}
    <itunes:block>Yes</itunes:block>
    <googleplay:block>yes</googleplay:block>
    <podcast:locked>yes</podcast:locked>
{chr(10).join(items)}
  </channel>
</rss>
"""

def site_files(cfg, repo):
    (repo / ".nojekyll").touch()
    (repo / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (repo / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><meta name=robots content=\"noindex,nofollow\">"
        "<title>.</title><p>Private podcast feed.</p>\n")
    here = Path(__file__).resolve()
    if here.parent != repo.resolve():
        shutil.copyfile(here, repo / "publish_episode.py")

def write_feed(cfg, repo, episodes):
    feed = build_feed(cfg, episodes)
    ET.fromstring(feed.encode())  # validate
    (repo / "feed.xml").write_text(feed)

def commit_push(repo, msg, push=True):
    run(["git", "add", "-A"], cwd=repo)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode == 0:
        print("nothing to commit"); return
    run(["git", "commit", "-m", msg], cwd=repo)
    if push:
        run(["git", "push", "origin", "main"], cwd=repo)

def wait_live(cfg, fname=None, length=None, timeout=600):
    base = cfg["base_url"].rstrip("/")
    marker = (repo_feed := (Path(cfg["clone"]) / "feed.xml").read_text())
    want = re.search(r"<lastBuildDate>(.*?)</lastBuildDate>", marker).group(1)
    t0 = time.time()
    while time.time() - t0 < timeout:
        ok = True
        try:
            body = urllib.request.urlopen(f"{base}/feed.xml?cb={time.time():.0f}", timeout=30).read().decode()
            ok = want in body
            if ok and fname:
                r = urllib.request.urlopen(urllib.request.Request(f"{base}/episodes/{fname}?cb={time.time():.0f}", method="HEAD"), timeout=30)
                ok = int(r.headers.get("Content-Length") or -1) == length
        except Exception as e:
            ok = False
        if ok:
            print(f"live after {time.time()-t0:.0f}s"); return True
        time.sleep(15)
    print("WARNING: not live yet after", timeout, "s"); return False

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mp3"); ap.add_argument("--title"); ap.add_argument("--episode", type=int)
    ap.add_argument("--description"); ap.add_argument("--description-file")
    ap.add_argument("--chapters", help="chapters JSON: [{title, start_seconds}, ...]")
    ap.add_argument("--no-chapter-list", action="store_true", help="don't append the chapter list to the description")
    ap.add_argument("--slug"); ap.add_argument("--file")
    ap.add_argument("--episode-type", choices=["full", "bonus", "trailer"], default="full")
    ap.add_argument("--pubdate", help="'YYYY-MM-DD HH:MM' America/New_York (default: now)")
    ap.add_argument("--replace", action="store_true"); ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--no-push", action="store_true"); ap.add_argument("--wait", action="store_true")
    a = ap.parse_args()

    cfg = json.loads(CONFIG.read_text()); repo = Path(cfg["clone"])
    epj = repo / "episodes.json"
    episodes = json.loads(epj.read_text()) if epj.exists() else []
    if a.rebuild:
        site_files(cfg, repo); write_feed(cfg, repo, episodes)
        commit_push(repo, "Rebuild feed", not a.no_push)
        if a.wait and not a.no_push: wait_live(cfg)
        return
    if not (a.mp3 and a.title):
        ap.error("--mp3 and --title are required (or use --rebuild)")
    mp3 = Path(a.mp3)
    slug = a.slug or re.sub(r"[^a-z0-9-]+", "-", mp3.stem.lower()).strip("-")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,120}", slug):
        sys.exit("slug must be lowercase letters, digits and hyphens")
    fname = a.file or f"{slug}.mp3"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,120}\.mp3", fname):
        sys.exit("--file must be lowercase letters, digits and hyphens ending in .mp3")
    existing = [e for e in episodes if e["slug"] == slug]
    if existing and not a.replace:
        sys.exit(f"Episode '{slug}' already exists; use --replace")
    if any(e["file"] == fname for e in episodes if e["slug"] != slug):
        sys.exit(f"File name {fname} is already used by another episode")
    if a.description and a.description_file:
        sys.exit("use either --description or --description-file, not both")
    desc = a.description or (Path(a.description_file).read_text(encoding="utf-8").strip() if a.description_file else "")

    chap_name = None
    if a.chapters:
        ch = json.loads(Path(a.chapters).read_text())
        if not a.no_chapter_list:
            desc = (desc + "\n\n" if desc else "") + "Chapters:\n" + "\n".join(
                f"{mmss(c['start_seconds'])} {c['title']}" for c in ch)
        (repo / "chapters").mkdir(exist_ok=True)
        chap_name = f"{slug}.json"
        (repo / "chapters" / chap_name).write_text(json.dumps({"version": "1.2.0", "chapters": [
            {"startTime": round(float(c["start_seconds"]), 2), "title": c["title"]} for c in ch]},
            indent=2, ensure_ascii=False) + "\n")
    if not desc:
        sys.exit("give --description/--description-file and/or --chapters")

    if a.pubdate:
        pub = datetime.strptime(a.pubdate, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    elif existing:  # --replace keeps the original publish time unless --pubdate is given
        pub = datetime.fromisoformat(existing[0]["pub_iso"])
    else:
        pub = datetime.now(TZ).replace(microsecond=0)
    (repo / "episodes").mkdir(exist_ok=True)
    dest = repo / "episodes" / fname
    shutil.copyfile(mp3, dest)
    stale = [repo / "episodes" / e["file"] for e in existing if e["file"] != fname]
    guid = existing[0]["guid"] if existing else f"wealth-whisperer-{slug}"
    entry = {"slug": slug, "title": a.title, "description": desc, "file": fname,
             "length": dest.stat().st_size, "duration": hms(probe_seconds(dest)),
             "pub_iso": pub.isoformat(), "guid": guid}
    if a.episode is not None: entry["episode"] = a.episode
    if chap_name: entry["chapters"] = chap_name
    if a.episode_type != "full": entry["episode_type"] = a.episode_type
    episodes = [e for e in episodes if e["slug"] != slug] + [entry]
    epj.write_text(json.dumps(episodes, indent=2, ensure_ascii=False) + "\n")
    for f in stale:
        if f.exists(): f.unlink(); print("removed replaced MP3", f.name)
    site_files(cfg, repo); write_feed(cfg, repo, episodes)
    commit_push(repo, f"Publish episode {slug}", not a.no_push)
    base = cfg["base_url"].rstrip("/")
    print("Feed:", base + "/feed.xml"); print("Episode:", base + "/episodes/" + fname)
    if a.wait and not a.no_push:
        wait_live(cfg, fname, entry["length"])

if __name__ == "__main__":
    main()
