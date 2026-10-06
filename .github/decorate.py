import base64
import glob
import json
import math
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)

FONT = os.path.join(os.path.dirname(__file__), "SpaceGrotesk-subset.woff2")
FONT_CSS = (
    '\n@font-face { font-family: "Space Grotesk"; font-weight: 300 700; src: url(data:font/woff2;base64,'
    + base64.b64encode(open(FONT, "rb").read()).decode()
    + ') format("woff2"); }\n* { font-family: "Space Grotesk", "Helvetica", "Arial", sans-serif; }'
)
DATE_RANGE = re.compile(r"\d{4}-\d{2}-\d{2} / \d{4}-\d{2}-\d{2}")

QUERY = """query($login: String!) { user(login: $login) { contributionsCollection {
  restrictedContributionsCount
  contributionCalendar { weeks { contributionDays { date contributionCount weekday } } }
} } }"""


def fetch_stats(login, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}"},
    )
    coll = json.load(urllib.request.urlopen(req))["data"]["user"]["contributionsCollection"]
    days = [d for w in coll["contributionCalendar"]["weeks"] for d in w["contributionDays"]]
    total = sum(d["contributionCount"] for d in days)
    peak = max(days, key=lambda d: d["contributionCount"])
    streak = best = 0
    for d in days:
        streak = streak + 1 if d["contributionCount"] else 0
        best = max(best, streak)
    weekend = sum(d["contributionCount"] for d in days if d["weekday"] in (0, 6))
    return {
        "restricted": coll["restrictedContributionsCount"],
        "peak": peak["contributionCount"],
        "peak_date": date.fromisoformat(peak["date"]).strftime("%b %-d"),
        "streak": best,
        "weekend_pct": round(100 * weekend / total) if total else 0,
        "first_weekday": days[0]["weekday"],
        "day_count": len(days),
    }


def el(tag, parent=None, text=None, **attrs):
    attrs = {k.rstrip("_").replace("_", "-"): str(v) for k, v in attrs.items()}
    e = ET.Element(f"{{{NS}}}{tag}", attrs) if parent is None else ET.SubElement(parent, f"{{{NS}}}{tag}", attrs)
    e.text = text
    return e


def captions(s):
    g = el("g")
    lines = [
        (f"{s['restricted']:,} of these are classified.", "28px", "fill-strong", "bold"),
        ("You will have to take my word for them.", "20px", "fill-weak", "normal"),
        (f"Peak day: {s['peak']} on {s['peak_date']}. Sleep is optional.", "22px", "fill-fg", "normal"),
        (f"Longest streak: {s['streak']} days. Then I touched grass.", "22px", "fill-fg", "normal"),
        (f"Weekend contributions: {s['weekend_pct']}%. Allegedly.", "22px", "fill-fg", "normal"),
    ]
    y = 90
    for i, (txt, size, cls, weight) in enumerate(lines):
        t = el("text", g, txt, x=1240, y=y, class_=cls, text_anchor="end", opacity=0,
               style=f"font-size: {size}; font-weight: {weight}")
        el("animate", t, attributeName="opacity", values="0;1", dur="0.6s",
           begin=f"{3 + i * 0.4}s", fill="freeze")
        y += 52 if i == 0 else 40
        if i == 1:
            y += 18
    return g


def car(s):
    # Mirrors create-3d-contrib.ts (v0.9.3) grid math so the car drives the front edge (Saturday row).
    dx = 1280 / 64
    dy = dx * math.tan(math.radians(30))
    weeks = math.ceil((s["day_count"] + s["first_weekday"]) / 7)
    offset_y = 850 - (weeks + 7) * dy

    def edge(w):
        return 7 * dx + (w - 6) * dx - 2, offset_y + (w + 6) * dy + 6

    # Starts and ends off-canvas so the loop restart is never visible.
    (x0, y0), (x1, y1) = edge(-5), edge(weeks + 5)
    mover = el("g")
    el("animateMotion", mover, path=f"M{x0:.1f},{y0:.1f} L{x1:.1f},{y1:.1f}", dur="16s",
       repeatCount="indefinite")
    body = el("g", mover, transform="skewY(30) scale(1.5)")
    for cx in (-24, -30, -36):
        puff = el("circle", body, cx=cx, cy=-5, r=3, fill="#9aa0a6", opacity="0")
        el("animate", puff, attributeName="opacity", values="0;0.6;0", dur="0.9s",
           begin=f"{(cx + 36) / 40:.2f}s", repeatCount="indefinite")
        el("animate", puff, attributeName="r", values="2;6", dur="0.9s",
           begin=f"{(cx + 36) / 40:.2f}s", repeatCount="indefinite")
    el("rect", body, x=-22, y=-14, width=44, height=10, rx=3, fill="#e10600")
    el("path", body, d="M-12,-14 L-6,-23 L10,-23 L16,-14 Z", fill="#e10600")
    el("path", body, d="M-9,-15 L-4.5,-21 L1,-21 L1,-15 Z M3,-15 L3,-21 L9,-21 L13,-15 Z", fill="#cfe8ff")
    el("rect", body, x=-22, y=-9, width=44, height=2, fill="#ffffff", opacity="0.8")
    el("circle", body, cx=20, cy=-11, r=1.8, fill="#ffd400")
    for wx in (-12, 12):
        el("circle", body, cx=wx, cy=-4, r=5, fill="#1b1b1b")
        el("circle", body, cx=wx, cy=-4, r=2, fill="#b0b0b0")
        spokes = el("g", el("g", body, transform=f"translate({wx} -4)"))
        el("path", spokes, d="M-3.5,0 H3.5 M0,-3.5 V3.5", stroke="#6b6b6b", stroke_width=1)
        el("animateTransform", spokes, attributeName="transform", type="rotate",
           values="0;360", dur="0.4s", repeatCount="indefinite")
    return mover


def decorate(path, stats):
    tree = ET.parse(path)
    root = tree.getroot()
    groups = [c for c in root if c.tag == f"{{{NS}}}g"]
    # v0.9.3 layout: 3D calendar, radar, language pie, totals
    assert len(groups) == 4, (path, len(groups))
    for g in groups[1:3]:
        root.remove(g)
    parents = {c: p for p in root.iter() for c in p}
    for t in list(root.iter(f"{{{NS}}}text")):
        if DATE_RANGE.fullmatch(t.text or ""):
            parents[t].remove(t)
    # Transparent background so the image blends into GitHub's light/dark page colour.
    for r in root.findall(f"{{{NS}}}rect[@class='fill-bg']"):
        root.remove(r)
    root.find(f"{{{NS}}}style").text += FONT_CSS
    root.append(captions(stats))
    root.append(car(stats))
    tree.write(path, encoding="unicode")


if __name__ == "__main__":
    stats = fetch_stats(sys.argv[2], os.environ["GITHUB_TOKEN"])
    for p in glob.glob(f"{sys.argv[1]}/*.svg"):
        decorate(p, stats)
