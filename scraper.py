#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Community Radio Radar - Chart Scraper
Scrapes weekly music data from:
  - Triple R  (Soundscape page)
  - RTRFM     (Featured Music page)
  - Three D   (Top 20+1 chart)
Outputs: charts.json in the same folder as this script
"""

import json
import re
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen, Request

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CommunityRadioRadar/1.0)"}
OUTPUT_FILE = Path(__file__).parent / "charts.json"

# SSL context — verified by default (safe for server use).
# Pass --insecure flag when running locally on a dev machine whose system
# cert store doesn't carry all intermediate CAs (e.g. Windows + Python).
_INSECURE = "--insecure" in sys.argv
if _INSECURE:
    _SSL_CTX = ssl.create_default_context()
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE
    print("WARNING: SSL verification disabled (--insecure flag)")
else:
    try:
        import certifi
        _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        _SSL_CTX = ssl.create_default_context()


def fetch(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=20, context=_SSL_CTX) as r:
        return r.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# ARTWORK HELPERS
# ---------------------------------------------------------------------------

def _itunes_art(artist, track, size=200):
    """Fetch album artwork URL from iTunes Search API. Returns '' on failure."""
    try:
        q   = quote(f"{artist} {track}")
        url = f"https://itunes.apple.com/search?term={q}&entity=song&limit=1&country=AU"
        data = json.loads(fetch(url))
        results = data.get("results", [])
        if results:
            art = results[0].get("artworkUrl100", "")
            if art:
                return art.replace("100x100bb", f"{size}x{size}bb")
    except Exception:
        pass
    return ""


def _enrich_artwork(tracks, workers=8, delay=0.05):
    """
    Add imgSrc to each track dict by querying iTunes.
    Uses a thread pool to fetch in parallel.
    Skips tracks that already have imgSrc set.
    """
    to_fetch = [(i, t) for i, t in enumerate(tracks) if not t.get("imgSrc")]
    if not to_fetch:
        return tracks

    def _fetch_one(args):
        i, t = args
        art = _itunes_art(t.get("artist", ""), t.get("track", "") or t.get("album", ""))
        time.sleep(delay)
        return i, art

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, arg): arg for arg in to_fetch}
        for future in as_completed(futures):
            try:
                i, art = future.result()
                tracks[i]["imgSrc"] = art
            except Exception:
                pass

    return tracks


# ---------------------------------------------------------------------------
# TRIPLE R - Soundscape (weekly featured albums)
# Page: https://www.rrr.org.au/explore/soundscape
# Each album listed as an <h1> tag: "Artist - Album (Label)"
# ---------------------------------------------------------------------------

def scrape_triple_r():
    print("  Triple R: fetching soundscape index...")
    index = fetch("https://www.rrr.org.au/explore/soundscape")

    links = re.findall(r'href="(/explore/soundscape/triple-r-soundscape-[^"]+)"', index)
    if not links:
        raise ValueError("No soundscape links found on index page")

    url = "https://www.rrr.org.au" + links[0]
    print("  Triple R: fetching " + url)
    html = fetch(url)

    m = re.search(r"Triple R Soundscape:\s*([\w\s]+\d{4})", html)
    chart_date = m.group(1).strip() if m else "This week"

    # Entries live in <h1><strong>Artist - Album (Label) ***note</strong></h1>
    # Use strong tag content to get the full entry text
    headings = re.findall(r'<strong[^>]*class="inline--bold"[^>]*>([^<]+)</strong>', html)
    if not headings:
        # Fallback: any strong inside h1
        headings = re.findall(r'<h1[^>]*>[\s\S]*?<strong[^>]*>([^<]+)</strong>', html)
    if not headings:
        # Last resort: bare h1 content
        headings = re.findall(r'<h1[^>]*>([^<]+)</h1>', html)

    skip_words = ["triple r", "soundscape", "melbourne", "explore",
                  "subscribe", "102.7", "sign in", "shop", "on demand",
                  "donation", "double your"]

    tracks = []
    for h in headings:
        h = h.strip()
        # Strip trailing notes like ***AOTW
        h = re.sub(r'\s*\*+\w*\s*$', '', h).strip()
        if any(s in h.lower() for s in skip_words):
            continue
        if " - " not in h:
            continue
        artist, rest = h.split(" - ", 1)
        label_m = re.search(r'\(([^)]+)\)\s*$', rest)
        album = rest[:label_m.start()].strip() if label_m else rest.strip()
        label = label_m.group(1).strip() if label_m else ""
        if not artist.strip() or not album.strip():
            continue
        tracks.append({
            "rank": len(tracks) + 1,
            "artist": artist.strip(),
            "track": album,
            "label": label,
            "type": "featured_album"
        })
        if len(tracks) >= 15:
            break

    print("  Triple R: fetching artwork...")
    _enrich_artwork(tracks)
    return {
        "station": "VIC",
        "chart_title": "Triple R Soundscape",
        "chart_subtitle": "Weekly featured releases - " + chart_date,
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "tracks": tracks
    }


# ---------------------------------------------------------------------------
# RTRFM - Featured Music (weekly picks)
# Page: https://rtrfm.com.au/featured-music/
# ---------------------------------------------------------------------------

def scrape_rtrfm():
    print("  RTRFM: fetching featured music index...")
    index = fetch("https://rtrfm.com.au/featured-music/")

    links = re.findall(r'href="(https://rtrfm\.com\.au/featured-music/rtrfm-feature[^"]+)"', index)
    if not links:
        links = re.findall(r'href="(/featured-music/rtrfm-feature[^"]+)"', index)
        links = ["https://rtrfm.com.au" + l for l in links]
    if not links:
        raise ValueError("No featured music links found on RTRFM index")

    url = links[0]
    print("  RTRFM: fetching " + url)
    html = fetch(url)

    m = re.search(r'rtrfm-features?-edition-(.+?)(?:/|$)', url)
    chart_date = m.group(1).replace("-", " ").title() if m else "This week"

    tracks = []

    feature_blocks = re.findall(
        r'<h4[^>]*>\s*([A-Z][^<]{2,80}?)\s*</h4>\s*<p[^>]*>\s*([^<]{3,60}?)\s*[bullet].*?FEATURE.*?</p>',
        html, re.IGNORECASE
    )
    for title, artist in feature_blocks[:3]:
        tracks.append({
            "rank": len(tracks) + 1,
            "artist": artist.strip().title(),
            "track": title.strip().title(),
            "label": "RTRFM Feature",
            "type": "feature_album"
        })

    sound_blocks = re.findall(
        r'<h4[^>]*>\s*([A-Z][^<]{2,80}?)\s*</h4>[\s\S]{0,400}?BY\s+([^<\n]{3,50})[\s\S]{0,200}?<p[^>]*>\s*([^<]{2,60}?)\s*</p>',
        html, re.IGNORECASE
    )
    for track, artist, album in sound_blocks[:15]:
        if any(s in track.lower() for s in ["listen", "donate", "subscribe"]):
            continue
        tracks.append({
            "rank": len(tracks) + 1,
            "artist": artist.strip().title(),
            "track": track.strip().title(),
            "label": album.strip().title(),
            "type": "sound_selection"
        })

    if len(tracks) < 2:
        all_h4 = re.findall(r'<h4[^>]*>\s*([A-Z][A-Z\s\'\-&,\.]{3,60})\s*</h4>', html)
        all_by = re.findall(r'BY\s+([A-Z][A-Z\s\'\-&,\.]{2,40})', html)
        for t, a in zip(all_h4[:12], all_by[:12]):
            tracks.append({
                "rank": len(tracks) + 1,
                "artist": a.strip().title(),
                "track": t.strip().title(),
                "label": "",
                "type": "sound_selection"
            })

    print("  RTRFM: fetching artwork...")
    _enrich_artwork(tracks)
    return {
        "station": "WA",
        "chart_title": "RTRFM Featured Music",
        "chart_subtitle": "This week's picks - " + chart_date,
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "tracks": tracks
    }


# ---------------------------------------------------------------------------
# THREE D RADIO - Top 20+1 (weekly airplay chart)
# Page: https://threedradio.com/chart-category/top-20-1/
# Format after stripping HTML: "#0 ARTIST-Track-Local-New"
# ---------------------------------------------------------------------------

def scrape_three_d():
    print("  Three D: fetching chart index...")
    index = fetch("https://threedradio.com/chart-category/top-20-1/")

    links = re.findall(r'href="(https://threedradio\.com/chart/[^"]+)"', index)
    if not links:
        raise ValueError("No chart links found on Three D index")

    url = links[0]
    print("  Three D: fetching " + url)
    html = fetch(url)

    m = re.search(r'[Ww]eek [Ee]nding\s+([\d/\-\.]+)', html)
    chart_date = m.group(1) if m else "This week"

    # Parse each <li> individually - each contains "#N ARTIST-Track-Origin-LastWeek"
    tracks = []
    li_blocks = re.findall(r'<li[^>]*>([\s\S]*?)</li>', html)
    for block in li_blocks:
        text = re.sub(r'<[^>]+>', '', block)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
        text = re.sub(r'\s+', ' ', text).strip()
        if not re.match(r'#\d+', text):
            continue
        text = re.sub(r'^#\d+\s*', '', text).strip()
        m = re.match(r'(.+)-(Local|Australian|International|New Zealand)-(\S+)$', text, re.IGNORECASE)
        if not m:
            continue
        artist_track, origin, last_week = m.groups()
        # Artist is all-caps, track follows after first hyphen
        parts = artist_track.split('-', 1)
        if len(parts) != 2:
            continue
        artist, track = parts
        tracks.append({
            "rank": len(tracks) + 1,
            "artist": artist.strip().title(),
            "track": track.strip().title(),
            "label": origin.strip().title(),
            "last_week": last_week,
            "type": "chart"
        })
        if len(tracks) >= 21:
            break

    print("  Three D: fetching artwork...")
    _enrich_artwork(tracks)
    return {
        "station": "SA",
        "chart_title": "Three D Radio Top 20+1",
        "chart_subtitle": "Week ending " + chart_date,
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "tracks": tracks
    }


# ---------------------------------------------------------------------------
# 4ZZZ - The Chart Show (weekly top 20 most played)
# Page: https://4zzz.org.au/program/the-chart-show
# Structure: <div class="track"> with spans for artist, title, release, locality
# ---------------------------------------------------------------------------

def scrape_4zzz():
    print("  4ZZZ: fetching chart show...")
    # The index page redirects to the latest episode automatically
    # We follow the redirect and use whatever URL we land on
    import urllib.request
    req = urllib.request.Request(
        "https://4zzz.org.au/program/the-chart-show",
        headers=HEADERS
    )
    with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as r:
        url = r.url  # final URL after redirect
        html = r.read().decode("utf-8", errors="replace")
    print("  4ZZZ: landed on " + url)

    # Extract date from URL: /program/the-chart-show/2026-02-27%2018:00:00/
    date_m = re.search(r'/(\d{4}-\d{2}-\d{2})', url)
    chart_date = date_m.group(1) if date_m else "This week"

    # Each track is a <div class="track"> containing:
    # <span class="track-artist">, <span class="track-title">,
    # <span class="track-release">, <span class="track-locality">
    track_divs = re.findall(r'<div[^>]*class="[^"]*track[^"]*"[^>]*>([\s\S]*?)</div>', html)

    tracks = []
    for div in track_divs:
        artist_m = re.search(r'<span[^>]*class="track-artist"[^>]*>([^<]+)</span>', div)
        title_m  = re.search(r'<span[^>]*class="track-title"[^>]*>([^<]+)</span>', div)
        local_m  = re.search(r'<span[^>]*class="track-locality"[^>]*>([^<]+)</span>', div)
        release_m = re.search(r'<span[^>]*class="track-release"[^>]*>([^<]+)</span>', div)

        if not artist_m or not title_m:
            continue

        artist = artist_m.group(1).strip()
        track  = title_m.group(1).strip()
        locality = local_m.group(1).strip() if local_m else ""
        release = release_m.group(1).strip() if release_m else ""

        if not artist or not track:
            continue

        def unescape(s):
            return s.replace("&amp;", "&").replace("&#x27;", "'").replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')

        tracks.append({
            "rank": len(tracks) + 1,
            "artist": unescape(artist),
            "track": unescape(track),
            "label": unescape(release),
            "locality": locality,
            "type": "chart"
        })

        if len(tracks) >= 20:
            break

    print("  4ZZZ: fetching artwork...")
    _enrich_artwork(tracks)
    return {
        "station": "QLD",
        "chart_title": "4ZZZ Chart Show",
        "chart_subtitle": "Top 20 most played - " + chart_date,
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "tracks": tracks
    }


# ---------------------------------------------------------------------------
# FBI RADIO - The Playlist (weekly new releases)
# Page: https://www.fbi.radio/programs/the-playlist
# Structure: tracklist blocks with timestamp, artist, optional state, track
# ---------------------------------------------------------------------------

def scrape_fbi():
    print("  FBI: fetching playlist index...")
    index = fetch("https://www.fbi.radio/programs/the-playlist")

    # Find most recent episode link
    # Links look like: /programs/the-playlist/episodes/the-playlist-6th-february-2026
    links = re.findall(r'href="(/programs/the-playlist/episodes/[^"]+)"', index)
    if not links:
        raise ValueError("No playlist episode links found on FBI index")

    url = "https://www.fbi.radio" + links[0]
    print("  FBI: fetching " + url)
    html = fetch(url)

    # Extract date from page title e.g. "06.02.26"
    date_m = re.search(r'(\d{2}\.\d{2}\.\d{2,4})', html)
    chart_date = date_m.group(1) if date_m else "This week"

    # Strip HTML and split into lines, then group by timestamp blocks
    # Each track block: timestamp, artist, [state], track title, [state]
    raw = re.sub(r'<[^>]+>', '\n', html)
    lines = [l.strip() for l in raw.split('\n') if l.strip()]

    # Australian state/territory labels to filter out
    states = {'NSW', 'VIC', 'QLD', 'WA', 'SA', 'TAS', 'NT', 'ACT', 'Australia', 'LOCAL', 'AUS'}
    timestamp_re = re.compile(r'^\d{2}:\d{2}:\d{2}$')

    tracks = []
    i = 0
    while i < len(lines):
        if timestamp_re.match(lines[i]):
            # Collect lines until next timestamp
            block = []
            i += 1
            while i < len(lines) and not timestamp_re.match(lines[i]):
                block.append(lines[i])
                i += 1
            # Filter out state labels and skip interview blocks
            content = [l for l in block if l not in states and len(l) > 1]
            if any('interview' in l.lower() for l in content):
                continue
            if len(content) >= 2:
                artist = content[0]
                track  = content[1]
                # Skip nav/boilerplate
                if any(s in artist.lower() for s in ['schedule', 'explore', 'support', 'volunteer', 'newsletter']):
                    continue
                def unescape(s):
                    return s.replace("&amp;", "&").replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
                tracks.append({
                    "rank": len(tracks) + 1,
                    "artist": unescape(artist),
                    "track": unescape(track),
                    "label": "",
                    "type": "playlist"
                })
                if len(tracks) >= 25:
                    break
        else:
            i += 1

    print("  FBI: fetching artwork...")
    _enrich_artwork(tracks)
    return {
        "station": "NSW",
        "chart_title": "FBI Radio The Playlist",
        "chart_subtitle": "Weekly new releases - " + chart_date,
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "tracks": tracks
    }



# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

# 2XX FM - Aus Music Hour
# Page: https://www.2xxfm.org.au/shows/aus-music-hour/
# Structure: timestamped playlist with "Track – Artist" format
# ---------------------------------------------------------------------------

def scrape_2xx():
    print("  2XX: fetching Aus Music Hour...")
    html = fetch("https://www.2xxfm.org.au/shows/aus-music-hour/")

    # Extract date from most recent episode heading
    date_m = re.search(r'Aus Music Hour\s*[–-]\s*([\d\-]+)', html)
    chart_date = date_m.group(1) if date_m else "This week"

    # Strip HTML tags and parse lines
    raw = re.sub(r'<[^>]+>', '\n', html)
    lines = [l.strip() for l in raw.split('\n') if l.strip()]

    # Tracks appear as "HH:MM  HH:MM  Track – Artist" pairs after timestamps
    # Find the first episode block (lines after first date heading)
    timestamp_re = re.compile(r'^\d{1,2}:\d{2}$')
    skip_terms = ['aus music hour', 'listen to', 'latest episodes', 'amrap', 'schedule',
                  'explore', 'support', 'donate', 'volunteer', 'newsletter', 'home', 'shows']

    tracks = []
    seen = set()
    in_episode = False

    for i, line in enumerate(lines):
        # Start capturing after the first timestamp
        if timestamp_re.match(line):
            in_episode = True
            continue

        if not in_episode:
            continue

        # Stop if we've hit a second episode date
        if re.match(r'^\d+ \w+ \d{4}', line) and tracks:
            break

        # Skip boilerplate
        if any(t in line.lower() for t in skip_terms):
            continue

        # Tracks are formatted as "Title – Artist"
        if ' – ' in line:
            parts = line.split(' – ', 1)
            track = parts[0].strip()
            artist = parts[1].strip()
            key = (track.lower(), artist.lower())
            if key not in seen and len(track) > 1 and len(artist) > 1:
                seen.add(key)
                tracks.append({
                    "rank": len(tracks) + 1,
                    "artist": artist,
                    "track": track,
                    "label": "",
                    "type": "playlist"
                })
            if len(tracks) >= 25:
                break

    print("  2XX: fetching artwork...")
    _enrich_artwork(tracks)
    return {
        "station": "ACT",
        "chart_title": "2XX Aus Music Hour",
        "chart_subtitle": "Recent Australian independent music - " + chart_date,
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": "https://www.2xxfm.org.au/shows/aus-music-hour/",
        "tracks": tracks
    }


# ---------------------------------------------------------------------------
# BANDCAMP DAILY
# Sources:
#   1. Album of the Day  — scraped from homepage (uses _2.jpg images)
#   2. Essential Releases — latest article from /essential-releases index
# ---------------------------------------------------------------------------

def _parse_bc_aotd_title(raw):
    """Split 'Artist, "Album"' title string into (artist, album)."""
    # Replace Unicode replacement chars (encoding artefact) with plain quote
    raw = raw.replace('�', '"').replace('“', '"').replace('”', '"') \
             .replace('‘', "'").replace('’', "'") \
             .replace('&amp;', '&').replace('&#39;', "'").replace('&quot;', '"')
    # Pattern: Artist Name, "Album Title"
    m = re.match(r'^(.+?),\s*["\'](.+)["\']$', raw.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Fallback: split on first comma
    parts = raw.split(',', 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip().strip('"\'')
    return raw.strip(), ''


def scrape_bandcamp_daily():
    tracks = []

    # ── 1. Album of the Day (homepage) ───────────────────────────────────────
    print("  Bandcamp Daily: fetching homepage for AOTD...")
    homepage = fetch("https://daily.bandcamp.com/")

    # AOTD images use _2.jpg suffix; other article thumbnails use _150.jpg.
    # Find paired (image, title) where image precedes the title-wrapper.
    aotd_pairs = re.findall(
        r'<img src="(https://f4\.bcbits\.com/img/[^"]+_2\.jpg)"'
        r'[\s\S]*?class="title-wrapper"><a[^>]*>([^<]+)</a>',
        homepage)

    for img, raw_title in aotd_pairs[:5]:
        artist, album = _parse_bc_aotd_title(raw_title)
        if not artist:
            continue
        tracks.append({
            "rank":   len(tracks) + 1,
            "artist": artist,
            "track":  "",
            "album":  album,
            "label":  "Album of the Day",
            "imgSrc": img,
            "type":   "editorial"
        })

    # ── 2. Essential Releases (latest article) ───────────────────────────────
    print("  Bandcamp Daily: fetching Essential Releases index...")
    index = fetch("https://daily.bandcamp.com/essential-releases")

    links = re.findall(
        r'href="(/essential-releases/essential-releases-[^"]+)"', index)
    links = list(dict.fromkeys(links))  # deduplicate preserving order

    if links:
        er_url = "https://daily.bandcamp.com" + links[0]
        print("  Bandcamp Daily: fetching " + er_url)
        article = fetch(er_url)

        # h3 tags contain artist+album concatenated: "Aho SsanThe Sun Turned Black"
        h3_raw = re.findall(r'<h3[^>]*>([\s\S]*?)</h3>', article)
        h3s = [re.sub(r'<[^>]+>', '', h).strip() for h in h3_raw]
        h3s = [h for h in h3s if h and len(h) < 100]

        # mplayer-artist blocks give artist name and image (each appears twice)
        mblocks = re.findall(
            r'<mplayer-artist[^>]*>([\s\S]*?)</mplayer-artist>', article)

        seen_names = []
        artist_imgs = {}
        for block in mblocks:
            am = re.search(r'class="artist-name"><a[^>]+>([^<]+)</a>', block)
            im = re.search(
                r'src="(https://f4\.bcbits\.com/img/[^"]+_2\.jpg)"', block)
            if am:
                raw_name = am.group(1).strip()
                name = raw_name.replace('&amp;', '&').replace('&#39;', "'")
                if name not in artist_imgs:
                    seen_names.append(name)
                    artist_imgs[name] = im.group(1) if im else ""

        # Also scrape bandcamp.com/album/ links in the article to get album slugs
        # These give a fallback album title when h3 split is ambiguous
        album_links = re.findall(
            r'href="https://[^"]+\.bandcamp\.com/album/([^"]+)"', article)
        album_from_slug = [
            s.replace('-', ' ').title() for s in album_links if s
        ]

        # Pair h3s with deduplicated artist list; strip artist from front → album
        for idx_e, (h3, artist) in enumerate(zip(h3s, seen_names)):
            h3_clean = h3.replace('&amp;', '&').replace('&#39;', "'")
            if h3_clean.startswith(artist):
                album = h3_clean[len(artist):].strip()
            elif len(album_from_slug) > idx_e:
                # Use slug-derived album name as fallback
                album = album_from_slug[idx_e]
            else:
                album = h3_clean
            tracks.append({
                "rank":   len(tracks) + 1,
                "artist": artist,
                "track":  "",
                "album":  album,
                "label":  "Essential Release",
                "imgSrc": artist_imgs.get(artist, ""),
                "type":   "editorial"
            })
            if len(tracks) >= 15:
                break

    return {
        "station": "Bandcamp Daily",
        "chart_title": "Bandcamp Daily",
        "chart_subtitle": "AOTD & Essential Releases",
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": "https://daily.bandcamp.com/",
        "type": "editorial",
        "tracks": tracks
    }


# ---------------------------------------------------------------------------
# PITCHFORK - Best New Music (BNM)
# API: https://pitchfork.com/api/v2/reviews/albums/?types=bnm&limit=10
# ---------------------------------------------------------------------------

def scrape_pitchfork_bnm():
    print("  Pitchfork BNM: fetching page...")
    url  = "https://pitchfork.com/reviews/best/albums/"
    html = fetch(url)

    # Strip scripts/styles then extract text lines.
    # Pattern after stripping: Genre → Album Title → Artist → Reviewer → Date (repeating)
    raw = re.sub(r'<style[\s\S]*?</style>', '', html)
    raw = re.sub(r'<script[\s\S]*?</script>', '', raw)
    raw = re.sub(r'<[^>]+>', '\n', raw)
    lines = [l.strip() for l in raw.split('\n') if l.strip() and len(l.strip()) > 1]

    GENRES = {
        'Electronic', 'Folk/Country', 'Experimental', 'Rap', 'Rock', 'Pop/R&B',
        'Jazz', 'Metal', 'Classical', 'Global', 'Reissue', 'Alternative/Indie',
        'Country', 'R&B/Soul', 'Latin', 'Dance', 'Ambient'
    }
    SKIP = {
        'Best New Albums', 'Best New Reissues', '8.0+ reviews', 'Sunday Reviews',
        'Tracks', 'Albums', 'Skip to main content', 'Open Navigation Menu',
        'Menu', 'Newsletter', 'Search', 'News', 'Reviews', 'Best New Music',
        'Features', 'Lists', 'Columns', 'Video', 'All rights reserved',
    }

    # Extract images before stripping — deduplicate by photo ID, keep 1:1 ratio
    all_img_urls = re.findall(
        r'https://media\.pitchfork\.com/photos/[a-f0-9]+/1:1/[^\s"\'&<]+', html)
    seen_pids = set(); pitchfork_imgs = []
    for img_url in all_img_urls:
        pid = re.search(r'/photos/([a-f0-9]+)/', img_url)
        if pid and pid.group(1) not in seen_pids:
            seen_pids.add(pid.group(1))
            pitchfork_imgs.append(img_url)
    # First image is often a site-wide header — skip it if hash looks like old site art
    if pitchfork_imgs and '5935a027' in pitchfork_imgs[0]:
        pitchfork_imgs.pop(0)

    tracks = []
    i = 0
    while i < len(lines) and len(tracks) < 12:
        line = lines[i]
        if line in GENRES:
            # Next line = album, line after = artist
            if i + 2 < len(lines):
                album  = lines[i + 1]
                artist = lines[i + 2]
                # Sanity: skip if either looks like nav/boilerplate
                if album not in SKIP and artist not in SKIP and len(album) > 1:
                    img = pitchfork_imgs[len(tracks)] if len(tracks) < len(pitchfork_imgs) else ""
                    tracks.append({
                        "rank":   len(tracks) + 1,
                        "artist": artist,
                        "track":  "",
                        "album":  album,
                        "label":  line,
                        "imgSrc": img,
                        "type":   "editorial"
                    })
                i += 3
                continue
        i += 1

    return {
        "station": "Pitchfork",
        "chart_title": "Best New Music",
        "chart_subtitle": "BNM-rated albums",
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "type": "editorial",
        "tracks": tracks
    }


# ---------------------------------------------------------------------------
# NPR MUSIC - New Music Friday
# Page: https://www.npr.org/sections/allsongs/606254804/new-music-friday
# ---------------------------------------------------------------------------

def scrape_line_of_best_fit():
    print("  Line of Best Fit: fetching new tracks...")
    url  = "https://www.thelineofbestfit.com/new-music"
    html = fetch(url)

    # Images: cdn.craft.cloud 768w srcset - appear in same order as articles
    art_imgs_raw = re.findall(
        r'(https://cdn\.craft\.cloud/[^\s"\']+width=768[^\s"\']*)', html)
    art_imgs = [i.replace("&amp;", "&") for i in art_imgs_raw]

    # Artists: italic span tags appear in same order as articles
    bf_artists = re.findall(r"<span[^>]*class=['\"]italic['\"][^>]*>([^<]+)</span>", html)

    # Pair artist+image, deduplicate by artist
    seen_a = set(); paired_imgs = []; paired_artists = []
    for artist, img in zip(bf_artists, art_imgs):
        if artist not in seen_a:
            seen_a.add(artist)
            paired_artists.append(artist)
            paired_imgs.append(img)

    raw = re.sub(r"<style[\s\S]*?</style>", "", html)
    raw = re.sub(r"<script[\s\S]*?</script>", "", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    lines = [l.strip() for l in raw.splitlines() if l.strip() and len(l.strip()) > 2]

    # Each article is one merged line: "Artist  description with ‘TRACK’ in it"
    # Match lines starting with a known paired artist name, extract quoted track
    QUOTE_RE = re.compile(
        u"[\u2018\u2019\u201c\u201d\'\"](\w[^\u2018\u2019\u201c\u201d\'\"]"
        u"{2,60})[\u2018\u2019\u201c\u201d\'\"]"
    )
    tracks = []
    seen_a = set()
    for artist, img in zip(paired_artists, paired_imgs):
        if artist in seen_a or len(tracks) >= 15:
            break
        for line in lines:
            if not line.startswith(artist):
                continue
            seen_a.add(artist)
            all_m = QUOTE_RE.findall(line)
            track = all_m[-1].strip() if all_m else ""
            tracks.append({
                "rank":   len(tracks) + 1,
                "artist": artist,
                "track":  track,
                "album":  track,
                "label":  "",
                "imgSrc": img,
                "type":   "editorial"
            })
            break

    return {
        "station": "Best Fit",
        "chart_title": "New Tracks",
        "chart_subtitle": "The Line of Best Fit",
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "type": "editorial",
        "tracks": tracks
    }


def scrape_npr_new_music():
    print("  NPR New Music Friday: fetching index...")
    index_url = "https://www.npr.org/sections/allsongs/606254804/new-music-friday"
    index     = fetch(index_url)

    # Find the most recent article link
    links = re.findall(
        r'href="(https://www\.npr\.org/\d{4}/\d{2}/\d{2}/\d+/[^"]+)"',
        index)
    url  = index_url
    html = index
    for link in links[:5]:
        if 'new-music-friday' in link.lower() or 'all-songs' in link.lower():
            try:
                print("  NPR: fetching " + link)
                html = fetch(link)
                url  = link
                break
            except Exception:
                pass

    # NPR articles list picks as "Artist — Album" or bold artist names + album in text
    raw   = re.sub(r'<style[\s\S]*?</style>', '', html)
    raw   = re.sub(r'<script[\s\S]*?</script>', '', raw)
    raw   = re.sub(r'<[^>]+>', '\n', raw)
    lines = [l.strip() for l in raw.split('\n') if l.strip() and len(l.strip()) > 2]

    tracks = []
    seen   = set()
    SKIP   = {'NPR', 'Music', 'Subscribe', 'Newsletter', 'Listen', 'Follow',
              'Skip', 'Navigation', 'Search', 'Home', 'News', 'More'}

    for line in lines:
        # Pattern: "Artist, Album Title" or "Artist — Album"
        m = re.match(r'^([^,\-—]{3,45})[,\-—]\s*[“‘"]?(.{3,70})[”’"]?\s*$', line)
        if m:
            artist = m.group(1).strip()
            album  = m.group(2).strip().strip('"\'')
            # Skip nav boilerplate
            if any(s.lower() in artist.lower() for s in SKIP):
                continue
            if any(s.lower() in album.lower() for s in SKIP):
                continue
            # Skip lines that are clearly dates or metadata
            if re.search(r'\b(20\d\d|January|February|March|April|May|June|July|August|'
                         r'September|October|November|December|Monday|Tuesday|Wednesday|'
                         r'Thursday|Friday|Saturday|Sunday)\b', artist):
                continue
            key = artist.lower()
            if key not in seen and len(artist) > 2:
                seen.add(key)
                tracks.append({
                    "rank":   len(tracks) + 1,
                    "artist": artist,
                    "track":  "",
                    "album":  album,
                    "label":  "",
                    "type":   "editorial"
                })
        if len(tracks) >= 12:
            break

    return {
        "station": "NPR Music",
        "chart_title": "New Music Friday",
        "chart_subtitle": "NPR's weekly picks",
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "type": "editorial",
        "tracks": tracks
    }


# ---------------------------------------------------------------------------
# NACC - North American College & Community Radio Chart
# Page: https://nacc.usc.edu/
# ---------------------------------------------------------------------------

def scrape_nacc():
    import time
    print("  NACC: fetching chart...")

    html = None
    for attempt in range(3):
        try:
            html = fetch("https://nacc.usc.edu/")
            break
        except Exception as e:
            if attempt == 2:
                raise
            print("  NACC: connection failed, retry " + str(attempt + 2))
            time.sleep(4)

    rows   = re.findall(r'<tr[^>]*>([\s\S]*?)</tr>', html)
    tracks = []

    for row in rows:
        cells = re.findall(r'<td[^>]*>([\s\S]*?)</td>', row)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        cells = [c for c in cells if c]
        if len(cells) >= 2 and re.match(r'^\d+$', cells[0]):
            tracks.append({
                "rank":   int(cells[0]),
                "artist": cells[1] if len(cells) > 1 else "",
                "track":  "",
                "album":  cells[2] if len(cells) > 2 else "",
                "label":  cells[3] if len(cells) > 3 else "",
                "type":   "chart"
            })
        if len(tracks) >= 30:
            break

    return {
        "station": "NACC",
        "chart_title": "College Radio Chart",
        "chart_subtitle": "North American College & Community",
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": "https://nacc.usc.edu/",
        "type": "editorial",
        "tracks": tracks
    }


# ---------------------------------------------------------------------------
# UK OFFICIAL INDEPENDENT ALBUMS CHART
# Page: https://www.officialcharts.com/charts/independent-albums-chart/
# ---------------------------------------------------------------------------

def scrape_uk_indie():
    print("  UK Indie Albums: fetching...")
    html = fetch("https://www.officialcharts.com/charts/independent-albums-chart/")

    # The page embeds Apple Music 247x247 cover art — 2 per entry, take every other one
    all_art = re.findall(
        r'src="(https://is\d+-ssl\.mzstatic\.com/[^"]+/247x247bb\.jpg)"', html)
    art_imgs = all_art[::2]  # deduplicate: 2 copies per entry, take first of each pair

    # Page strips to: ... 'Number' → 'N' → movement → 'ALBUM' → 'ARTIST' → metadata ...
    raw   = re.sub(r'<style[\s\S]*?</style>', '', html)
    raw   = re.sub(r'<script[\s\S]*?</script>', '', raw)
    raw   = re.sub(r'<[^>]+>', '\n', raw)
    lines = [l.strip() for l in raw.split('\n') if l.strip()]

    MOVEMENT = re.compile(r'^(New|Re-Entry|Non-Mover|LW:|Peak:|=)$', re.IGNORECASE)

    tracks = []
    i = 0
    while i < len(lines) and len(tracks) < 20:
        if lines[i] == 'Number' and i + 1 < len(lines) and re.match(r'^\d{1,2}$', lines[i + 1]):
            rank = int(lines[i + 1])
            j = i + 2
            while j < len(lines) and MOVEMENT.match(lines[j]):
                j += 1
            album  = lines[j]     if j < len(lines) else ""
            artist = lines[j + 1] if j + 1 < len(lines) else ""
            if album and artist and re.search(r'[A-Za-z]{2,}', album):
                img = art_imgs[len(tracks)] if len(tracks) < len(art_imgs) else ""
                tracks.append({
                    "rank":   rank,
                    "artist": artist,
                    "track":  "",
                    "album":  album,
                    "label":  "",
                    "imgSrc": img,
                    "type":   "chart"
                })
            i = j + 2
            continue
        i += 1

    return {
        "station": "UK Indie Albums",
        "chart_title": "Independent Albums",
        "chart_subtitle": "UK Official Independent Albums Chart",
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": "https://www.officialcharts.com/charts/independent-albums-chart/",
        "type": "editorial",
        "tracks": tracks
    }


def main():
    print("Community Radio Radar - Chart Scraper")
    print("=" * 40)

    results   = {}
    editorial = []
    errors    = {}

    station_scrapers = {
        "triple_r": scrape_triple_r,
        "rtrfm":    scrape_rtrfm,
        "three_d":  scrape_three_d,
        "zzz":      scrape_4zzz,
        "fbi":      scrape_fbi,
        "twoxx":    scrape_2xx,
    }

    editorial_scrapers = [
        ("bandcamp",   scrape_bandcamp_daily),
        ("pitchfork",  scrape_pitchfork_bnm),
        ("best_fit",   scrape_line_of_best_fit),
        ("uk_indie",   scrape_uk_indie),
    ]

    print("\n-- Station Charts --")
    for key, fn in station_scrapers.items():
        try:
            data = fn()
            results[key] = data
            print("    OK: " + str(len(data['tracks'])) + " tracks")
        except Exception as e:
            print("    FAILED: " + str(e))
            errors[key] = str(e)

    print("\n-- Editorial Sources --")
    for key, fn in editorial_scrapers:
        try:
            data = fn()
            editorial.append(data)
            print("    OK (" + key + "): " + str(len(data['tracks'])) + " entries")
        except Exception as e:
            print("    FAILED (" + key + "): " + str(e))
            errors["editorial_" + key] = str(e)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "charts":       results,
        "editorial":    editorial,
        "errors":       errors
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("")
    print("Done! charts.json written to: " + str(OUTPUT_FILE))
    if errors:
        print("Sources with errors: " + ", ".join(errors.keys()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
