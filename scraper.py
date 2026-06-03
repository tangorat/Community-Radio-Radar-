#!/usr/bin/env python3
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
from datetime import datetime, timezone
from pathlib import Path
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

    return {
        "station": "ACT",
        "chart_title": "2XX Aus Music Hour",
        "chart_subtitle": "Recent Australian independent music - " + chart_date,
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_url": "https://www.2xxfm.org.au/shows/aus-music-hour/",
        "tracks": tracks
    }


# ---------------------------------------------------------------------------
# BANDCAMP DAILY - Notable Releases (staff picks)
# Page: https://daily.bandcamp.com/
# ---------------------------------------------------------------------------

def scrape_bandcamp_daily():
    print("  Bandcamp Daily: fetching...")
    html = fetch("https://daily.bandcamp.com/")

    tracks = []
    seen   = set()

    # Page structure: each article has class="title-wrapper" (article title)
    # and class="franchise" (genre category label above it).
    # Extract paired franchise + title from article-info-text blocks.
    blocks = re.findall(
        r'<div[^>]*class="article-info-text"[^>]*>([\s\S]*?)</div>\s*</div>',
        html)

    for block in blocks:
        franchise_m = re.search(r'class="franchise"[^>]*>([^<]+)<', block)
        title_m     = re.search(r'class="title(?:\s[^"]*)??"[^>]*>([^<]+)<', block)
        if not title_m:
            continue
        title     = title_m.group(1).strip()
        franchise = franchise_m.group(1).strip() if franchise_m else "Feature"
        # Skip generic "LISTS" category — too vague
        if franchise.upper() in ('LISTS', 'FEATURES'):
            continue
        key = title.lower()
        if key not in seen and title:
            seen.add(key)
            tracks.append({
                "rank":   len(tracks) + 1,
                "artist": franchise,   # genre/franchise as the "artist" field
                "track":  "",
                "album":  title,
                "label":  "",
                "type":   "editorial"
            })
        if len(tracks) >= 15:
            break

    return {
        "station": "Bandcamp Daily",
        "chart_title": "Bandcamp Daily",
        "chart_subtitle": "Staff picks & features",
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
                    tracks.append({
                        "rank":   len(tracks) + 1,
                        "artist": artist,
                        "track":  "",
                        "album":  album,
                        "label":  line,   # genre as label
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

    raw   = re.sub(r'<style[\s\S]*?</style>', '', html)
    raw   = re.sub(r'<script[\s\S]*?</script>', '', raw)
    raw   = re.sub(r'<[^>]+>', '\n', raw)
    lines = [l.strip() for l in raw.split('\n') if l.strip() and len(l.strip()) > 1]

    SKIP = {'Tracks', 'Albums', 'Features', 'News', 'About', 'Contact',
            'Advertise', 'Newsletter', 'Instagram', 'Search', 'Loading...',
            'The Line', 'Best Fit', 'Close', 'The Line of Best Fit'}
    DATE_RE = re.compile(r'^\d{2}\.\d{2}\.\d{4}')

    tracks = []
    seen   = set()
    i = 0
    while i < len(lines) and len(tracks) < 15:
        line = lines[i]
        if line in SKIP or DATE_RE.match(line):
            i += 1
            continue
        # Check if next line looks like a track description (contains apostrophe, quote, or music words)
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            if (len(line) <= 50 and len(nxt) > 20 and
                    (nxt.startswith('‘') or nxt.startswith('"') or nxt.startswith("'") or
                     "'" in nxt or '’' in nxt) and
                    line not in seen):
                # Extract track name from description (usually in quotes)
                track_m = re.search(r'[‘“’”\'"]([\w][^\'\"]{3,60})[‘“’”\']', nxt)
                track = track_m.group(1).strip() if track_m else ""
                seen.add(line)
                tracks.append({
                    "rank":   len(tracks) + 1,
                    "artist": line,
                    "track":  track,
                    "album":  track,
                    "label":  "",
                    "type":   "editorial"
                })
                i += 2
                continue
        i += 1

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

    # Page strips to: ... 'Number' → 'N' → movement → 'ALBUM' → 'ARTIST' → metadata ...
    raw   = re.sub(r'<style[\s\S]*?</style>', '', html)
    raw   = re.sub(r'<script[\s\S]*?</script>', '', raw)
    raw   = re.sub(r'<[^>]+>', '\n', raw)
    lines = [l.strip() for l in raw.split('\n') if l.strip()]

    MOVEMENT = re.compile(r'^(New|Re-Entry|Non-Mover|LW:|Peak:|=)$', re.IGNORECASE)

    tracks = []
    i = 0
    while i < len(lines) and len(tracks) < 20:
        # Look for the "Number" sentinel followed by a digit
        if lines[i] == 'Number' and i + 1 < len(lines) and re.match(r'^\d{1,2}$', lines[i + 1]):
            rank = int(lines[i + 1])
            # Skip past rank digit and any movement words
            j = i + 2
            while j < len(lines) and MOVEMENT.match(lines[j]):
                j += 1
            album  = lines[j]     if j < len(lines) else ""
            artist = lines[j + 1] if j + 1 < len(lines) else ""
            if album and artist and re.search(r'[A-Za-z]{2,}', album):
                tracks.append({
                    "rank":   rank,
                    "artist": artist,
                    "track":  "",
                    "album":  album,
                    "label":  "",
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
