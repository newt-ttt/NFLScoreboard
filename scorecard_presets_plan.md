# Scorecard Presets Implementation Plan

## Overview
The 800x480 eInk scoreboard currently renders all games identically as 30px rows. Monday/Thursday nights have 1 game, playoffs have 2-3, and Sundays have 11-14. A single game shouldn't occupy the same tiny row as a packed Sunday slate. This plan adds 3 display presets that scale layout, logos, fonts, and optionally show game stats based on game count.

---

## Preset Selection

Determined by counting today's games (post-filter). Sent to the frontend via SSE so rendering is purely CSS/JS driven.

| Games | Preset | Stats? |
|-------|--------|--------|
| 1 | `single` | Full (12 stats) |
| 2 | `playoff_2` | Partial (4 stats) |
| 3 | `playoff_3` | None — larger cards only |
| 4+ | `sunday` | None — dynamic row height |

---

## Layout Dimensions (800w × 432h game area)

### Single Game (1 game — 432px total)
- Logos: 96×96px
- Team abbreviation: 36px font
- Score: 64px font
- Status/clock: 24px font (red if live)
- Score section pinned to top (~160px)
- Stats table below (~260px), 3-column layout: Away stat | Label | Home stat
- **Full stats shown:**
  - 1st Downs
  - Total Yards
  - Passing Yards
  - Completions/Attempts
  - Rushing Yards
  - Rushing Attempts
  - Turnovers
  - Interceptions
  - Sacks-Yards Lost
  - 3rd Down Efficiency
  - Penalties-Yards
  - Time of Possession

### Playoff — 2 Games (216px per card)
- Logos: 64×64px
- Team abbreviation: 24px font
- Score: 40px font
- Status: 16px font
- Score section (~90px), condensed stats below (~120px)
- **Partial stats shown:**
  - Passing Yards
  - Rushing Yards
  - Turnovers
  - 3rd Down Efficiency

### Playoff — 3 Games (144px per card)
- Logos: 48×48px
- Team abbreviation: 20px font
- Score: 32px font
- Status: 14px font
- **No stats** — just enlarged cards with centered layout

### Sunday (4+ games — 432/n px per card)
- Dynamic scaling: logos, fonts, and row height all scale proportionally
- Minimum ~27px rows at 16 games
- Current compact layout style at ~30px
- **No stats**

---

## Backend Changes

### New ESPN Summary Endpoint (for stats)
```
https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={EVENT_ID}
```
- Returns full box score in `boxscore.teams[].statistics[]`
- Each stat has a `name` (e.g., `netPassingYards`) and `displayValue` (e.g., `"198"`)
- Only called for `single` and `playoff_2` presets (max 2 extra API calls per poll cycle)
- Each call wrapped in try/except — if stats fail, the card renders without them

### Preset Detection
```python
def determine_preset(game_count):
    if game_count == 1:
        return "single"
    elif game_count == 2:
        return "playoff_2"
    elif game_count == 3:
        return "playoff_3"
    else:
        return "sunday"
```

### Modified SSE Payload
Current format:
```json
[game1, game2, ...]
```
New format:
```json
{
  "preset": "single",
  "stat_keys": ["netPassingYards", "rushingYards", ...],
  "stat_labels": {"netPassingYards": "Pass Yds", ...},
  "games": [
    {
      "id": "401234567",
      "away_team": "KC",
      "home_team": "BUF",
      "away_score": "21",
      "home_score": "17",
      "status": "Q3 8:42",
      "state": "in",
      "stats": {
        "KC":  {"netPassingYards": "198", "rushingYards": "89", ...},
        "BUF": {"netPassingYards": "167", "rushingYards": "64", ...}
      }
    }
  ]
}
```

### Logo Endpoint Enhancement
- Current: `/logo/<abbr>` — always serves 64×64
- New: `/logo/<abbr>?size=96` — accepts size query parameter
- Cache key changes from `{abbr}.png` to `{abbr}_{size}.png`
- Size clamped 16–128px

### Mock Data for Testing
- New `MOCK_PRESET` environment variable: `single`, `playoff2`, `playoff3`, or empty
- New `MOCK_STATS` dictionary with fake box score data for each mock game
- When `MOCK_PRESET` is set, the mock game list is sliced to the appropriate count

---

## Frontend Changes

### CSS Strategy
Apply a preset class to the `#games` container (`preset-single`, `preset-playoff_2`, etc.), then use CSS descendant selectors to control all sizing. No inline styles needed except for dynamic Sunday row heights.

### Card Layouts
- **Single & Playoff 2:** Vertical stacked layout (flexbox column) — logos and scores on top, stats table below
- **Playoff 3:** Horizontal row layout (like current) but with larger elements and more padding
- **Sunday:** Horizontal row layout with proportionally scaled elements

### JavaScript
- `renderGames()` updated to accept new payload object and branch on `preset`
- Four render functions: `renderSingleGame()`, `renderPlayoff2Game()`, `renderPlayoff3Game()`, `renderSundayGame()`
- Logo `<img>` tags include `?size=` parameter matching the preset's logo size
- SSE handler updated to parse new payload shape

---

## Implementation Order

### Phase A — Backend Data Pipeline
1. Add `ESPN_SUMMARY_URL` constant
2. Add `fetch_game_stats()` function
3. Add `determine_preset()` and stat constants
4. Add `MOCK_STATS` and `MOCK_PRESET` support
5. Modify `fetch_scores()` for new payload shape
6. Modify `/logo/<abbr>` for size parameter

### Phase B — Sunday Preset
- Closest to current layout, validates new payload parsing
- Dynamic row height and proportional scaling

### Phase C — Playoff 3 Preset
- Enlarged cards, no stats, centered layout

### Phase D — Playoff 2 Preset
- Vertical card layout with condensed 4-row stats table

### Phase E — Single Game Preset
- Full vertical layout with 12-row stats table

### Phase F — Polish
- Edge cases (stats fetch failure, overflow, text truncation)
- Live testing on actual game days

---

## Testing Commands

```
rem Sunday preset (13 mock games)
set MOCK=1 && python scoreboard.py

rem Single game preset
set MOCK=1 && set MOCK_PRESET=single && python scoreboard.py

rem Playoff 2-game preset (with stats)
set MOCK=1 && set MOCK_PRESET=playoff2 && python scoreboard.py

rem Playoff 3-game preset (no stats)
set MOCK=1 && set MOCK_PRESET=playoff3 && python scoreboard.py
```

Open http://localhost:5000 to verify each preset. Check browser DevTools → Network → EventStream for SSE payload structure.

---

## Notes
- No new Python dependencies required (flask, requests, Pillow, numpy already present)
- Logo dithered cache directory will grow with size variants (e.g., `kc_64.png`, `kc_96.png`)
- Preset is based on total games scheduled today (not just live games), so it remains stable as games end
- Stats API calls only happen for 1-2 game presets — no additional load on Sunday slates
