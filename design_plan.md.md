# NFL scoreboard on a Raspberry Pi 3B with tri-color eInk

**The ESPN unofficial API is the only free data source worth using for live NFL scores, and a Flask + SSE stack on the Pi 3B handles the entire project comfortably.** This combination powers dozens of existing open-source Pi scoreboard projects and is proven, reliable, and beginner-friendly. The tri-color eInk display's **16–18 second refresh time** is the dominant design constraint — it dictates everything from polling intervals to UI philosophy. Prototype in the browser first with a pixel-accurate 800×480 canvas locked to black, white, and red, then migrate to the hardware with the Adafruit Blinka + `adafruit-circuitpython-epd` library stack. The project is very achievable for a beginner-to-intermediate Python developer.

---

## The ESPN hidden API is the only serious free option

After evaluating nine data sources, one stands far above the rest for live scores. The **ESPN undocumented API** at `site.api.espn.com` requires no API key, returns rich JSON, updates within **5–30 seconds** of real plays, and has been stable for years. The key endpoint is:

```
https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
```

This single call returns every game for the current week — scores, quarter, clock, possession, down and distance, and team metadata including logo URLs. Add query parameters for historical data: `?seasontype=2&week=1` for regular season week 1. A per-game detail endpoint exists at `site.web.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={EVENT_ID}` for play-by-play and drive data.

The open-source project **`mikemountain/nfl-led-scoreboard`** on GitHub is direct proof-of-concept: it drives an RGB LED matrix on a Raspberry Pi using this exact API, polling every **3 seconds** without issues. An emulated version (`ty-porter/nfl-led-scoreboard-emulated`) lets you test without hardware. Another mature project, **`robbydyer/sports`** (written in Go), supports NFL plus five other leagues with a web UI and Docker deployment.

Community documentation is excellent. The GitHub repo `pseudo-r/Public-ESPN-API` catalogs **370+ endpoints** across 17 sports. Additional endpoint references exist at `gist.github.com/nntrn/ee26cb2a0716de0947a0a4e9a157bc1c` (NFL-specific) and `sportsapis.dev/espn-api`.

Every other free source has a fatal flaw for live scores:

- **NFL.com endpoints** (`static.nfl.com/liveupdate/scorestrip/ss.xml`) — **deprecated since ~2020** when the NFL overhauled their infrastructure. The classic `nflgame` Python library that relied on these is broken.
- **`nfl_data_py`** (pip installable, MIT-licensed, from the nflverse project) — excellent for historical analytics (play-by-play from 1999 onward) but data updates **weekly**, not live. Useless for a scoreboard.
- **SportsDataIO free tier** — the 1,000 calls/month trial returns **scrambled fake data**, not real scores. Real data requires an enterprise contract.
- **MySportsFeeds free tier** — capped at **100 requests/day** and explicitly excludes real-time scores on the free plan.
- **TheSportsDB free tier** — no livescores at all; those require the **€9/month** premium tier (with a 2-minute delay).
- **Web scraping** ESPN/NFL.com — both are JavaScript-rendered SPAs requiring a headless browser (Playwright/Selenium), which is resource-heavy on a Pi 3B and fragile to maintain. The ESPN API returns the same data directly as JSON.

Two niche Python packages are worth noting: **`nfllivepy`** (`github.com/jlkazan/nfllivepy`) is designed specifically for live play-by-play data and could complement the ESPN API. **`sportsipy`** scrapes Sports Reference for historical stats only.

---

## Flask with server-sent events is the right display stack

For the browser prototype, the ideal stack is **Flask + SSE** (server-sent events) with zero extra dependencies beyond Flask itself. A background thread polls the ESPN API and pushes updates to any connected browser via SSE. The browser's native `EventSource` API handles reconnection automatically. Total RAM usage on the Pi 3B: **~30–50 MB**.

Here is a working minimal example:

```python
# scoreboard.py — complete working prototype
import json, queue, threading, time, requests
from flask import Flask, Response, render_template_string

app = Flask(__name__)

class MessageAnnouncer:
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

def fetch_scores():
    ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    while True:
        try:
            data = requests.get(ESPN_URL, timeout=10).json()
            games = []
            for event in data.get("events", []):
                comp = event["competitions"][0]
                away = comp["competitors"][1]
                home = comp["competitors"][0]
                games.append({
                    "away_team": away["team"]["abbreviation"],
                    "home_team": home["team"]["abbreviation"],
                    "away_score": away["score"],
                    "home_score": home["score"],
                    "status": event["status"]["type"]["shortDetail"],
                    "away_logo": away["team"]["logo"],
                    "home_logo": home["team"]["logo"],
                })
            msg = f"event: scores\ndata: {json.dumps(games)}\n\n"
            announcer.announce(msg)
        except Exception as e:
            print(f"Error fetching scores: {e}")
        time.sleep(30)

threading.Thread(target=fetch_scores, daemon=True).start()

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

TEMPLATE = """<!DOCTYPE html>
<html><head><title>NFL Scoreboard</title>
<style>
  body { background:#fff; color:#000; font-family:monospace; margin:0; }
  #eink { width:800px; height:480px; background:#fff; overflow:hidden; }
  .game { display:flex; align-items:center; padding:8px; border-bottom:2px solid #000; }
  .score { color:#ff0000; font-size:32px; font-weight:bold; margin:0 12px; }
  .team { font-size:18px; font-weight:bold; }
  .status { color:#ff0000; font-size:14px; }
</style></head>
<body><div id="eink"><div id="games">Loading...</div></div>
<script>
const src = new EventSource("/stream");
src.addEventListener("scores", e => {
  const games = JSON.parse(e.data);
  document.getElementById("games").innerHTML = games.map(g =>
    `<div class="game">
       <span class="team">${g.away_team}</span>
       <span class="score">${g.away_score}</span>
       <span>@</span>
       <span class="score">${g.home_score}</span>
       <span class="team">${g.home_team}</span>
       <span class="status">${g.status}</span>
     </div>`
  ).join("");
});
</script></body></html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
```

Run with `python scoreboard.py` and open `http://localhost:5000` — or on the Pi, launch Chromium in kiosk mode: `chromium-browser --kiosk http://localhost:5000`.

**Why not the alternatives?** FastAPI adds async complexity (uvicorn, `async/await` patterns) for zero benefit at this scale — you're serving one browser client. Node.js + Socket.io requires JavaScript when the entire eInk pipeline is Python. Simple polling (Flask REST + `setInterval`) also works perfectly and is even simpler if SSE feels like overkill — for NFL scores that change every few minutes, **30-second polling is indistinguishable from push**. HTMX is a sleek middle ground that eliminates all custom JavaScript: `<div hx-get="/scores" hx-trigger="every 30s">` handles live updates in a single HTML attribute.

---

## Simulating tri-color eInk in the browser

The simplest and most effective approach: **design directly within the 3-color constraint from the start.** For a text-heavy scoreboard layout, just use CSS variables and never reference any other colors:

```css
:root {
  --black: #000000;
  --white: #FFFFFF;
  --red:   #FF0000;
}
#eink-preview {
  width: 800px;
  height: 480px;
  background: var(--white);
  color: var(--black);
  image-rendering: pixelated;
}
.highlight { color: var(--red); }
```

For **raster images** (like team logos) that need color reduction, use an HTML5 Canvas with Floyd-Steinberg dithering to map arbitrary colors to the 3-color palette. The GitHub repo **`MortimerWittgenstein/FloydSteinbergAlgorithm`** provides a ready-made JavaScript implementation designed specifically for e-paper displays — the author uses it for Waveshare panels. Usage is one function call:

```javascript
const EINK_PALETTE = [[0,0,0], [255,255,255], [255,0,0]];
floydSteinbergDithering(canvasContext, EINK_PALETTE, 800, 480, 1.0);
```

CSS filters alone **cannot** enforce a 3-color palette — `grayscale()` and `contrast()` can force black/white but cannot introduce red as a third color. Canvas-based quantization is the only reliable browser-side approach.

**To export the browser preview to the actual eInk display**, use `canvas.toBlob()` to save a PNG, then on the Pi split it into two 1-bit images with Pillow — one for the black channel and one for the red channel:

```python
from PIL import Image

img = Image.open("eink-frame.png").convert("RGB")
black_layer = Image.new("1", (800, 480), 255)
red_layer   = Image.new("1", (800, 480), 255)

for x in range(800):
    for y in range(480):
        r, g, b = img.getpixel((x, y))
        if (r, g, b) == (0, 0, 0):
            black_layer.putpixel((x, y), 0)
        elif (r, g, b) == (255, 0, 0):
            red_layer.putpixel((x, y), 0)

# Send both layers to the Waveshare/Adafruit driver
```

The Adafruit UC8179 driver accepts exactly this two-buffer format via `display.display(epd.getbuffer(black_img), epd.getbuffer(red_img))`.

---

## Team logos: fetch at runtime from ESPN's CDN

ESPN hosts **500×500 PNG logos** for all 32 teams at a predictable URL pattern:

```
https://a.espncdn.com/i/teamlogos/nfl/500/{abbr}.png
```

Where `{abbr}` is the lowercase abbreviation: `kc`, `buf`, `dal`, `sf`, `ne`, etc. A dark-mode variant exists at `/500-dark/{abbr}.png`. The ESPN scoreboard API itself returns the full logo URL in each team's JSON object, so you don't even need to construct the URL manually.

The **nflverse project** maintains a comprehensive CSV at `github.com/nflverse/nflverse-pbp` mapping all 32 teams to their abbreviations, ESPN logo URLs, Wikipedia logo URLs, hex color codes, and wordmarks. This is the best structured reference file for the project.

**TheSportsDB** also serves team badges via their free API (key: `123`): `thesportsdb.com/api/v1/json/123/lookup_all_teams.php?id=4391` returns all NFL teams with `strBadge` URLs. For SVG logos specifically, **`ChrisKatsaras/React-NFL-Logos`** on GitHub contains vector versions of all 32 team logos.

**On licensing**: NFL team logos are registered trademarks. For a **personal, non-commercial** project running in your home, the practical legal risk is effectively zero — trademark enforcement targets commercial use and consumer confusion. However, **do not bundle logo files in a public GitHub repository**. Instead, fetch them at runtime from ESPN's CDN and cache locally. If publishing code, provide a download script that users run themselves, and add a disclaimer noting NFL trademarks.

**For the eInk display**, full-color logos must be converted to 3 colors. Most logos become black silhouettes on white. Only about **9 teams** meaningfully benefit from the red channel — the Cardinals, Chiefs, 49ers, Buccaneers, Falcons, Bengals, Texans, Patriots, and Commanders all have red elements. For all other teams, render logos as black-on-white. Keep logos small (~60–80px) where dithering artifacts are less visible, or use simplified silhouette versions.

---

## The critical gotchas that will shape your design

**The eInk refresh rate is the single biggest constraint.** A full tri-color refresh takes **16–18 seconds** on the 7.5" UC8179 display. Partial refresh is only available for black/white — using it loses the red channel entirely. Adafruit and Waveshare both recommend a **minimum 180-second interval** between refreshes to prevent display damage and ghosting. This means the scoreboard is a glance-at-it dashboard, not a real-time ticker. The optimal strategy: poll the ESPN API every **30–60 seconds**, compare new data against cached data, and **only trigger a display refresh when scores actually change** — with a 3-minute cooldown enforced between refreshes.

**Rate limits on the ESPN API are undefined but manageable.** No official limits are published, no API key is required. Community projects have polled every 3 seconds for years without blocks. For this project, polling every 30–60 seconds generates roughly the same load as one person idly browsing ESPN.com. Implement exponential backoff on HTTP errors and cache responses. Use the single `/scoreboard` endpoint (returns all games) rather than hitting per-game endpoints individually.

**Terms of service are technically violated but not enforced for hobby use.** Disney's ToS (covering ESPN) explicitly prohibits automated access and scraping. In practice, **no cease-and-desist actions have been reported** against any of the hundreds of open-source Pi scoreboard projects using this API. The legal precedent from *HiQ v. LinkedIn* (2022) supports accessing publicly available data. Commercial use, however, carries real legal risk.

**The Raspberry Pi 3B handles this workload easily.** With its 1.2GHz quad-core ARM and 1GB RAM, running Flask + a polling thread + serving one browser client uses roughly **200–300 MB total** (including the OS). Run **Raspberry Pi OS Lite** (headless, no desktop) to maximize available resources. Use a quality **2.5A+ power supply** — the eInk display draws meaningful current during refresh cycles.

**CircuitPython is not a concern here.** CircuitPython runs on microcontrollers, not the Raspberry Pi's Linux OS. The Pi runs standard **CPython 3.x**. To use Adafruit's eInk libraries on the Pi, install **Adafruit Blinka** (`pip3 install Adafruit-Blinka`), which provides CircuitPython-compatible APIs on CPython. Then install `adafruit-circuitpython-epd` for the display driver. The UC8179 driver class handles the 7.5" tri-color display. Note: on Raspberry Pi OS Bookworm and later, all pip installs must be done inside a **virtual environment**.

**The hardware setup requires an intermediary board.** The Adafruit 7.5" bare display (product #6415, $64.95) has a 24-pin FPC connector but no onboard driver. You need the **Adafruit E-Ink Bonnet** (plugs onto the Pi's GPIO header) or the **eInk Breakout Friend** (for breadboard wiring). SPI must be enabled via `raspi-config`. The initialization code:

```python
import board, busio, digitalio
from adafruit_epd.uc8179 import Adafruit_UC8179

spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
display = Adafruit_UC8179(
    800, 480, spi,
    cs_pin=digitalio.DigitalInOut(board.CE0),
    dc_pin=digitalio.DigitalInOut(board.D22),
    rst_pin=digitalio.DigitalInOut(board.D27),
    busy_pin=digitalio.DigitalInOut(board.D17),
    sramcs_pin=None,  # Not needed on Pi (plenty of RAM)
    tri_color=True
)
```

---

## Recommended project architecture and phased plan

The cleanest path from prototype to hardware follows three phases:

**Phase 1 — Browser prototype.** Build the Flask + SSE app with an 800×480 `<div>` locked to black/white/red. Fetch scores from ESPN, render the layout with HTML/CSS, and iterate on the design in any desktop browser. This phase validates the data pipeline and UI layout with zero hardware.

**Phase 2 — Pillow rendering bridge.** Refactor the score-rendering logic to generate a **Pillow `Image`** instead of (or in addition to) HTML. Draw text, rectangles, and logo images onto an 800×480 canvas using `ImageDraw`. This is the same image that will be sent to the eInk display. Serve it as a PNG at `/preview.png` for browser verification.

**Phase 3 — eInk deployment.** Split the Pillow image into black and red layers, send to the UC8179 driver. Add a systemd service for auto-start on boot. Set the polling interval to 30 seconds and the display refresh cooldown to 180 seconds. Run headless.

The data-fetching thread from Phase 1 carries through unchanged into Phase 3. The only thing that changes is the rendering target — HTML in the browser, Pillow for the display. This architecture keeps the project modular and testable at every stage.