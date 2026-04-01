import json
import os
import queue
import re
import threading
import time
from datetime import datetime

import requests
from flask import Flask, Response, render_template_string, send_file, request
from PIL import Image
import numpy as np

LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logos")
DITHER_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logos", "dithered")
os.makedirs(DITHER_CACHE_DIR, exist_ok=True)

EINK_PALETTE = np.array([
    [0, 0, 0],        # black
    [255, 255, 255],   # white
    [255, 0, 0],       # red
], dtype=np.float64)

app = Flask(__name__)

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_SUMMARY_URL = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}"
POLL_INTERVAL = 30  # seconds between ESPN API polls
USE_MOCK = os.environ.get("MOCK", "").strip().lower() in ("1", "true", "yes")
MOCK_PRESET = os.environ.get("MOCK_PRESET", "").strip().lower()

LOGO_URL = "https://a.espncdn.com/i/teamlogos/nfl/500/{abbr}.png"

# Stats to display per preset
STATS_SINGLE = [
    "firstDowns", "totalYards", "netPassingYards", "completionAttempts",
    "rushingYards", "rushingAttempts", "turnovers", "interceptions",
    "sacksYardsLost", "thirdDownEff", "totalPenaltiesYards", "possessionTime",
]
STATS_PLAYOFF_2 = ["netPassingYards", "rushingYards", "turnovers", "thirdDownEff"]
STAT_LABELS = {
    "firstDowns": "1st Downs", "totalYards": "Total Yds",
    "netPassingYards": "Pass Yds", "completionAttempts": "Comp/Att",
    "rushingYards": "Rush Yds", "rushingAttempts": "Rush Att",
    "turnovers": "Turnovers", "interceptions": "INTs",
    "sacksYardsLost": "Sacks", "thirdDownEff": "3rd Down",
    "totalPenaltiesYards": "Penalties", "possessionTime": "Possession",
}

_today = datetime.now().strftime("%Y-%m-%d")

MOCK_GAMES = [
    {"id": "m1",  "away_team": "KC",  "home_team": "BUF", "away_score": "21", "home_score": "17",
     "status": "Q3 8:42", "state": "in", "date": _today, "possession": "KC", "down_distance": "2nd & 7", "spot": "BUF 35"},
    {"id": "m2",  "away_team": "DAL", "home_team": "PHI", "away_score": "10", "home_score": "14",
     "status": "Q2 2:01", "state": "in", "date": _today, "possession": "PHI", "down_distance": "1st & 10", "spot": "PHI 25"},
    {"id": "m3",  "away_team": "SF",  "home_team": "SEA", "away_score": "27", "home_score": "24",
     "status": "Final", "state": "post", "date": _today},
    {"id": "m4",  "away_team": "BAL", "home_team": "CIN", "away_score": "31", "home_score": "28",
     "status": "Q4 0:34", "state": "in", "date": _today, "possession": "CIN", "down_distance": "3rd & 8", "spot": "BAL 42"},
    {"id": "m5",  "away_team": "MIA", "home_team": "NE",  "away_score": "3",  "home_score": "7",
     "status": "Q1 11:20", "state": "in", "date": _today, "possession": "MIA", "down_distance": "3rd & 2", "spot": "NE 48"},
    {"id": "m6",  "away_team": "DEN", "home_team": "LV",  "away_score": "17", "home_score": "20",
     "status": "Final/OT", "state": "post", "date": _today},
    {"id": "m7",  "away_team": "NYG", "home_team": "WAS", "away_score": "14", "home_score": "14",
     "status": "Q2 0:12", "state": "in", "date": _today, "possession": "WAS", "down_distance": "2nd & 3", "spot": "NYG 40"},
    {"id": "m8",  "away_team": "LAR", "home_team": "ARI", "away_score": "23", "home_score": "20",
     "status": "Final", "state": "post", "date": _today},
    {"id": "m9",  "away_team": "TB",  "home_team": "NO",  "away_score": "7",  "home_score": "3",
     "status": "Q1 5:44", "state": "in", "date": _today, "possession": "TB", "down_distance": "1st & 10", "spot": "TB 30"},
    {"id": "m10", "away_team": "PIT", "home_team": "CLE", "away_score": "13", "home_score": "10",
     "status": "Halftime", "state": "in", "date": _today},
    {"id": "m11", "away_team": "JAX", "home_team": "TEN", "away_score": "6",  "home_score": "9",
     "status": "Q3 12:00", "state": "in", "date": _today, "possession": "TEN", "down_distance": "3rd & 1", "spot": "JAX 49"},
    {"id": "m12", "away_team": "LAC", "home_team": "HOU", "away_score": "0",  "home_score": "0",
     "status": "8:20 PM", "state": "pre", "date": _today},
    {"id": "m13", "away_team": "GB",  "home_team": "CHI", "away_score": "0",  "home_score": "0",
     "status": "Mon 8:15PM", "state": "pre", "date": "2099-01-01"},
]

MOCK_STATS = {
    "m1": {
        "KC":  {"firstDowns": "18", "totalYards": "342", "netPassingYards": "245", "completionAttempts": "19/27",
                "rushingYards": "97", "rushingAttempts": "22", "turnovers": "1", "interceptions": "1",
                "sacksYardsLost": "2-14", "thirdDownEff": "5/10", "totalPenaltiesYards": "4-30", "possessionTime": "18:22"},
        "BUF": {"firstDowns": "15", "totalYards": "298", "netPassingYards": "201", "completionAttempts": "17/25",
                "rushingYards": "97", "rushingAttempts": "18", "turnovers": "0", "interceptions": "0",
                "sacksYardsLost": "1-8", "thirdDownEff": "4/9", "totalPenaltiesYards": "6-45", "possessionTime": "15:38"},
    },
    "m2": {
        "DAL": {"firstDowns": "8", "totalYards": "156", "netPassingYards": "112", "completionAttempts": "10/18",
                "rushingYards": "44", "rushingAttempts": "12", "turnovers": "1", "interceptions": "1",
                "sacksYardsLost": "3-21", "thirdDownEff": "2/7", "totalPenaltiesYards": "3-25", "possessionTime": "12:15"},
        "PHI": {"firstDowns": "12", "totalYards": "210", "netPassingYards": "148", "completionAttempts": "14/20",
                "rushingYards": "62", "rushingAttempts": "15", "turnovers": "0", "interceptions": "0",
                "sacksYardsLost": "1-6", "thirdDownEff": "5/8", "totalPenaltiesYards": "2-15", "possessionTime": "17:45"},
    },
    "m3": {
        "SF":  {"firstDowns": "22", "totalYards": "385", "netPassingYards": "267", "completionAttempts": "24/33",
                "rushingYards": "118", "rushingAttempts": "28", "turnovers": "1", "interceptions": "0",
                "sacksYardsLost": "2-12", "thirdDownEff": "7/13", "totalPenaltiesYards": "5-40", "possessionTime": "32:10"},
        "SEA": {"firstDowns": "19", "totalYards": "350", "netPassingYards": "230", "completionAttempts": "22/35",
                "rushingYards": "120", "rushingAttempts": "25", "turnovers": "2", "interceptions": "1",
                "sacksYardsLost": "3-18", "thirdDownEff": "6/14", "totalPenaltiesYards": "7-55", "possessionTime": "27:50"},
    },
    "m4": {
        "BAL": {"firstDowns": "24", "totalYards": "410", "netPassingYards": "280", "completionAttempts": "22/30",
                "rushingYards": "130", "rushingAttempts": "26", "turnovers": "0", "interceptions": "0",
                "sacksYardsLost": "1-5", "thirdDownEff": "8/12", "totalPenaltiesYards": "3-20", "possessionTime": "17:30"},
        "CIN": {"firstDowns": "21", "totalYards": "378", "netPassingYards": "298", "completionAttempts": "25/38",
                "rushingYards": "80", "rushingAttempts": "18", "turnovers": "1", "interceptions": "1",
                "sacksYardsLost": "2-10", "thirdDownEff": "6/11", "totalPenaltiesYards": "4-35", "possessionTime": "16:26"},
    },
}


def fetch_game_stats(event_id):
    """Fetch box score statistics for a single game from ESPN summary endpoint."""
    url = ESPN_SUMMARY_URL.format(event_id=event_id)
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    result = {}
    for team_data in data.get("boxscore", {}).get("teams", []):
        abbr = team_data["team"]["abbreviation"]
        stats = {}
        for stat in team_data.get("statistics", []):
            stats[stat["name"]] = stat["displayValue"]
        result[abbr] = stats
    return result


def determine_preset(game_count):
    """Return the display preset based on number of games."""
    if game_count == 1:
        return "single"
    elif game_count == 2:
        return "playoff_2"
    elif game_count == 3:
        return "playoff_3"
    return "sunday"


class MessageAnnouncer:
    """Manages SSE listeners. Each connected browser gets a queue."""

    def __init__(self):
        self.listeners = []

    def listen(self):
        q = queue.Queue(maxsize=5)
        self.listeners.append(q)
        return q

    def announce(self, msg):
        for i in reversed(range(len(self.listeners))):
            try:
                self.listeners[i].put_nowait(msg)
            except queue.Full:
                del self.listeners[i]


announcer = MessageAnnouncer()


def parse_games(data):
    """Extract game info from ESPN API response."""
    games = []
    for event in data.get("events", []):
        comp = event["competitions"][0]
        # ESPN lists home team first (index 0), away second (index 1)
        home = comp["competitors"][0]
        away = comp["competitors"][1]

        status_obj = event["status"]
        status_detail = status_obj["type"]["shortDetail"]
        status_state = status_obj["type"]["state"]  # pre, in, post

        # Extract date (YYYY-MM-DD) from the event's UTC timestamp
        event_date = event.get("date", "")[:10]

        game = {
            "id": event["id"],
            "away_team": away["team"]["abbreviation"],
            "away_name": away["team"]["shortDisplayName"],
            "home_team": home["team"]["abbreviation"],
            "home_name": home["team"]["shortDisplayName"],
            "away_score": away["score"],
            "home_score": home["score"],
            "away_logo": away["team"]["logo"],
            "home_logo": home["team"]["logo"],
            "status": status_detail,
            "state": status_state,
            "date": event_date,
        }

        # Add possession indicator if game is in progress
        if status_state == "in":
            situation = comp.get("situation", {})
            possession_id = situation.get("possession")
            game["possession"] = None
            if possession_id:
                for team in comp["competitors"]:
                    if team["team"]["id"] == possession_id:
                        game["possession"] = team["team"]["abbreviation"]
            game["down_distance"] = situation.get("shortDownDistanceText", "")
            game["spot"] = situation.get("possessionText", "")

        games.append(game)
    return games


def dither_to_tricolor(img, size):
    """Floyd-Steinberg dither an image down to black/white/red at the given size."""
    img = img.convert("RGBA")
    # Composite onto white background
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    bg.paste(img, mask=img)
    img = bg.convert("RGB").resize((size, size), Image.LANCZOS)

    pixels = np.array(img, dtype=np.float64)
    h, w = pixels.shape[:2]

    for y in range(h):
        for x in range(w):
            old = pixels[y, x].copy()
            # Find nearest palette color
            dists = np.sum((EINK_PALETTE - old) ** 2, axis=1)
            nearest = EINK_PALETTE[np.argmin(dists)]
            pixels[y, x] = nearest
            error = old - nearest
            # Distribute error to neighbors
            if x + 1 < w:
                pixels[y, x + 1] += error * 7 / 16
            if y + 1 < h:
                if x - 1 >= 0:
                    pixels[y + 1, x - 1] += error * 3 / 16
                pixels[y + 1, x] += error * 5 / 16
                if x + 1 < w:
                    pixels[y + 1, x + 1] += error * 1 / 16

    result = np.clip(pixels, 0, 255).astype(np.uint8)
    return Image.fromarray(result)


@app.route("/logo/<abbr>")
def logo(abbr):
    """Serve a tricolor-dithered team logo. Cached to disk after first request."""
    size = request.args.get("size", 64, type=int)
    size = min(max(size, 16), 128)
    abbr = abbr.lower().replace(".png", "")
    cached = os.path.join(DITHER_CACHE_DIR, f"{abbr}_{size}.png")
    if os.path.exists(cached):
        return send_file(cached, mimetype="image/png")

    source = os.path.join(LOGO_DIR, f"{abbr}.png")
    if not os.path.exists(source):
        return "Not found", 404

    img = Image.open(source)
    dithered = dither_to_tricolor(img, size)
    dithered.save(cached, "PNG")
    return send_file(cached, mimetype="image/png")


def game_sort_key(game):
    """Sort key: pre-game today first, then live by most time remaining, then final.

    Returns a tuple (category, time_remaining) where lower = higher on screen.
    category: 0 = pre (today), 1 = in-progress, 2 = post/final
    time_remaining: higher = more time left = closer to top
    """
    state = game.get("state", "")
    status = game.get("status", "")

    if state == "pre":
        return (0, 0)

    if state == "post":
        return (2, 0)

    # state == "in": parse quarter and clock from status like "Q3 8:42" or "Halftime"
    quarter_values = {"Q1": 4, "Q2": 3, "Q3": 2, "Q4": 1, "OT": 0}

    if "halftime" in status.lower():
        return (1, -3000)  # Between Q2 (3000-3999) and Q3 (2000-2999)

    match = re.match(r"(Q[1-4]|OT)\s+(\d+):(\d+)", status)
    if match:
        q = quarter_values.get(match.group(1), 0)
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        time_remaining = q * 1000 + minutes * 60 + seconds
        return (1, -time_remaining)

    # Fallback for unrecognized in-progress status
    return (1, 0)


def filter_and_sort_games(games):
    """Remove pre-game entries not scheduled for today, then sort by time remaining."""
    today = datetime.now().strftime("%Y-%m-%d")
    filtered = [
        g for g in games
        if g.get("state") != "pre" or g.get("date", "") == today
    ]
    filtered.sort(key=game_sort_key)
    return filtered


def fetch_scores():
    """Background thread: polls ESPN (or serves mock data) and pushes updates via SSE."""
    while True:
        try:
            if USE_MOCK:
                games = list(MOCK_GAMES)
                # Apply MOCK_PRESET to limit game count for testing
                if MOCK_PRESET == "single":
                    games = games[:1]
                elif MOCK_PRESET == "playoff2":
                    games = games[:2]
                elif MOCK_PRESET == "playoff3":
                    games = games[:3]
            else:
                resp = requests.get(ESPN_URL, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                games = parse_games(data)

            games = filter_and_sort_games(games)
            preset = determine_preset(len(games))

            # Fetch stats for presets that need them
            stat_keys = []
            stat_labels = {}
            if preset == "single":
                stat_keys = STATS_SINGLE
                stat_labels = {k: STAT_LABELS[k] for k in STATS_SINGLE}
            elif preset == "playoff_2":
                stat_keys = STATS_PLAYOFF_2
                stat_labels = {k: STAT_LABELS[k] for k in STATS_PLAYOFF_2}

            if stat_keys:
                for game in games:
                    try:
                        if USE_MOCK:
                            game["stats"] = MOCK_STATS.get(game["id"], {})
                        else:
                            game["stats"] = fetch_game_stats(game["id"])
                    except Exception as e:
                        print(f"[ESPN] Error fetching stats for {game['id']}: {e}")
                        game["stats"] = {}

            payload = {
                "preset": preset,
                "stat_keys": stat_keys,
                "stat_labels": stat_labels,
                "games": games,
            }
            msg = f"event: scores\ndata: {json.dumps(payload)}\n\n"
            announcer.announce(msg)
        except Exception as e:
            print(f"[ESPN] Error fetching scores: {e}")
        time.sleep(POLL_INTERVAL)


@app.route("/stream")
def stream():
    def event_stream():
        messages = announcer.listen()
        while True:
            yield messages.get()

    return Response(event_stream(), mimetype="text/event-stream")


@app.route("/")
def index():
    return render_template_string(TEMPLATE)


TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>NFL Scoreboard</title>
<style>
  :root {
    --black: #000000;
    --white: #FFFFFF;
    --red:   #FF0000;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: #333;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    font-family: 'Courier New', monospace;
  }

  #eink {
    width: 800px;
    height: 480px;
    background: var(--white);
    color: var(--black);
    overflow: hidden;
    border: 2px solid var(--black);
    position: relative;
    display: flex;
    flex-direction: column;
  }

  #header {
    background: var(--black);
    color: var(--white);
    text-align: center;
    padding: 4px 0;
    font-size: 16px;
    font-weight: bold;
    letter-spacing: 2px;
  }

  #games {
    flex: 1;
    overflow: hidden;
    padding: 0;
  }

  /* --- Base game row styles (used by Sunday preset, overridden by others) --- */
  .game {
    display: flex;
    align-items: center;
    padding: 0 12px;
    border-bottom: 1px solid var(--black);
    overflow: hidden;
  }

  .team-block {
    display: flex;
    align-items: center;
    width: 160px;
  }
  .team-block.away { justify-content: flex-end; }
  .team-block.home { justify-content: flex-start; }

  .team-logo {
    object-fit: contain;
    image-rendering: pixelated;
  }

  .team-abbr {
    font-weight: bold;
    margin: 0 4px;
  }
  .team-block.away .team-abbr { text-align: right; }
  .team-block.home .team-abbr { text-align: left; }

  .score-block {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 140px;
    gap: 6px;
  }

  .score {
    font-weight: bold;
    text-align: center;
  }

  .score-separator {
    color: var(--black);
  }

  .status-block {
    flex: 1;
    text-align: right;
    padding-left: 8px;
    white-space: nowrap;
    overflow: hidden;
  }

  .status-live {
    color: var(--red);
    font-weight: bold;
  }

  .status-final {
    color: var(--black);
    font-weight: bold;
  }

  .status-pre {
    color: var(--black);
  }

  .possession-dot {
    color: var(--red);
    margin: 0 2px;
  }

  .situation {
    color: var(--black);
  }

  #footer {
    background: var(--black);
    color: var(--white);
    text-align: center;
    padding: 3px 0;
    font-size: 10px;
  }

  .no-games {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    font-size: 20px;
    color: var(--black);
  }

  /* Scrollbar hidden to mimic eink feel */
  #games::-webkit-scrollbar { display: none; }
  #games { -ms-overflow-style: none; scrollbar-width: none; }
</style>
</head>
<body>
<div id="eink">
  <div id="header">NFL SCOREBOARD</div>
  <div id="games"><div class="no-games">Connecting...</div></div>
  <div id="footer">Updated: <span id="updated">--</span></div>
</div>

<script>
const gamesEl = document.getElementById("games");
const updatedEl = document.getElementById("updated");
const GAMES_AREA_HEIGHT = 432; /* 480 - 24 header - 24 footer */

function renderSundayGame(g, cardHeight) {
  const isLive = g.state === "in";
  const isFinal = g.state === "post";
  const statusClass = isLive ? "status-live" : isFinal ? "status-final" : "status-pre";

  const logoSize = Math.min(cardHeight - 6, 24);
  const abbrFont = Math.max(10, Math.min(16, Math.floor(cardHeight * 0.5)));
  const scoreFont = Math.max(14, Math.min(22, Math.floor(cardHeight * 0.7)));
  const statusFont = Math.max(8, Math.min(12, Math.floor(cardHeight * 0.35)));
  const separatorFont = Math.max(10, Math.min(16, Math.floor(cardHeight * 0.45)));
  const dotFont = Math.max(6, Math.min(8, Math.floor(cardHeight * 0.25)));
  const situationFont = Math.max(7, Math.min(10, Math.floor(cardHeight * 0.3)));

  const awayPoss = isLive && g.possession === g.away_team
    ? '<span class="possession-dot" style="font-size:' + dotFont + 'px">&#9679;</span>' : '';
  const homePoss = isLive && g.possession === g.home_team
    ? '<span class="possession-dot" style="font-size:' + dotFont + 'px">&#9679;</span>' : '';

  let situationHtml = '';
  if (isLive && g.down_distance) {
    situationHtml = '<span class="situation" style="font-size:' + situationFont + 'px">' +
      g.down_distance + (g.spot ? ' at ' + g.spot : '') + '</span>';
  }

  return '<div class="game" style="height:' + cardHeight + 'px">' +
    '<div class="team-block away">' +
      '<img class="team-logo" src="/logo/' + g.away_team.toLowerCase() + '?size=' + logoSize + '" alt=""' +
        ' style="width:' + logoSize + 'px;height:' + logoSize + 'px">' +
      '<span class="team-abbr" style="font-size:' + abbrFont + 'px;min-width:' + (abbrFont * 2.2) + 'px">' + g.away_team + '</span>' +
      awayPoss +
    '</div>' +
    '<div class="score-block">' +
      '<span class="score" style="font-size:' + scoreFont + 'px;min-width:' + (scoreFont * 1.5) + 'px">' + g.away_score + '</span>' +
      '<span class="score-separator" style="font-size:' + separatorFont + 'px">-</span>' +
      '<span class="score" style="font-size:' + scoreFont + 'px;min-width:' + (scoreFont * 1.5) + 'px">' + g.home_score + '</span>' +
    '</div>' +
    '<div class="team-block home">' +
      homePoss +
      '<span class="team-abbr" style="font-size:' + abbrFont + 'px;min-width:' + (abbrFont * 2.2) + 'px">' + g.home_team + '</span>' +
      '<img class="team-logo" src="/logo/' + g.home_team.toLowerCase() + '?size=' + logoSize + '" alt=""' +
        ' style="width:' + logoSize + 'px;height:' + logoSize + 'px">' +
    '</div>' +
    '<div class="status-block" style="font-size:' + statusFont + 'px">' +
      '<span class="' + statusClass + '">' + g.status + '</span>' +
      (situationHtml ? ' ' + situationHtml : '') +
    '</div>' +
  '</div>';
}

function renderPlayoff3Game(g) {
  const isLive = g.state === "in";
  const isFinal = g.state === "post";
  const statusClass = isLive ? "status-live" : isFinal ? "status-final" : "status-pre";

  const awayPoss = isLive && g.possession === g.away_team
    ? '<span class="possession-dot" style="font-size:12px">&#9679;</span>' : '';
  const homePoss = isLive && g.possession === g.home_team
    ? '<span class="possession-dot" style="font-size:12px">&#9679;</span>' : '';

  let situationHtml = '';
  if (isLive && g.down_distance) {
    situationHtml = '<div style="font-size:14px;color:var(--black);text-align:center;margin-top:2px">' +
      g.down_distance + (g.spot ? ' at ' + g.spot : '') + '</div>';
  }

  return '<div class="game" style="height:144px;flex-direction:column;justify-content:center;padding:8px 12px">' +
    '<div style="display:flex;align-items:center;justify-content:center;gap:12px">' +
      '<div style="display:flex;align-items:center;gap:8px">' +
        '<img class="team-logo" src="/logo/' + g.away_team.toLowerCase() + '?size=48" alt=""' +
          ' style="width:48px;height:48px">' +
        '<span style="font-size:20px;font-weight:bold;min-width:44px;text-align:right">' + g.away_team + '</span>' +
        awayPoss +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:8px">' +
        '<span style="font-size:32px;font-weight:bold;min-width:48px;text-align:center">' + g.away_score + '</span>' +
        '<span style="font-size:20px">-</span>' +
        '<span style="font-size:32px;font-weight:bold;min-width:48px;text-align:center">' + g.home_score + '</span>' +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:8px">' +
        homePoss +
        '<span style="font-size:20px;font-weight:bold;min-width:44px;text-align:left">' + g.home_team + '</span>' +
        '<img class="team-logo" src="/logo/' + g.home_team.toLowerCase() + '?size=48" alt=""' +
          ' style="width:48px;height:48px">' +
      '</div>' +
    '</div>' +
    '<div style="text-align:center;margin-top:4px">' +
      '<span class="' + statusClass + '" style="font-size:16px">' + g.status + '</span>' +
    '</div>' +
    situationHtml +
  '</div>';
}

function renderPlayoff2Game(g, statKeys, statLabels) {
  const isLive = g.state === "in";
  const isFinal = g.state === "post";
  const statusClass = isLive ? "status-live" : isFinal ? "status-final" : "status-pre";

  const awayPoss = isLive && g.possession === g.away_team
    ? '<span class="possession-dot" style="font-size:12px">&#9679;</span>' : '';
  const homePoss = isLive && g.possession === g.home_team
    ? '<span class="possession-dot" style="font-size:12px">&#9679;</span>' : '';

  let situationHtml = '';
  if (isLive && g.down_distance) {
    situationHtml = ' <span style="font-size:13px;color:var(--black)">' +
      g.down_distance + (g.spot ? ' at ' + g.spot : '') + '</span>';
  }

  /* Stats table rows */
  let statsHtml = '';
  const stats = g.stats || {};
  const awayStats = stats[g.away_team] || {};
  const homeStats = stats[g.home_team] || {};
  if (statKeys && statKeys.length && (Object.keys(awayStats).length || Object.keys(homeStats).length)) {
    const rows = statKeys.map(function(key) {
      return '<tr>' +
        '<td style="text-align:right;padding:1px 8px;font-size:13px;font-weight:bold">' + (awayStats[key] || '-') + '</td>' +
        '<td style="text-align:center;padding:1px 8px;font-size:12px;color:var(--red)">' + (statLabels[key] || key) + '</td>' +
        '<td style="text-align:left;padding:1px 8px;font-size:13px;font-weight:bold">' + (homeStats[key] || '-') + '</td>' +
      '</tr>';
    }).join('');
    statsHtml = '<table style="width:100%;border-collapse:collapse;margin-top:4px">' +
      '<tr style="border-bottom:1px solid var(--black)">' +
        '<th style="text-align:right;padding:1px 8px;font-size:11px;font-weight:bold">' + g.away_team + '</th>' +
        '<th style="text-align:center;padding:1px 8px;font-size:11px"></th>' +
        '<th style="text-align:left;padding:1px 8px;font-size:11px;font-weight:bold">' + g.home_team + '</th>' +
      '</tr>' + rows + '</table>';
  }

  return '<div class="game" style="height:216px;flex-direction:column;justify-content:flex-start;padding:10px 20px">' +
    '<div style="display:flex;align-items:center;justify-content:center;gap:12px;margin-top:4px">' +
      '<div style="display:flex;align-items:center;gap:8px">' +
        '<img class="team-logo" src="/logo/' + g.away_team.toLowerCase() + '?size=64" alt=""' +
          ' style="width:64px;height:64px">' +
        '<span style="font-size:24px;font-weight:bold;min-width:50px;text-align:right">' + g.away_team + '</span>' +
        awayPoss +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:8px">' +
        '<span style="font-size:40px;font-weight:bold;min-width:56px;text-align:center">' + g.away_score + '</span>' +
        '<span style="font-size:24px">-</span>' +
        '<span style="font-size:40px;font-weight:bold;min-width:56px;text-align:center">' + g.home_score + '</span>' +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:8px">' +
        homePoss +
        '<span style="font-size:24px;font-weight:bold;min-width:50px;text-align:left">' + g.home_team + '</span>' +
        '<img class="team-logo" src="/logo/' + g.home_team.toLowerCase() + '?size=64" alt=""' +
          ' style="width:64px;height:64px">' +
      '</div>' +
    '</div>' +
    '<div style="text-align:center;margin-top:4px">' +
      '<span class="' + statusClass + '" style="font-size:16px">' + g.status + '</span>' +
      situationHtml +
    '</div>' +
    statsHtml +
  '</div>';
}

function renderSingleGame(g, statKeys, statLabels) {
  const isLive = g.state === "in";
  const isFinal = g.state === "post";
  const statusClass = isLive ? "status-live" : isFinal ? "status-final" : "status-pre";

  const awayPoss = isLive && g.possession === g.away_team
    ? '<span class="possession-dot" style="font-size:16px">&#9679;</span>' : '';
  const homePoss = isLive && g.possession === g.home_team
    ? '<span class="possession-dot" style="font-size:16px">&#9679;</span>' : '';

  let situationHtml = '';
  if (isLive && g.down_distance) {
    situationHtml = '<div style="font-size:18px;color:var(--black);text-align:center;margin-top:2px">' +
      g.down_distance + (g.spot ? ' at ' + g.spot : '') + '</div>';
  }

  /* Full stats table */
  let statsHtml = '';
  const stats = g.stats || {};
  const awayStats = stats[g.away_team] || {};
  const homeStats = stats[g.home_team] || {};
  if (statKeys && statKeys.length && (Object.keys(awayStats).length || Object.keys(homeStats).length)) {
    const rows = statKeys.map(function(key) {
      return '<tr>' +
        '<td style="text-align:right;padding:2px 12px;font-size:14px;font-weight:bold">' + (awayStats[key] || '-') + '</td>' +
        '<td style="text-align:center;padding:2px 12px;font-size:13px;color:var(--red)">' + (statLabels[key] || key) + '</td>' +
        '<td style="text-align:left;padding:2px 12px;font-size:14px;font-weight:bold">' + (homeStats[key] || '-') + '</td>' +
      '</tr>';
    }).join('');
    statsHtml = '<table style="width:100%;border-collapse:collapse;margin-top:8px">' +
      '<tr style="border-bottom:2px solid var(--black)">' +
        '<th style="text-align:right;padding:2px 12px;font-size:14px;font-weight:bold">' + g.away_team + '</th>' +
        '<th style="text-align:center;padding:2px 12px;font-size:12px"></th>' +
        '<th style="text-align:left;padding:2px 12px;font-size:14px;font-weight:bold">' + g.home_team + '</th>' +
      '</tr>' + rows + '</table>';
  }

  return '<div class="game" style="height:432px;flex-direction:column;justify-content:flex-start;padding:12px 40px">' +
    '<div style="display:flex;align-items:center;justify-content:center;gap:16px;margin-top:8px">' +
      '<div style="display:flex;align-items:center;gap:12px">' +
        '<img class="team-logo" src="/logo/' + g.away_team.toLowerCase() + '?size=96" alt=""' +
          ' style="width:96px;height:96px">' +
        '<span style="font-size:36px;font-weight:bold;min-width:60px;text-align:right">' + g.away_team + '</span>' +
        awayPoss +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:10px">' +
        '<span style="font-size:64px;font-weight:bold;min-width:72px;text-align:center">' + g.away_score + '</span>' +
        '<span style="font-size:36px">-</span>' +
        '<span style="font-size:64px;font-weight:bold;min-width:72px;text-align:center">' + g.home_score + '</span>' +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:12px">' +
        homePoss +
        '<span style="font-size:36px;font-weight:bold;min-width:60px;text-align:left">' + g.home_team + '</span>' +
        '<img class="team-logo" src="/logo/' + g.home_team.toLowerCase() + '?size=96" alt=""' +
          ' style="width:96px;height:96px">' +
      '</div>' +
    '</div>' +
    '<div style="text-align:center;margin-top:6px">' +
      '<span class="' + statusClass + '" style="font-size:24px">' + g.status + '</span>' +
    '</div>' +
    situationHtml +
    statsHtml +
  '</div>';
}

function renderGames(payload) {
  const { preset, games, stat_keys, stat_labels } = payload;

  if (!games.length) {
    gamesEl.innerHTML = '<div class="no-games">No games scheduled</div>';
    return;
  }

  if (preset === "sunday") {
    const cardHeight = Math.max(27, Math.floor(GAMES_AREA_HEIGHT / games.length));
    gamesEl.innerHTML = games.map(g => renderSundayGame(g, cardHeight)).join("");
  } else if (preset === "playoff_3") {
    gamesEl.innerHTML = games.map(g => renderPlayoff3Game(g)).join("");
  } else if (preset === "playoff_2") {
    gamesEl.innerHTML = games.map(g => renderPlayoff2Game(g, stat_keys, stat_labels)).join("");
  } else if (preset === "single") {
    gamesEl.innerHTML = games.map(g => renderSingleGame(g, stat_keys, stat_labels)).join("");
  }
}

const src = new EventSource("/stream");
src.addEventListener("scores", function(e) {
  const payload = JSON.parse(e.data);
  renderGames(payload);
  const now = new Date();
  updatedEl.textContent = now.toLocaleTimeString();
});

src.onerror = function() {
  updatedEl.textContent = "reconnecting...";
};
</script>
</body>
</html>
"""

if __name__ == "__main__":
    threading.Thread(target=fetch_scores, daemon=True).start()
    mode = "MOCK DATA" if USE_MOCK else "LIVE (ESPN API)"
    preset_info = f", preset={MOCK_PRESET}" if MOCK_PRESET else ""
    print(f"NFL Scoreboard running at http://localhost:5000  [{mode}{preset_info}]")
    app.run(host="0.0.0.0", port=5000, threaded=True)
