NFL Scoreboard - Browser Prototype
===================================

Requirements
------------
- Python 3.x
- pip

Setup
-----
1. Install dependencies:

   pip install requests Pillow numpy adafruit-blinka adafruit-circuitpython-epd

2. Run the server (mock data for testing):

   set MOCK=1 && python scoreboard.py

   To turn mock mode off again, close the terminal or run:

   set MOCK= && python scoreboard.py

3. Test specific display presets (mock mode only):

   set MOCK=1 && set MOCK_PRESET=single && python scoreboard.py
   set MOCK=1 && set MOCK_PRESET=playoff2 && python scoreboard.py
   set MOCK=1 && set MOCK_PRESET=playoff3 && python scoreboard.py
   set MOCK=1 && python scoreboard.py                (Sunday, default)


Display Presets
---------------
The scoreboard automatically selects a layout based on game count:
- Single (1 game)  : Large card with 96px logos, 64px scores, full 12-stat box score
- Playoff 2 (2)    : Medium cards with 64px logos, 40px scores, 4 condensed stats
- Playoff 3 (3)    : Enlarged cards with 48px logos, 32px scores, no stats
- Sunday (4+)      : Compact rows, dynamically scaled to fit all games
