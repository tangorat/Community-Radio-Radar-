#!/usr/bin/env python3
"""
Community Radio Radar - Backend Server
Serves charts.json to the frontend and runs the scraper on a daily schedule.

Usage:
  pip install flask apscheduler
  python3 server.py

The frontend should fetch: GET /charts
CORS is enabled so the HTML file can call it from any origin.
"""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
CHARTS_FILE = Path(__file__).parent / "charts.json"
SCRAPER_FILE = Path(__file__).parent / "scraper.py"
AMRAP_FILE   = Path(__file__).parent / "amrap.json"
ART_DIR      = Path(__file__).parent / "amrap_art"
_amrap_lock  = threading.Lock()


def download_artwork(url, dest_path):
    """Download an image from url and save to dest_path. Returns True on success."""
    import urllib.request
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RadioRadar/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            dest_path.write_bytes(resp.read())
        return True
    except Exception as e:
        print(f"  artwork download failed ({dest_path.name}): {e}")
        return False


def scrape_amrap():
    """Scrape the AMRAP Metro Airplay Chart via their JSON API and cache artwork locally."""
    print(f"[{datetime.now().isoformat()}] Scraping AMRAP Metro chart...")
    try:
        import urllib.request

        # --- Fetch chart data ---
        req = urllib.request.Request(
            "https://amrap.org.au/api/charts/weekly",
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; RadioRadar/1.0)",
                "Accept": "application/json",
                "Referer": "https://amrap.org.au/charts"
            }
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        metro   = data.get("charts", {}).get("metro", {})
        entries = metro.get("entries", [])

        # --- Ensure artwork directory exists ---
        ART_DIR.mkdir(exist_ok=True)

        # --- Build track list, downloading artwork as we go ---
        tracks = []
        for entry in entries[:10]:
            track    = entry.get("track", {})
            album    = track.get("album") or {}
            rank     = str(entry.get("position", ""))
            s3_url   = album.get("artwork_url", "")

            # Save artwork as metro_1.png … metro_10.png
            local_filename = f"metro_{rank}.png"
            local_path     = ART_DIR / local_filename

            if s3_url:
                # Always re-download on scrape so art stays current with the chart
                ok = download_artwork(s3_url, local_path)
                img_src = f"/amrap_art/{local_filename}" if ok else s3_url
            else:
                img_src = ""

            tracks.append({
                "rank":      rank,
                "title":     track.get("title", ""),
                "artist":    track.get("artist", ""),
                "imgSrc":    img_src,
                "remoteImg": s3_url,
            })

        if tracks:
            result = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "chart_title":  metro.get("chart_name", "Community Radio Metro Airplay Chart"),
                "week_range":   metro.get("week_range", ""),
                "source_url":   "https://amrap.org.au/charts",
                "tracks":       tracks
            }
            with _amrap_lock:
                with open(AMRAP_FILE, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"AMRAP: scraped {len(tracks)} metro tracks, artwork saved to {ART_DIR}")
        else:
            print("AMRAP: no tracks found in API response")

    except Exception as e:
        print(f"AMRAP scrape failed: {e}")


@app.route("/")
def index():
    """Serve the main HTML app."""
    return send_from_directory(Path(__file__).parent, "community-radio-radar.html")

@app.route("/manifest.json")
def manifest():
    return send_from_directory(Path(__file__).parent, "manifest.json")

@app.route("/service-worker.js")
def service_worker():
    resp = send_from_directory(Path(__file__).parent, "service-worker.js")
    resp.headers['Service-Worker-Allowed'] = '/'
    return resp

@app.route("/icons/<filename>")
def icons(filename):
    return send_from_directory(Path(__file__).parent / "icons", filename)


@app.route("/amrap")
def get_amrap():
    """Return the latest AMRAP Metro chart data."""
    if not AMRAP_FILE.exists():
        threading.Thread(target=scrape_amrap, daemon=True).start()
        return jsonify({"error": "AMRAP data not yet available, scraping now..."}), 503
    with _amrap_lock:
        with open(AMRAP_FILE) as f:
            data = json.load(f)
    return jsonify(data)


@app.route("/amrap_art/<filename>")
def serve_amrap_art(filename):
    """Serve locally cached AMRAP artwork images."""
    return send_from_directory(ART_DIR, filename)


def run_scraper():
    """Run the scraper and update charts.json."""
    print(f"[{datetime.now().isoformat()}] Running scraper...")
    try:
        result = subprocess.run(
            [sys.executable, str(SCRAPER_FILE)],
            capture_output=True,
            text=True,
            timeout=120
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"Scraper errors: {result.stderr}")
    except Exception as e:
        print(f"Scraper failed: {e}")


@app.after_request
def add_cors(response):
    """Allow any origin to call this API."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/charts")
def get_charts():
    """Return the latest charts data."""
    if not CHARTS_FILE.exists():
        return jsonify({"error": "Charts not yet generated. Try again shortly."}), 503
    with open(CHARTS_FILE) as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/scrape", methods=["POST"])
def trigger_scrape():
    """Manually trigger a scrape (useful for testing)."""
    run_scraper()
    return jsonify({"status": "ok", "message": "Scrape complete"})


@app.route("/health")
def health():
    charts_age = None
    if CHARTS_FILE.exists():
        mtime = CHARTS_FILE.stat().st_mtime
        charts_age = f"{(datetime.now().timestamp() - mtime) / 3600:.1f} hours ago"
    return jsonify({
        "status": "ok",
        "charts_file_exists": CHARTS_FILE.exists(),
        "charts_last_updated": charts_age
    })


if __name__ == "__main__":
    # Run scrapers immediately on startup if data is missing
    if not CHARTS_FILE.exists():
        print("No charts.json found — running initial scrape...")
        run_scraper()
    if not AMRAP_FILE.exists():
        print("No amrap.json found — scraping AMRAP Metro chart...")
        threading.Thread(target=scrape_amrap, daemon=True).start()

    # Schedule daily scrapes at 6am AEST (UTC+10 = 20:00 UTC)
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scraper,    "cron", hour=20, minute=0)
    scheduler.add_job(scrape_amrap,   "cron", hour=20, minute=5)
    scheduler.start()
    print("Scheduler started — scraping daily at 6am AEST")

    # Start the server
    port = int(os.environ.get("PORT", 5000))
    print(f"Server running on http://localhost:{port}")
    print(f"  GET  /              → main app (community-radio-radar.html)")
    print(f"  GET  /charts        → chart data")
    print(f"  POST /scrape        → trigger manual scrape")
    print(f"  GET  /health        → status check")
    print(f"  GET  /amrap         → AMRAP metro chart")
    print(f"  GET  /amrap_art/<f> → local artwork images")
    app.run(host="0.0.0.0", port=port)
