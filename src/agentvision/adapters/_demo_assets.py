"""Self-contained demo HTML so `agentvision demo` works after a pip install (no repo)."""

BROKEN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Dashboard (broken)</title><style>
body{font-family:system-ui,sans-serif;margin:0;padding:24px;background:#fff}
h1{color:#111}
p.note{color:#c9c9c9;background:#fff;font-size:15px}
.wide-row{width:2200px;background:#eef;padding:16px}
.card{display:inline-block;width:600px;height:80px;background:#f4f4f4;margin-right:16px}
.cta{color:#9fcaff;background:#fff;font-size:14px}
</style></head><body>
<h1>Quarterly Dashboard</h1>
<p class="note">Revenue is up 12% over last quarter. This summary text is hard to read.</p>
<img src="missing-logo.png" alt="Company logo" width="160" height="48">
<div class="wide-row"><span class="card">Metric A</span><span class="card">Metric B</span>
<span class="card">Metric C</span></div>
<p class="cta">Click here to view the full report</p>
</body></html>"""

FIXED_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Dashboard (fixed)</title><style>
body{font-family:system-ui,sans-serif;margin:0;padding:24px;background:#fff}
h1{color:#111}
p.note{color:#333;background:#fff;font-size:15px}
.row{display:flex;flex-wrap:wrap;gap:16px}
.card{flex:1 1 200px;min-width:0;height:80px;background:#f4f4f4}
.cta{color:#0b5cad;background:#fff;font-size:14px;font-weight:600}
</style></head><body>
<h1>Quarterly Dashboard</h1>
<p class="note">Revenue is up 12% over last quarter. This summary text is easy to read.</p>
<img alt="Company logo" width="160" height="48" src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='48'><rect width='160' height='48' fill='%230b5cad'/><text x='12' y='30' fill='white' font-family='sans-serif' font-size='18'>ACME</text></svg>">
<div class="row"><span class="card">Metric A</span><span class="card">Metric B</span>
<span class="card">Metric C</span></div>
<p class="cta">Click here to view the full report</p>
</body></html>"""
