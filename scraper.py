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
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CommunityRadioRadar/1.0)"}
OUTPUT_FILE = Path(__file__).parent / "charts.json"


def fetch(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=20) as r:
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

    headings = re.findall(r'<h1[^>]*>([^<]+)</h1>', html)

    skip_words = ["triple r", "soundscape", "melbourne", "explore",
                  "subscribe", "102.7", "sign in", "shop", "on demand"]

    tracks = []
    for h in headings:
        h = h.strip()
        if any(s in h.lower() for s in skip_words):
            continue
        if " - " not in h:
            continue
        artist, rest = h.split(" - ", 1)
        label_m = re.search(r'\(([^)]+)\)\s*$', rest)
        album = rest[:label_m.start()].strip() if label_m else rest.strip()
        label = label_m.group(1).strip() if label_m else ""
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
    with urllib.request.urlopen(req, timeout=20) as r:
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


def main():
    print("Community Radio Radar - Chart Scraper")
    print("=" * 40)

    results = {}
    errors = {}

    scrapers = {
        "triple_r": scrape_triple_r,
        "rtrfm":    scrape_rtrfm,
        "three_d":  scrape_three_d,
        "zzz":      scrape_4zzz,
        "fbi":      scrape_fbi,
        "twoxx":    scrape_2xx,
    }

    for key, fn in scrapers.items():
        try:
            data = fn()
            results[key] = data
            print("    OK: " + str(len(data['tracks'])) + " tracks")
        except Exception as e:
            print("    FAILED: " + str(e))
            errors[key] = str(e)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "charts": results,
        "errors": errors
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("")
    print("Done! charts.json written to: " + str(OUTPUT_FILE))
    if errors:
        print("Stations with errors: " + ", ".join(errors.keys()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
