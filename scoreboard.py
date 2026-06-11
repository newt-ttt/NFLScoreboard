#!/usr/bin/env python3
"""NFL Scoreboard e-ink display driver for Adafruit 7.5" tri-color display + bonnet."""

import os
import re
import time
from datetime import datetime

import board
import busio
import digitalio
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from adafruit_epd.epd import Adafruit_EPD
from adafruit_epd.uc8179 import Adafruit_UC8179

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED   = (255, 0, 0)

W, H      = 800, 480
HEADER_H  = 24
FOOTER_H  = 16
GAMES_H   = H - HEADER_H - FOOTER_H

POLL_INTERVAL = 30

ESPN_URL         = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_SUMMARY_URL = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}"

USE_MOCK    = os.environ.get("MOCK", "").strip().lower() in ("1", "true", "yes")
MOCK_PRESET = os.environ.get("MOCK_PRESET", "").strip().lower()

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
LOGO_DIR     = os.path.join(BASE_DIR, "logos")
DITHER_CACHE = os.path.join(LOGO_DIR, "dithered")
os.makedirs(DITHER_CACHE, exist_ok=True)

FONT      = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

EINK_PALETTE = np.array([[0,0,0],[255,255,255],[255,0,0]], dtype=np.float64)

STATS_SINGLE = [
	"firstDowns","totalYards","netPassingYards","completionAttempts",
	"rushingYards","rushingAttempts","turnovers","interceptions",
	"sacksYardsLost","thirdDownEff","totalPenaltiesYards","possessionTime",
]
STATS_PLAYOFF2 = ["netPassingYards","rushingYards","turnovers","thirdDownEff"]
STAT_LABELS = {
	"firstDowns": "1st Downs",  "totalYards": "Total Yds",
	"netPassingYards": "Pass Yds", "completionAttempts": "Comp/Att",
	"rushingYards": "Rush Yds",  "rushingAttempts": "Rush Att",
	"turnovers": "Turnovers",   "interceptions": "INTs",
	"sacksYardsLost": "Sacks",  "thirdDownEff": "3rd Down",
	"totalPenaltiesYards": "Penalties", "possessionTime": "Possession",
}

_today = datetime.now().strftime("%Y-%m-%d")
MOCK_WEEK_LABEL = "Week 14"
MOCK_GAMES = [
	{"id":"m1",  "away_team":"KC",  "home_team":"BUF","away_score":"21","home_score":"17",
	 "away_record":"11-2","home_record":"10-3",
	 "status":"Q3 8:42","state":"in","date":_today,"possession":"KC","down_distance":"2nd & 7","spot":"BUF 35"},
	{"id":"m2",  "away_team":"DAL","home_team":"PHI","away_score":"10","home_score":"14",
	 "away_record":"7-6","home_record":"10-3",
	 "status":"Q2 2:01","state":"in","date":_today,"possession":"PHI","down_distance":"1st & 10","spot":"PHI 25"},
	{"id":"m3",  "away_team":"SF", "home_team":"SEA","away_score":"27","home_score":"24",
	 "away_record":"9-4","home_record":"7-6",
	 "status":"Final","state":"post","date":_today},
	{"id":"m4",  "away_team":"BAL","home_team":"CIN","away_score":"31","home_score":"28",
	 "away_record":"11-2","home_record":"5-8",
	 "status":"Q4 0:34","state":"in","date":_today,"possession":"CIN","down_distance":"3rd & 8","spot":"BAL 42"},
	{"id":"m5",  "away_team":"MIA","home_team":"NE", "away_score":"3", "home_score":"7",
	 "away_record":"8-5","home_record":"3-10",
	 "status":"Q1 11:20","state":"in","date":_today,"possession":"MIA","down_distance":"3rd & 2","spot":"NE 48"},
	{"id":"m6",  "away_team":"DEN","home_team":"LV", "away_score":"17","home_score":"20",
	 "away_record":"7-6","home_record":"5-8",
	 "status":"Final/OT","state":"post","date":_today},
	{"id":"m7",  "away_team":"NYG","home_team":"WAS","away_score":"14","home_score":"14",
	 "away_record":"2-11","home_record":"9-4",
	 "status":"Q2 0:12","state":"in","date":_today,"possession":"WAS","down_distance":"2nd & 3","spot":"NYG 40"},
	{"id":"m8",  "away_team":"LAR","home_team":"ARI","away_score":"23","home_score":"20",
	 "away_record":"6-6-1","home_record":"6-7",
	 "status":"Final","state":"post","date":_today},
	{"id":"m9",  "away_team":"TB", "home_team":"NO", "away_score":"7", "home_score":"3",
	 "away_record":"7-6","home_record":"4-9",
	 "status":"Q1 5:44","state":"in","date":_today,"possession":"TB","down_distance":"1st & 10","spot":"TB 30"},
	{"id":"m10","away_team":"PIT","home_team":"CLE","away_score":"13","home_score":"10",
	 "away_record":"8-5","home_record":"3-10",
	 "status":"Halftime","state":"in","date":_today},
	{"id":"m11","away_team":"JAX","home_team":"TEN","away_score":"6", "home_score":"9",
	 "away_record":"3-10","home_record":"4-9",
	 "status":"Q3 12:00","state":"in","date":_today,"possession":"TEN","down_distance":"3rd & 1","spot":"JAX 49"},
	{"id":"m12","away_team":"LAC","home_team":"HOU","away_score":"0", "home_score":"0",
	 "away_record":"8-5","home_record":"8-5",
	 "status":"8:20 PM","state":"pre","date":_today},
	{"id":"m13","away_team":"GB", "home_team":"CHI","away_score":"0", "home_score":"0",
	 "away_record":"9-4","home_record":"4-9",
	 "status":"Mon 8:15PM","state":"pre","date":"2099-01-01"},
]
MOCK_STATS = {
	"m1": {
		"KC":  {"firstDowns":"18","totalYards":"342","netPassingYards":"245","completionAttempts":"19/27",
		        "rushingYards":"97","rushingAttempts":"22","turnovers":"1","interceptions":"1",
		        "sacksYardsLost":"2-14","thirdDownEff":"5/10","totalPenaltiesYards":"4-30","possessionTime":"18:22"},
		"BUF": {"firstDowns":"15","totalYards":"298","netPassingYards":"201","completionAttempts":"17/25",
		        "rushingYards":"97","rushingAttempts":"18","turnovers":"0","interceptions":"0",
		        "sacksYardsLost":"1-8","thirdDownEff":"4/9","totalPenaltiesYards":"6-45","possessionTime":"15:38"},
	},
	"m2": {
		"DAL": {"firstDowns":"8","totalYards":"156","netPassingYards":"112","completionAttempts":"10/18",
		        "rushingYards":"44","rushingAttempts":"12","turnovers":"1","interceptions":"1",
		        "sacksYardsLost":"3-21","thirdDownEff":"2/7","totalPenaltiesYards":"3-25","possessionTime":"12:15"},
		"PHI": {"firstDowns":"12","totalYards":"210","netPassingYards":"148","completionAttempts":"14/20",
		        "rushingYards":"62","rushingAttempts":"15","turnovers":"0","interceptions":"0",
		        "sacksYardsLost":"1-6","thirdDownEff":"5/8","totalPenaltiesYards":"2-15","possessionTime":"17:45"},
	},
}

spi  = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
ecs  = digitalio.DigitalInOut(board.CE0)
dc   = digitalio.DigitalInOut(board.D22)
rst  = digitalio.DigitalInOut(board.D27)
busy = digitalio.DigitalInOut(board.D17)

display = Adafruit_UC8179(W, H, spi,
	cs_pin=ecs, dc_pin=dc, sramcs_pin=None,
	rst_pin=rst, busy_pin=busy, tri_color=True)


def dither_to_tricolor(img, size):
	img = img.convert("RGBA")
	bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
	bg.paste(img, mask=img)
	img = bg.convert("RGB").resize((size, size), Image.LANCZOS)
	pixels = np.array(img, dtype=np.float64)
	h, w = pixels.shape[:2]
	for y in range(h):
		for x in range(w):
			old = pixels[y, x].copy()
			dists = np.sum((EINK_PALETTE - old) ** 2, axis=1)
			nearest = EINK_PALETTE[np.argmin(dists)]
			pixels[y, x] = nearest
			error = old - nearest
			if x + 1 < w:
				pixels[y, x+1] += error * 7/16
			if y + 1 < h:
				if x - 1 >= 0:
					pixels[y+1, x-1] += error * 3/16
				pixels[y+1, x] += error * 5/16
				if x + 1 < w:
					pixels[y+1, x+1] += error * 1/16
	return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))


def get_logo(abbr, size):
	abbr = abbr.lower()
	cached = os.path.join(DITHER_CACHE, f"{abbr}_{size}.png")
	if os.path.exists(cached):
		return Image.open(cached).convert("RGB")
	source = os.path.join(LOGO_DIR, f"{abbr}.png")
	if not os.path.exists(source):
		return None
	dithered = dither_to_tricolor(Image.open(source), size)
	dithered.save(cached, "PNG")
	return dithered


def parse_week_label(data):
	season_type = data.get("season", {}).get("type", 2)
	week_num = data.get("week", {}).get("number", 0)
	if season_type == 1:
		return f"Preseason Week {week_num}"
	elif season_type == 2:
		return f"Week {week_num}"
	elif season_type == 3:
		names = {1:"Wild Card",2:"Divisional",3:"Conference Championships",5:"Super Bowl"}
		return names.get(week_num, f"Postseason Week {week_num}")
	return f"Week {week_num}"


def parse_games(data):
	games = []
	for event in data.get("events", []):
		comp = event["competitions"][0]
		home = comp["competitors"][0]
		away = comp["competitors"][1]
		status_obj    = event["status"]
		status_detail = status_obj["type"]["shortDetail"]
		status_state  = status_obj["type"]["state"]
		event_date    = event.get("date", "")[:10]
		away_records  = away.get("records", [])
		home_records  = home.get("records", [])
		game = {
			"id":          event["id"],
			"away_team":   away["team"]["abbreviation"],
			"home_team":   home["team"]["abbreviation"],
			"away_score":  away["score"],
			"home_score":  home["score"],
			"away_record": away_records[0]["summary"] if away_records else "",
			"home_record": home_records[0]["summary"] if home_records else "",
			"status": status_detail,
			"state":  status_state,
			"date":   event_date,
		}
		if status_state == "in":
			situation     = comp.get("situation", {})
			possession_id = situation.get("possession")
			game["possession"] = None
			if possession_id:
				for team in comp["competitors"]:
					if team["team"]["id"] == possession_id:
						game["possession"] = team["team"]["abbreviation"]
			game["down_distance"] = situation.get("shortDownDistanceText", "")
			game["spot"]          = situation.get("possessionText", "")
		games.append(game)
	return games


def fetch_game_stats(event_id):
	url = ESPN_SUMMARY_URL.format(event_id=event_id)
	resp = requests.get(url, timeout=10)
	resp.raise_for_status()
	data = resp.json()
	result = {}
	for team_data in data.get("boxscore", {}).get("teams", []):
		abbr  = team_data["team"]["abbreviation"]
		stats = {s["name"]: s["displayValue"] for s in team_data.get("statistics", [])}
		result[abbr] = stats
	return result


def game_sort_key(game):
	state  = game.get("state", "")
	status = game.get("status", "")
	if state == "pre":
		return (0, 0)
	if state == "post":
		return (2, 0)
	quarter_values = {"Q1":4,"Q2":3,"Q3":2,"Q4":1,"OT":0}
	if "halftime" in status.lower():
		return (1, -3000)
	match = re.match(r"(Q[1-4]|OT)\s+(\d+):(\d+)", status)
	if match:
		q = quarter_values.get(match.group(1), 0)
		time_remaining = q * 1000 + int(match.group(2)) * 60 + int(match.group(3))
		return (1, -time_remaining)
	return (1, 0)


def filter_and_sort_games(games):
	today    = datetime.now().strftime("%Y-%m-%d")
	filtered = [g for g in games if g.get("state") != "pre" or g.get("date","") == today]
	filtered.sort(key=game_sort_key)
	return filtered


def determine_preset(n):
	if n == 1: return "single"
	if n == 2: return "playoff_2"
	if n == 3: return "playoff_3"
	return "sunday"


_FONT_SIZES = [8, 9, 10, 11, 12, 13, 14, 16, 18, 20, 22, 24, 28, 32, 36, 40, 48, 64]

def load_fonts():
	reg  = {s: ImageFont.truetype(FONT,      s) for s in _FONT_SIZES}
	bold = {s: ImageFont.truetype(FONT_BOLD, s) for s in _FONT_SIZES}
	return reg, bold


def draw_header(draw, week_label, bold):
	draw.rectangle((0, 0, W, HEADER_H), fill=BLACK)
	draw.text((W // 2, HEADER_H // 2), f"NFL SCOREBOARD — {week_label}",
		font=bold[14], fill=WHITE, anchor="mm")


def draw_footer(draw, reg):
	y  = H - FOOTER_H
	ts = datetime.now().strftime("%-I:%M %p")
	draw.rectangle((0, y, W, H), fill=BLACK)
	draw.text((W // 2, y + FOOTER_H // 2), f"Updated: {ts}",
		font=reg[10], fill=WHITE, anchor="mm")


def draw_divider(draw, y):
	draw.line((0, y, W, y), fill=BLACK, width=1)


def paste_logo(image, abbr, size, x, y, anchor="lm"):
	logo = get_logo(abbr, size)
	if logo is None:
		return
	if anchor == "rm":
		x = x - size
	elif anchor == "mm":
		x = x - size // 2
	image.paste(logo, (x, y - size // 2))


def render_sunday(image, draw, games, reg, bold):
	card_h  = max(27, GAMES_H // len(games))
	logo_sz = min(card_h - 6, 22)

	for i, g in enumerate(games):
		y0  = HEADER_H + i * card_h
		mid = y0 + card_h // 2

		if i > 0:
			draw_divider(draw, y0)

		is_live      = g["state"] == "in"
		status_color = RED if is_live else BLACK

		abbr_sz   = max(10, min(16, card_h // 2))
		score_sz  = max(14, min(22, int(card_h * 0.68)))
		status_sz = max(8,  min(12, int(card_h * 0.34)))
		sit_sz    = max(7,  min(10, int(card_h * 0.28)))

		f_abbr   = bold.get(abbr_sz,  bold[14])
		f_score  = bold.get(score_sz, bold[18])
		f_status = reg.get(status_sz, reg[10])
		f_sit    = reg.get(sit_sz,    reg[8])

		x = 100  # left margin — shifts content away from edge

		# Away logo
		paste_logo(image, g["away_team"], logo_sz, x, mid, anchor="lm")
		x += logo_sz + 4

		# Away abbr
		draw.text((x, mid), g["away_team"], font=f_abbr, fill=BLACK, anchor="lm")
		x += int(f_abbr.getlength(g["away_team"])) + 4

		# Away possession dot
		if is_live and g.get("possession") == g["away_team"]:
			draw.ellipse((x, mid-4, x+8, mid+4), fill=RED)
		x += 12

		# Away score
		draw.text((x, mid), g["away_score"], font=f_score, fill=BLACK, anchor="lm")
		x += int(f_score.getlength(g["away_score"])) + 5

		# Separator
		draw.text((x, mid), "-", font=f_score, fill=BLACK, anchor="lm")
		x += int(f_score.getlength("-")) + 5

		# Home score
		draw.text((x, mid), g["home_score"], font=f_score, fill=BLACK, anchor="lm")
		x += int(f_score.getlength(g["home_score"])) + 4

		# Home possession dot
		if is_live and g.get("possession") == g["home_team"]:
			draw.ellipse((x, mid-4, x+8, mid+4), fill=RED)
		x += 12

		# Home abbr
		draw.text((x, mid), g["home_team"], font=f_abbr, fill=BLACK, anchor="lm")
		x += int(f_abbr.getlength(g["home_team"])) + 4

		# Home logo
		paste_logo(image, g["home_team"], logo_sz, x, mid, anchor="lm")
		x += logo_sz + 8

		# Situation — inline between home logo and status
		if is_live and g.get("down_distance"):
			sit = g["down_distance"] + (f" at {g['spot']}" if g.get("spot") else "")
			draw.text((x, mid), sit, font=f_sit, fill=BLACK, anchor="lm")

		# Status (quarter/clock) far right
		draw.text((790, mid), g["status"], font=f_status, fill=status_color, anchor="rm")


def render_playoff3(image, draw, games, reg, bold):
	card_h  = GAMES_H // 3
	logo_sz = 48

	for i, g in enumerate(games):
		y0  = HEADER_H + i * card_h
		mid = y0 + card_h // 2

		if i > 0:
			draw_divider(draw, y0)

		is_live      = g["state"] == "in"
		status_color = RED if is_live else BLACK

		paste_logo(image, g["away_team"], logo_sz, 60,     mid, anchor="mm")
		paste_logo(image, g["home_team"], logo_sz, W - 60, mid, anchor="mm")

		draw.text((120, mid - 10), g["away_team"], font=bold[20], fill=BLACK, anchor="lm")
		if g.get("away_record"):
			draw.text((120, mid + 12), g["away_record"], font=reg[10], fill=BLACK, anchor="lm")

		draw.text((W - 120, mid - 10), g["home_team"], font=bold[20], fill=BLACK, anchor="rm")
		if g.get("home_record"):
			draw.text((W - 120, mid + 12), g["home_record"], font=reg[10], fill=BLACK, anchor="rm")

		if is_live and g.get("possession") == g["away_team"]:
			draw.ellipse((240, mid-6, 252, mid+6), fill=RED)
		if is_live and g.get("possession") == g["home_team"]:
			draw.ellipse((W - 252, mid-6, W - 240, mid+6), fill=RED)

		draw.text((340, mid), g["away_score"], font=bold[32], fill=BLACK, anchor="rm")
		draw.text((400, mid), "-",             font=bold[20], fill=BLACK, anchor="mm")
		draw.text((460, mid), g["home_score"], font=bold[32], fill=BLACK, anchor="lm")

		draw.text((W // 2, mid + 22), g["status"], font=bold[14], fill=status_color, anchor="mt")

		if is_live and g.get("down_distance"):
			sit = g["down_distance"] + (f" at {g['spot']}" if g.get("spot") else "")
			draw.text((W // 2, mid + 38), sit, font=reg[12], fill=BLACK, anchor="mt")


def render_playoff2(image, draw, games, reg, bold):
	card_h    = GAMES_H // 2
	logo_sz   = 64
	stat_keys = STATS_PLAYOFF2

	for i, g in enumerate(games):
		y0  = HEADER_H + i * card_h
		mid = y0 + 70

		if i > 0:
			draw_divider(draw, y0)

		is_live      = g["state"] == "in"
		status_color = RED if is_live else BLACK

		paste_logo(image, g["away_team"], logo_sz, 50,     mid, anchor="mm")
		paste_logo(image, g["home_team"], logo_sz, W - 50, mid, anchor="mm")

		draw.text((120, mid - 14), g["away_team"], font=bold[24], fill=BLACK, anchor="lm")
		if g.get("away_record"):
			draw.text((120, mid + 12), g["away_record"], font=reg[11], fill=BLACK, anchor="lm")

		draw.text((W - 120, mid - 14), g["home_team"], font=bold[24], fill=BLACK, anchor="rm")
		if g.get("home_record"):
			draw.text((W - 120, mid + 12), g["home_record"], font=reg[11], fill=BLACK, anchor="rm")

		if is_live and g.get("possession") == g["away_team"]:
			draw.ellipse((252, mid-7, 264, mid+7), fill=RED)
		if is_live and g.get("possession") == g["home_team"]:
			draw.ellipse((W - 264, mid-7, W - 252, mid+7), fill=RED)

		draw.text((340, mid), g["away_score"], font=bold[40], fill=BLACK, anchor="rm")
		draw.text((400, mid), "-",             font=bold[24], fill=BLACK, anchor="mm")
		draw.text((460, mid), g["home_score"], font=bold[40], fill=BLACK, anchor="lm")

		status_y = mid + 30
		draw.text((W // 2, status_y), g["status"], font=bold[16], fill=status_color, anchor="mt")
		if is_live and g.get("down_distance"):
			sit = g["down_distance"] + (f" at {g['spot']}" if g.get("spot") else "")
			draw.text((W // 2, status_y + 18), sit, font=reg[13], fill=BLACK, anchor="mt")

		stats  = g.get("stats", {})
		away_s = stats.get(g["away_team"], {})
		home_s = stats.get(g["home_team"], {})
		if away_s or home_s:
			tbl_y = y0 + 110
			draw.line((0, tbl_y, W, tbl_y), fill=BLACK, width=1)
			draw.text((300, tbl_y + 2), g["away_team"], font=bold[11], fill=BLACK, anchor="rm")
			draw.text((500, tbl_y + 2), g["home_team"], font=bold[11], fill=BLACK, anchor="lm")
			tbl_y += 16
			for key in stat_keys:
				label = STAT_LABELS.get(key, key)
				draw.text((300, tbl_y), away_s.get(key, "-"), font=bold[13], fill=BLACK, anchor="rm")
				draw.text((400, tbl_y), label,                font=reg[12],  fill=RED,   anchor="mm")
				draw.text((500, tbl_y), home_s.get(key, "-"), font=bold[13], fill=BLACK, anchor="lm")
				tbl_y += 16
				if tbl_y >= y0 + card_h - 4:
					break


def render_single(image, draw, game, reg, bold):
	g       = game
	logo_sz = 96
	mid_y   = HEADER_H + 80

	is_live      = g["state"] == "in"
	status_color = RED if is_live else BLACK

	paste_logo(image, g["away_team"], logo_sz, 60,     mid_y, anchor="mm")
	paste_logo(image, g["home_team"], logo_sz, W - 60, mid_y, anchor="mm")

	draw.text((165, mid_y - 18), g["away_team"], font=bold[36], fill=BLACK, anchor="lm")
	if g.get("away_record"):
		draw.text((165, mid_y + 20), g["away_record"], font=reg[14], fill=BLACK, anchor="lm")

	draw.text((W - 165, mid_y - 18), g["home_team"], font=bold[36], fill=BLACK, anchor="rm")
	if g.get("home_record"):
		draw.text((W - 165, mid_y + 20), g["home_record"], font=reg[14], fill=BLACK, anchor="rm")

	if is_live and g.get("possession") == g["away_team"]:
		draw.ellipse((320, mid_y-9, 334, mid_y+9), fill=RED)
	if is_live and g.get("possession") == g["home_team"]:
		draw.ellipse((W - 334, mid_y-9, W - 320, mid_y+9), fill=RED)

	draw.text((360, mid_y), g["away_score"], font=bold[64], fill=BLACK, anchor="rm")
	draw.text((400, mid_y), "-",             font=bold[36], fill=BLACK, anchor="mm")
	draw.text((440, mid_y), g["home_score"], font=bold[64], fill=BLACK, anchor="lm")

	status_y = HEADER_H + 148
	draw.text((W // 2, status_y), g["status"], font=bold[24], fill=status_color, anchor="mt")

	if is_live and g.get("down_distance"):
		sit = g["down_distance"] + (f" at {g['spot']}" if g.get("spot") else "")
		draw.text((W // 2, status_y + 28), sit, font=reg[18], fill=BLACK, anchor="mt")

	stats  = g.get("stats", {})
	away_s = stats.get(g["away_team"], {})
	home_s = stats.get(g["home_team"], {})
	if away_s or home_s:
		tbl_y = status_y + 58
		draw.line((0, tbl_y, W, tbl_y), fill=BLACK, width=2)
		draw.text((340, tbl_y + 3), g["away_team"], font=bold[18], fill=BLACK, anchor="rm")
		draw.text((460, tbl_y + 3), g["home_team"], font=bold[18], fill=BLACK, anchor="lm")
		tbl_y += 26
		for key in STATS_SINGLE:
			label = STAT_LABELS.get(key, key)
			draw.text((340, tbl_y), away_s.get(key, "-"), font=bold[14], fill=BLACK, anchor="rm")
			draw.text((400, tbl_y), label,                font=bold[13], fill=RED,   anchor="mm")
			draw.text((460, tbl_y), home_s.get(key, "-"), font=bold[14], fill=BLACK, anchor="lm")
			tbl_y += 18
			if tbl_y >= H - FOOTER_H - 4:
				break


def render_frame(games, week_label, preset):
	image = Image.new("RGB", (W, H), WHITE)
	draw  = ImageDraw.Draw(image)
	reg, bold = load_fonts()

	draw_header(draw, week_label, bold)
	draw_footer(draw, reg)

	if not games:
		draw.text((W // 2, H // 2), "No games today", font=bold[24], fill=BLACK, anchor="mm")
	elif preset == "sunday":
		render_sunday(image, draw, games, reg, bold)
	elif preset == "playoff_3":
		render_playoff3(image, draw, games, reg, bold)
	elif preset == "playoff_2":
		render_playoff2(image, draw, games, reg, bold)
	elif preset == "single":
		render_single(image, draw, games[0], reg, bold)

	return image


def push(image):
	display.fill(Adafruit_EPD.WHITE)
	display.image(image)
	display.display()


def main():
	mode = "MOCK" if USE_MOCK else "LIVE"
	print(f"NFL Scoreboard e-ink driver starting [{mode}]")

	while True:
		try:
			if USE_MOCK:
				games      = list(MOCK_GAMES)
				week_label = MOCK_WEEK_LABEL
				if MOCK_PRESET == "single":
					games = games[:1]
				elif MOCK_PRESET == "playoff2":
					games = games[:2]
				elif MOCK_PRESET == "playoff3":
					games = games[:3]
			else:
				resp = requests.get(ESPN_URL, timeout=10)
				resp.raise_for_status()
				data       = resp.json()
				week_label = parse_week_label(data)
				games      = parse_games(data)

			games  = filter_and_sort_games(games)
			preset = determine_preset(len(games))

			if preset in ("single", "playoff_2"):
				stat_games = games[:1] if preset == "single" else games
				for game in stat_games:
					try:
						if USE_MOCK:
							game["stats"] = MOCK_STATS.get(game["id"], {})
						else:
							game["stats"] = fetch_game_stats(game["id"])
					except Exception as e:
						print(f"[stats] {game['id']}: {e}")
						game["stats"] = {}

			image = render_frame(games, week_label, preset)
			push(image)
			print(f"[{datetime.now().strftime('%H:%M:%S')}] Updated — {len(games)} games, preset={preset}")

		except Exception as e:
			print(f"[error] {e}")

		time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
	main()
