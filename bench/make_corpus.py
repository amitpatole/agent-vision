"""Generate the labelled AgentVision benchmark corpus (media & communications themed).

Every case is self-contained (no network): HTML with inline styles and data-URI/inline-SVG art,
or a PNG drawn with Pillow. ``manifest.json`` records the ground truth for each case:
``defect`` (the IssueKind a correct grader must report) or ``null`` for a clean case.
Re-run to regenerate: ``python bench/make_corpus.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "corpus"
BASE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>body{{font-family:Helvetica,Arial,sans-serif;margin:0;padding:32px;background:#fff;color:#111}}
h1{{font-size:32px;margin:0 0 12px}} p{{font-size:17px;line-height:1.5;max-width:720px}}
.btn{{display:inline-block;background:#0b5394;color:#fff;padding:12px 22px;border-radius:6px;
font-weight:600;text-decoration:none}} {css}</style></head><body>{body}</body></html>"""

POSTER = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' "
          "height='135'><rect width='240' height='135' fill='%23264653'/><circle cx='120' "
          "cy='67' r='30' fill='%23e9c46a'/></svg>")

PLAYER = """<div class="player"><div class="screen">{screen}</div>
<div class="bar"><span class="play">&#9654;</span><span class="track"><span class="pos"></span></span>
<span class="time">12:04 / 48:10</span></div></div><h1>{title}</h1><p>{desc}</p>"""
PLAYER_CSS = """.player{width:800px;background:#000;border-radius:8px;overflow:hidden}
.screen{height:420px;display:flex;align-items:center;justify-content:center;color:#fff;
font-size:20px;background:#1d3557} .bar{display:flex;align-items:center;gap:12px;padding:10px 16px;
background:#111;color:#eee;font-size:14px} .track{flex:1;height:4px;background:#444}
.pos{display:block;width:25%;height:4px;background:#e63946} h1{margin-top:20px}"""

SCHEDULE_ROW = "".join(
    f"<div class='slot'><b>{t}</b><span>{s}</span></div>"
    for t, s in [("18:00", "Evening News"), ("18:30", "Weather"), ("19:00", "Quiz Night"),
                 ("20:00", "Drama: Harbour"), ("21:00", "Documentary"), ("22:00", "Late News")]
)


def html(name, title, body, css=""):
    (OUT / name).write_text(BASE.format(title=title, body=body, css=css))


def png(name, lines, *, fg=(17, 17, 17), bg=(255, 255, 255), size=(1200, 630)):
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    try:
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
        small = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        big = small = ImageFont.load_default()
    y = 150
    for i, line in enumerate(lines):
        d.text((80, y), line, fill=fg, font=big if i == 0 else small)
        y += 110 if i == 0 else 60
    d.rectangle([80, 520, 330, 524], fill=(58, 138, 153))
    im.save(OUT / name)


CASES: list[dict] = []


def case(id, file, defect, note, expect=None):
    CASES.append({"id": id, "file": file, "defect": defect, "note": note,
                  "expect": expect or []})


def build():
    OUT.mkdir(exist_ok=True)
    # ---- defect cases --------------------------------------------------------------
    html("player_error.html", "Watch", PLAYER.format(
        screen="Error 403: Playback failed. This title is not available in your region.",
        title="Harbour, Season 2 Episode 4", desc="The crew returns to port as the storm hits."),
        PLAYER_CSS)
    case("player_error", "player_error.html", "error_text", "Player surface shows a playback error")

    html("hero_low_contrast.html", "Promo", """<h1>Stream the final season</h1>
<p class="faint">Every episode, ad-free, from Friday. Start your free trial today and cancel
anytime.</p><a class="btn" href="#">Start free trial</a>""", ".faint{color:#d4d4d4}")
    case("hero_low_contrast", "hero_low_contrast.html", "contrast",
         "Body copy is light grey on white (about 1.5:1)")

    html("schedule_overflow.html", "Schedule", f"<h1>Tonight on Channel 4</h1>"
         f"<div class='grid'>{SCHEDULE_ROW}</div>",
         ".grid{display:flex;width:2400px} .slot{width:380px;padding:16px;border:1px solid #ddd}"
         ".slot b{display:block}")
    case("schedule_overflow", "schedule_overflow.html", "overflow",
         "TV schedule grid is far wider than the viewport")

    html("headline_clipped.html", "News", """<div class="card"><h2>Central bank holds rates
steady as inflation cools faster than economists had expected across the region</h2></div>""",
         ".card{width:420px;height:58px;overflow:hidden;border:1px solid #ccc;padding:8px}"
         "h2{font-size:24px;margin:0;line-height:1.3}")
    case("headline_clipped", "headline_clipped.html", "clipped",
         "Headline is cut off by a fixed-height overflow:hidden card")

    html("thumbnail_broken.html", "Carousel", f"""<h1>Continue watching</h1><div class="row">
<figure><img src="{POSTER}" width="240" height="135" alt="Harbour"><figcaption>Harbour</figcaption></figure>
<figure><img src="posters/missing-quiz-night.jpg" width="240" height="135" alt="Quiz Night">
<figcaption>Quiz Night</figcaption></figure>
<figure><img src="{POSTER}" width="240" height="135" alt="Late News"><figcaption>Late News</figcaption></figure>
</div>""", ".row{display:flex;gap:20px} figure{margin:0}")
    case("thumbnail_broken", "thumbnail_broken.html", "broken_image",
         "One carousel poster fails to load")

    html("badge_overlap.html", "Live", """<div class="tile"><span class="live">LIVE NOW</span>
<h2>Election night results special</h2><p>Coverage from every count centre.</p></div>""",
         ".tile{position:relative;width:520px;padding:16px;border:1px solid #ddd}"
         ".live{position:absolute;top:22px;left:40px;background:#e63946;color:#fff;"
         "padding:6px 14px;font-weight:700;font-size:20px} h2{font-size:28px;margin:0}")
    case("badge_overlap", "badge_overlap.html", "overlap",
         "LIVE badge sits on top of the headline text")

    html("blank_page.html", "App", "<div id='root'></div>")
    case("blank_page", "blank_page.html", "blank", "App shell rendered nothing")

    html("typo_headline.html", "News", """<h1>Brekaing: Goverment anounces new broadband
plan</h1><p>The plan promises gigabit speeds to every houshold by the end of the decade.</p>""")
    case("typo_headline", "typo_headline.html", "typo", "Several misspellings in the headline")

    html("missing_subscribe.html", "Newsletter", """<h1>The Morning Briefing</h1>
<p>Five stories you need before 8am, written by our newsroom and delivered every weekday.</p>""")
    case("missing_subscribe", "missing_subscribe.html", "missing_element",
         "Brief requires a Subscribe button; the page has none",
         expect=["must: a Subscribe button is visible"])

    case("missing_subscribe_quoted", "missing_subscribe.html", "missing_element",
         "Same page, brief quotes the label, so OCR can decide it deterministically",
         expect=['must: a "Subscribe" button is visible'])

    html("svg_label_clipped.html", "Ratings", """<h1>Audience share by genre</h1>
<svg width="420" height="300" viewBox="0 0 420 300" style="border:1px solid #ddd">
<rect x="150" y="40" width="200" height="40" fill="#3a8a99"/>
<rect x="150" y="110" width="140" height="40" fill="#3a8a99"/>
<rect x="150" y="180" width="90" height="40" fill="#3a8a99"/>
<text x="-60" y="66" font-size="18">Documentary and Factual</text>
<text x="10" y="136" font-size="18">Drama</text><text x="10" y="206" font-size="18">Sport</text>
</svg>""")
    case("svg_label_clipped", "svg_label_clipped.html", "clipped",
         "Chart label starts outside the SVG viewBox and is cut off (the dogfood miss)")

    png("social_typo.png", ["Premeire this Friday", "Harbour returns for its final seasn",
                            "Streaming only on Channel 4"])
    case("social_typo", "social_typo.png", "typo", "Raster social card with misspellings")

    png("social_low_contrast.png", ["Premiere this Friday", "Harbour returns for its final season",
                                    "Streaming only on Channel 4"], fg=(225, 225, 225))
    case("social_low_contrast", "social_low_contrast.png", "contrast",
         "Raster social card with near-white text on white")

    # ---- clean cases ---------------------------------------------------------------
    html("player_ok.html", "Watch", PLAYER.format(
        screen=f'<img src="{POSTER}" width="480" height="270" alt="Harbour">',
        title="Harbour, Season 2 Episode 4", desc="The crew returns to port as the storm hits."),
        PLAYER_CSS)
    case("player_ok", "player_ok.html", None, "Healthy player page")

    html("hero_ok.html", "Promo", """<h1>Stream the final season</h1>
<p>Every episode, ad-free, from Friday. Start your free trial today and cancel anytime.</p>
<a class="btn" href="#">Start free trial</a>""")
    case("hero_ok", "hero_ok.html", None, "Readable promo hero")

    html("schedule_ok.html", "Schedule", f"<h1>Tonight on Channel 4</h1>"
         f"<div class='grid'>{SCHEDULE_ROW}</div>",
         ".grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;max-width:900px}"
         ".slot{padding:16px;border:1px solid #ddd} .slot b{display:block}")
    case("schedule_ok", "schedule_ok.html", None, "Schedule grid that fits")

    html("headline_ok.html", "News", """<div class="card"><h2>Central bank holds rates
steady as inflation cools</h2><p>Economists had expected a cut later in the year.</p></div>""",
         ".card{width:520px;border:1px solid #ccc;padding:12px} h2{font-size:24px;margin:0}")
    case("headline_ok", "headline_ok.html", None, "Headline card with room to breathe")

    html("carousel_ok.html", "Carousel", f"""<h1>Continue watching</h1><div class="row">
<figure><img src="{POSTER}" width="240" height="135" alt="Harbour"><figcaption>Harbour</figcaption></figure>
<figure><img src="{POSTER}" width="240" height="135" alt="Quiz Night"><figcaption>Quiz Night</figcaption></figure>
<figure><img src="{POSTER}" width="240" height="135" alt="Late News"><figcaption>Late News</figcaption></figure>
</div>""", ".row{display:flex;gap:20px} figure{margin:0}")
    case("carousel_ok", "carousel_ok.html", None, "Carousel with every poster loaded")

    html("subscribe_ok.html", "Newsletter", """<h1>The Morning Briefing</h1>
<p>Five stories you need before 8am, written by our newsroom and delivered every weekday.</p>
<a class="btn" href="#">Subscribe</a>""")
    case("subscribe_ok", "subscribe_ok.html", None, "Newsletter page with its Subscribe button",
         expect=["must: a Subscribe button is visible"])

    case("subscribe_ok_quoted", "subscribe_ok.html", None,
         "Same clean page, brief quotes the label",
         expect=['must: a "Subscribe" button is visible'])

    html("chart_ok.html", "Ratings", """<h1>Audience share by genre</h1>
<svg width="460" height="300" viewBox="0 0 460 300" style="border:1px solid #ddd">
<rect x="200" y="40" width="200" height="40" fill="#3a8a99"/>
<rect x="200" y="110" width="140" height="40" fill="#3a8a99"/>
<rect x="200" y="180" width="90" height="40" fill="#3a8a99"/>
<text x="10" y="66" font-size="18">Documentary</text>
<text x="10" y="136" font-size="18">Drama</text><text x="10" y="206" font-size="18">Sport</text>
</svg>""")
    case("chart_ok", "chart_ok.html", None, "Chart with every label inside the canvas")

    png("social_ok.png", ["Premiere this Friday", "Harbour returns for its final season",
                          "Streaming only on Channel 4"])
    case("social_ok", "social_ok.png", None, "Clean raster social card")

    (Path(__file__).parent / "manifest.json").write_text(json.dumps(CASES, indent=2) + "\n")


if __name__ == "__main__":
    build()
    print(f"wrote {len(CASES)} cases to {OUT}")
