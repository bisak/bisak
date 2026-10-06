import base64
import glob
import json
import math
import os
import random
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


def sprite(name):
    # Side-profile renders of my own cars (Nano Banana pass over my photos, then cut out).
    with open(os.path.join(os.path.dirname(__file__), name), "rb") as f:
        return "data:image/webp;base64," + base64.b64encode(f.read()).decode()


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


def ground(s):
    """Map grid coordinates to the SVG. Mirrors create-3d-contrib.ts (v0.9.3).

    W counts weeks (left to right), D counts weekdays towards the viewer; the bars occupy
    0 <= D <= 7, so D > 7 is the strip in front of the graph where the road goes.
    """
    dx = 1280 / 64
    dy = dx * math.tan(math.radians(30))
    weeks = math.ceil((s["day_count"] + s["first_weekday"]) / 7)
    offset_y = 850 - (weeks + 7) * dy
    return weeks, lambda w, d: (160 + (w - d) * dx, offset_y + (w + d - 1) * dy)


EVO_LANE, YARIS_LANE = 8.2, 10.2


def lane(s, d):
    weeks, at = ground(s)
    # Starts and ends off-canvas so the loop restart is never visible.
    (x0, y0), (x1, y1) = at(-10, d), at(weeks + 9, d)
    return f"M{x0:.1f},{y0:.1f} L{x1:.1f},{y1:.1f}"


def road(s):
    weeks, at = ground(s)
    w0, w1 = -15, weeks + 15

    def line(d):
        (x0, y0), (x1, y1) = at(w0, d), at(w1, d)
        return f"M{x0:.1f},{y0:.1f} L{x1:.1f},{y1:.1f}"

    g = el("g")
    corners = [at(w0, 7.25), at(w1, 7.25), at(w1, 11.15), at(w0, 11.15)]
    el("path", g, d="M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in corners) + " Z",
       class_="fill-weak", opacity="0.16")
    for d in (7.4, 11.0):
        el("path", g, d=line(d), class_="stroke-weak", stroke_width=2, opacity="0.6", fill="none")
    el("path", g, d=line((EVO_LANE + YARIS_LANE) / 2), class_="stroke-weak", stroke_width=2,
       stroke_dasharray="26 20", opacity="0.6", fill="none")
    return g


def wave(rng, period, terms):
    # Random smooth periodic signal: integer harmonics of `period`, so it loops seamlessly.
    parts = [(amp, k, rng.uniform(0, 2 * math.pi)) for amp, k in terms]
    return lambda t: sum(a * math.sin(2 * math.pi * k * t / period + ph) for a, k, ph in parts)


def driving(path, laps, scale, seed):
    """Car on `path` with a different speed profile every lap, lane drift and suspension bob.

    laps: [(seconds on screen, seconds parked off-canvas before the next lap)]. Lap lengths
    differ between cars, so overtakes land at different places each time.
    """
    rng = random.Random(seed)
    times, points, t = [0.0], [0.0], 0.0
    shown = [(0.0, "visible")]
    for lap, gap in laps:
        n = int(lap * 4)
        speed = wave(rng, lap, [(rng.uniform(0.15, 0.3), 1), (rng.uniform(0.08, 0.18), 2),
                                (rng.uniform(0.04, 0.1), 4)])
        v = [1 + speed(lap * (i + 0.5) / n) for i in range(n)]
        dist = 0.0
        for i in range(n):
            dist += v[i] / sum(v)
            times.append(t + lap * (i + 1) / n)
            points.append(min(dist, 1.0))
        shown.append((t + lap, "hidden"))
        t += lap + gap
        shown.append((t + 0.002, "visible"))
        times += [t, t + 0.002]  # hold off-canvas, then jump back to the start (also off-canvas)
        points += [1.0, 0.0]
    total = times[-1]
    mover = el("g")
    el("animateMotion", mover, path=path, dur=f"{total:.3f}s", repeatCount="indefinite",
       calcMode="linear", keyTimes=";".join(f"{x / total:.6f}" for x in times[:-1]) + ";1",
       keyPoints=";".join(f"{x:.4f}" for x in points))
    # The 2 ms jump back sweeps the whole path; keep the car hidden so no frame can catch it.
    shown.pop()
    el("animate", mover, attributeName="visibility", calcMode="discrete", dur=f"{total:.3f}s",
       repeatCount="indefinite", keyTimes=";".join(f"{x / total:.6f}" for x, _ in shown),
       values=";".join(v for _, v in shown))
    period = round(rng.uniform(9, 14), 1)
    drift = wave(rng, period, [(3.0, 1), (1.5, 2), (0.6, 3)])
    bob = wave(rng, period, [(0.5, round(period / 0.55)), (0.3, round(period / 0.37))])
    samples = [i * 0.1 for i in range(int(period * 10) + 1)]
    sway = el("g", mover)
    el("animateTransform", sway, attributeName="transform", type="translate", dur=f"{period}s",
       repeatCount="indefinite", values=";".join(
           f"{-0.866 * drift(x):.2f} {0.5 * drift(x) + bob(x):.2f}" for x in samples))
    return mover, el("g", sway, transform=f"scale({scale})")


def iso_car(body, name, w, h):
    # Isometric render, nose towards the lower right; (0, 0) is the middle of the car's footprint.
    el("ellipse", body, cx=0, cy=0, rx=w * 0.42, ry=h * 0.16, transform="rotate(30)",
       fill="#000000", opacity="0.22")
    el("image", body, href=sprite(name), x=-w / 2, y=-h * 0.6, width=w, height=h)


def evo_x(s):
    mover, body = driving(lane(s, EVO_LANE), [(15.5, 0.8), (18.0, 1.6), (13.9, 0.4)], 1, seed=10)
    for i in range(3):
        cx, cy = -86 - i * 9, -24 - i * 5  # behind the rear bumper, along the direction of travel
        puff = el("circle", body, cx=cx, cy=cy, r=4, fill="#9aa0a6", opacity="0")
        el("animate", puff, attributeName="opacity", values="0;0.5;0", dur="0.9s",
           begin=f"{i * 0.3:.1f}s", repeatCount="indefinite")
        el("animate", puff, attributeName="r", values="3;9", dur="0.9s",
           begin=f"{i * 0.3:.1f}s", repeatCount="indefinite")
    iso_car(body, "evo-x.webp", 185, 131)
    return mover


def gr_yaris(s):
    # Roughly twice the Evo's pace in the lane nearer the viewer; lap lengths differ from the
    # Evo's so the overtake happens somewhere new each time.
    mover, body = driving(lane(s, YARIS_LANE), [(7.4, 0.3), (9.1, 1.2), (6.6, 0.5), (8.2, 2.0)], 1, seed=96)
    for i, off in enumerate((-14, 0, 14)):
        x0, y0 = -70 + off * 0.5, -22 + off * 0.866
        line = el("path", body, d=f"M{x0:.1f},{y0:.1f} l-42,-24.2", stroke="#c8ccd2",
                  stroke_width=1.6, stroke_linecap="round", opacity="0")
        el("animate", line, attributeName="opacity", values="0;0.8;0", dur="0.3s",
           begin=f"{i * 0.1:.1f}s", repeatCount="indefinite")
    iso_car(body, "gr-yaris.webp", 165, 125.5)
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
    root.append(road(stats))
    root.append(evo_x(stats))
    root.append(gr_yaris(stats))
    tree.write(path, encoding="unicode")


if __name__ == "__main__":
    stats = fetch_stats(sys.argv[2], os.environ["GITHUB_TOKEN"])
    for p in glob.glob(f"{sys.argv[1]}/*.svg"):
        decorate(p, stats)
