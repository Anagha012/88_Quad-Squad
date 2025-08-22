
import concurrent.futures
import json
import math
import time
from collections import Counter, defaultdict

from bs4 import BeautifulSoup


import requests

from flask import Flask, request, redirect, url_for, render_template_string

app = Flask(__name__)

# =============================
# Core crawling + auditing
# (merged from both of your scripts)
# =============================
SECURITY_HEADERS = [
    "Content-Security-Policy",
    "Strict-Transport-Security",
    "X-Frame-Options",
    "X-Content-Type-Options",
]


def fetch_page(url, timeout=12):
    """Fetch a single page and measure elapsed time."""
    try:
        start = time.time()
        r = requests.get(url, timeout=timeout)
        elapsed = round(time.time() - start, 3)
        return r, elapsed, None
    except Exception as e:
        return None, None, str(e)


def analyze_page(url):
    """Analyze a page for status, load time, security, seo, accessibility."""
    result = {
        "url": url,
        "status": None,
        "load_time": None,
        "security": [],
        "seo": [],
        "accessibility": [],
        "error": None,
    }

    r, elapsed, err = fetch_page(url)
    if err or r is None:
        result["status"] = "Error"
        result["error"] = err or "Fetch error"
        return result

    result["status"] = r.status_code
    result["load_time"] = elapsed

    # Security checks
    if url.startswith("http://"):
        result["security"].append("Site is not using HTTPS")
    for h in SECURITY_HEADERS:
        if h not in r.headers:
            result["security"].append(f"Missing security header: {h}")

    # SEO & Accessibility
    soup = BeautifulSoup(r.text, "html.parser")
    # SEO
    if not soup.title or not (soup.title.string or "").strip():
        result["seo"].append("Missing <title> tag")
    if not soup.find("meta", attrs={"name": "description"}):
        result["seo"].append("Missing meta description")
    if not soup.find("h1"):
        result["seo"].append("Missing <h1> heading")

    # Accessibility
    html_tag = soup.find("html")
    if html_tag and not html_tag.get("lang"):
        result["accessibility"].append("<html> tag missing 'lang' attribute")
    for img in soup.find_all("img"):
        if not img.get("alt"):
            result["accessibility"].append("Image missing alt attribute")
            break

    return result

from urllib.parse import urljoin,urlparse
def crawl_site(start_url, max_pages=10):
    """Crawl up to max_pages, following internal and external links."""
    visited = set()
    queue = [start_url]
    results = []

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        # Analyze page
        res = analyze_page(url)
        results.append(res)

        # Fetch page HTML for link extraction
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                link = urljoin(url, a["href"])
                link = link.split('#')[0]
                # only follow same host
                if urlparse(link).netloc == urlparse(start_url).netloc:
                    if link not in visited and link not in queue:
                        queue.append(link)

        except Exception as e:
            print(f"Failed to fetch {url}: {e}")
            continue

    return results



# =============================
# Load testing + autoscaling
# =============================

def fetch_once(session, url):
    try:
        start = time.time()
        resp = session.get(url, timeout=12)
        t = round(time.time() - start, 3)
        return {"status": resp.status_code, "time": t}
    except Exception:
        return {"status": "Error", "time": None}


def run_load_test(url, users=100):
    """Simulate concurrent users hitting a single URL in waves (no hard cap)."""
    results = []
    batch_size = 300  # safe number of threads per wave
    remaining = users
    with requests.Session() as sess:
        while remaining > 0:
            wave = min(batch_size, remaining)
            with concurrent.futures.ThreadPoolExecutor(max_workers=wave) as ex:
                futs = [ex.submit(fetch_once, sess, url) for _ in range(wave)]
                for f in concurrent.futures.as_completed(futs):
                    results.append(f.result())
            remaining -= wave
    return results


def summarize_load_results(results):
    total = len(results)
    success = sum(1 for r in results if r["status"] == 200)
    failures = total - success
    times = [r["time"] for r in results if r["time"] is not None]
    avg = round(sum(times) / len(times), 3) if times else None
    p95 = None
    if times:
        s = sorted(times)
        idx = int(0.95 * (len(s) - 1))
        p95 = s[idx]
    return {
        "total": total,
        "success": success,
        "failures": failures,
        "avg": avg,
        "p95": p95,
        "histogram": Counter(int((t or 0) * 10) / 10 for t in times),  # 0.1s buckets
    }


def auto_scale(avg_time, target, load_summary):
    if avg_time is None or avg_time <= 0:
        return {
            "servers": 1,
            "scaled_avg": avg_time,
            "processed": load_summary["success"],
            "failed": load_summary["failures"]
        }

    servers = max(1, math.ceil(avg_time / target))
    scaled_avg = round(avg_time / servers, 3)

    # Simplified assumption: all requests succeed after scaling
    processed = load_summary["total"]
    failed = 0

    return {
        "servers": servers,
        "scaled_avg": scaled_avg,
        "processed": processed,
        "failed": failed
    }


# =============================
# Recommendations engine
# =============================

def build_recommendations(audit_results, load_summary, scaled):
    recs = []

    # Security
    sec_count = sum(len(r.get("security", [])) for r in audit_results)
    if sec_count:
        recs += [
            "Enable HTTPS and redirect HTTP to HTTPS.",
            "Add missing headers: Content-Security-Policy, Strict-Transport-Security, X-Frame-Options, X-Content-Type-Options.",
        ]

    # SEO
    if any(r.get("seo") for r in audit_results):
        recs += [
            "Add a concise, unique <title> and meta description to every page.",
            "Ensure each page has exactly one <h1> that matches page intent.",
        ]

    # Accessibility
    if any(r.get("accessibility") for r in audit_results):
        recs += [
            "Add meaningful alt text to informative images (skip decorative).",
            "Set <html lang=...> to the primary language of the content.",
        ]

    # Performance / Traffic
    if load_summary.get("avg") and load_summary["avg"] > 1.5:
        servers = scaled["servers"]
        scaled_avg = scaled["scaled_avg"]

        recs += [
            f"Autoscale to ~{servers} instances to keep mean latency ~{scaled_avg}s under load.",
            "Add a CDN for static assets; enable HTTP/2 and compression (gzip/brotli).",
            "Introduce server-side caching for expensive routes; consider a reverse proxy cache.",
            "Use connection pooling for DB; add read replicas if DB bound.",
            "Implement rate limiting and a queue for bursty write operations.",
        ]
    else:
        recs.append("Current capacity looks okay; keep autoscaling rules in place for spikes.")

    # General quality
    recs += [
        "Implement observability: SLIs/SLOs, structured logs, distributed tracing.",
        "Add automated CI checks for Lighthouse/axe-core and security headers.",
    ]

    # Dedupe while keeping order
    seen = set()
    deduped = []
    for r in recs:
        if r not in seen:
            deduped.append(r)
            seen.add(r)
    return deduped


# =============================
# Web UI (single-file template)
# =============================
INDEX_TMPL = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Web Audit & Auto-Scale Lab</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root{--bg1:#0ea5e9;--bg2:#a78bfa;--bg3:#22c55e;--bg4:#f97316;--card:#0b1020aa;--glass:#ffffff22;--text:#e5e7eb;}
    *{box-sizing:border-box} body{margin:0;font-family:Inter,system-ui,-apple-system,sans-serif;color:var(--text);
      background: radial-gradient(1000px 600px at 20% 10%, #1f2937, #0b1020),
                  linear-gradient(130deg, #0ea5e933, #a78bfa33, #22c55e33);
      min-height:100vh;}
    .hero{position:relative;overflow:hidden;padding:64px 24px;text-align:center}
    .pulse{position:absolute;inset:-200px;background: conic-gradient(from 0deg, #0ea5e977, #a78bfa77, #22c55e77, #f9731677, #0ea5e977);
      filter: blur(80px); animation: spin 12s linear infinite;}
    @keyframes spin{to{transform: rotate(1turn)}}
    h1{font-weight:800;font-size:clamp(28px,4vw,44px);margin:0 0 8px}
    .tag{display:inline-block;padding:6px 12px;border-radius:999px;background:var(--glass);backdrop-filter: blur(6px);border:1px solid #ffffff33}
    .wrap{max-width:1100px;margin:0 auto;padding:0 16px}
    .card{background:var(--card);border:1px solid #ffffff1a;border-radius:20px;padding:18px;backdrop-filter: blur(8px);box-shadow:0 10px 30px #0006}
    .grid{display:grid;gap:18px}
    .g2{grid-template-columns:repeat(2,minmax(0,1fr))}
    .g3{grid-template-columns:repeat(3,minmax(0,1fr))}
    @media(max-width:900px){.g2,.g3{grid-template-columns:1fr}}
    label{display:block;margin:8px 0 6px;font-weight:600}
    input{width:100%;padding:12px 14px;border-radius:12px;border:1px solid #ffffff2a;background:#0b1020;color:#e5e7eb}
    button{cursor:pointer;border:0;padding:12px 16px;border-radius:12px;font-weight:700;color:#0b1020;background:linear-gradient(90deg,var(--bg1),var(--bg2));}
    .kpi{display:flex;align-items:center;gap:12px}
    .kpi .bubble{width:12px;height:12px;border-radius:999px}
    .list li{margin:8px 0}
    .footer{opacity:.7;text-align:center;padding:18px}
  </style>
</head>
<body>
  <section class="hero">
    <div class="pulse"></div>
    <div class="wrap">
      <span class="tag">✨ Website Auditor • Load Tester • Auto‑Scaler</span>
      <h1>Find issues, visualize impact, and fix them.</h1>
      <p style="opacity:.85">Enter a URL and how many pages to scan. (Optional) set concurrent users for a burst test.</p>
    </div>
  </section>

  <section class="wrap">
    <form class="card grid g3" method="post" action="{{ url_for('run_audit') }}">
      <div>
        <label>Website URL</label>
        <input name="url" type="url" placeholder="https://example.com" required value="{{ url or '' }}"/>
      </div>
      <div>
        <label>Pages to crawl (same host)</label>
        <input name="pages" type="number" min="1" max="100" value="{{ pages or 2 }}"/>
      </div>
      <div>
        <label>Simulated concurrent users</label>
        <input name="users" type="number" min="1" value="{{ users or 150 }}"/>
      </div>
      <div style="grid-column:1/-1;display:flex;gap:12px;align-items:center;justify-content:flex-end">
        <button type="submit">Run Audit & Test</button>
      </div>
    </form>
  </section>

  {% if results %}
  <section class="wrap" style="margin-top:24px">
    <div class="grid g3">
      <div class="card">
        <div class="kpi"><span class="bubble" style="background:#22c55e"></span>
          <div><div style="opacity:.7">Pages Scanned</div><div style="font-size:28px;font-weight:800">{{ results|length }}</div></div>
        </div>
      </div>
      <div class="card">
        <div class="kpi"><span class="bubble" style="background:#f97316"></span>
          <div><div style="opacity:.7">Issues Found</div><div style="font-size:28px;font-weight:800">{{ total_issues }}</div></div>
        </div>
      </div>
      <div class="card">
        <div class="kpi"><span class="bubble" style="background:#0ea5e9"></span>
          <div><div style="opacity:.7">Avg Load (under burst)</div><div style="font-size:28px;font-weight:800">{{ load_summary.avg or 'n/a' }}s</div></div>
        </div>
      </div>
    </div>
  </section>

  <section class="wrap" style="margin-top:18px">
  <div class="card">
    <h3 style="margin-top:0">Detailed Page Issues</h3>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;color:#e5e7eb">
        <thead>
          <tr style="background:#0ea5e933">
            <th style="padding:8px;text-align:left">Page</th>
            <th style="padding:8px;text-align:left">Status</th>
            <th style="padding:8px;text-align:left">Load (s)</th>
            <th style="padding:8px;text-align:left">Security</th>
            <th style="padding:8px;text-align:left">SEO</th>
            <th style="padding:8px;text-align:left">Accessibility</th>
          </tr>
        </thead>
        <tbody>
          {% for r in results %}
          <tr style="border-bottom:1px solid #ffffff22">
            <td style="padding:8px"><a href="{{ r.url }}" target="_blank" style="color:#38bdf8;text-decoration:none">{{ r.url }}</a></td>
            <td style="padding:8px">{{ r.status }}</td>
            <td style="padding:8px">{{ r.load_time or 'n/a' }}</td>
            <td style="padding:8px">
              {% if r.security %}
                <ul style="margin:0;padding-left:16px">
                  {% for s in r.security %}
                  <li>{{ s }}</li>
                  {% endfor %}
                </ul>
              {% else %}
                <span style="opacity:.7">No issues</span>
              {% endif %}
            </td>
            <td style="padding:8px">
              {% if r.seo %}
                <ul style="margin:0;padding-left:16px">
                  {% for s in r.seo %}
                  <li>{{ s }}</li>
                  {% endfor %}
                </ul>
              {% else %}
                <span style="opacity:.7">No issues</span>
              {% endif %}
            </td>
            <td style="padding:8px">
              {% if r.accessibility %}
                <ul style="margin:0;padding-left:16px">
                  {% for s in r.accessibility %}
                  <li>{{ s }}</li>
                  {% endfor %}
                </ul>
              {% else %}
                <span style="opacity:.7">No issues</span>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</section>


  <section class="wrap" style="margin-top:18px">
    <div class="grid g2">
      <div class="card">
        <h3 style="margin-top:0">Issue Breakdown</h3>
        <canvas id="issuesPie"></canvas>
      </div>
      <div class="card">
        <h3 style="margin-top:0">Page Load Times</h3>
        <canvas id="barTimes"></canvas>
      </div>
    </div>
  </section>

  <section class="wrap" style="margin-top:18px">
    <div class="grid g2">
      <div class="card">
        <h3 style="margin-top:0">Burst Test ({{ users }} users)</h3>
        <p style="margin:.2rem 0 .8rem;opacity:.85">Requests: {{ load_summary.total }}, Success: {{ load_summary.success }}, Failures: {{ load_summary.failures }}, p95: {{ load_summary.p95 or 'n/a' }}s</p>
        <canvas id="hist"></canvas>
      </div>
     <div class="card">
  <h3 style="margin-top:0">Auto-Scaling Suggestion ({{ users }} users)</h3>
  <p style="margin:.2rem 0 .8rem;opacity:.85">
    Servers: {{ scaled.servers }},
    Requests (after scale): {{ scaled.processed }},
    Success: {{ scaled.processed }},
    Failures: {{ scaled.failed }},
    Avg: {{ scaled.scaled_avg or 'n/a' }}s
  </p>
  <canvas id="scaleLine"></canvas>
</div>

    </div>
  </section>

  <section class="wrap" style="margin-top:18px">
    <div class="card">
      <h3 style="margin-top:0">Actionable Recommendations</h3>
      <ul class="list">
        {% for r in recommendations %}
          <li>✅ {{ r }}</li>
        {% endfor %}
      </ul>
    </div>
  </section>
  {% endif %}

  <div class="footer">Built for learning & diagnostics. Please use responsibly.</div>

<script>
  {% if results %}
  // ======= Issue Pie =======
  const issuesPie = new Chart(document.getElementById('issuesPie'), {
    type: 'pie',
    data: {
      labels: ['Security','SEO','Accessibility'],
      datasets: [{ data: [{{ counts.security }}, {{ counts.seo }}, {{ counts.accessibility }}] }]
    },
    options: { plugins:{legend:{labels:{color:'#e5e7eb'}}},
               animation: {animateRotate:true, animateScale:true},
               color:'#e5e7eb' }
  });

  // ======= Bar: per-page load time =======
  const barTimes = new Chart(document.getElementById('barTimes'), {
    type: 'bar',
    data: {
      labels: {{ page_labels|tojson }},
      datasets: [{ label: 'Seconds', data: {{ page_times|tojson }} }]
    },
    options: { scales: { x: { ticks: { color:'#e5e7eb' }}, y:{ ticks:{ color:'#e5e7eb' } } },
               plugins:{legend:{labels:{color:'#e5e7eb'}}}, color:'#e5e7eb' }
  });

  // ======= Histogram of burst response times =======
  const histData = {
    labels: {{ hist_labels|tojson }},
    datasets: [{ label: 'Requests', data: {{ hist_values|tojson }} }]
  };
  new Chart(document.getElementById('hist'), { type: 'line', data: histData,
    options:{ scales:{ x:{ ticks:{ color:'#e5e7eb'}}, y:{ ticks:{ color:'#e5e7eb'}}},
             plugins:{legend:{labels:{color:'#e5e7eb'}}},
             animation:{duration:900, easing:'easeInOutQuart'}, color:'#e5e7eb'} });

  // ======= Scale curve (1..N servers) =======
  const scaleLabels = Array.from({length: {{ scale_points|length }}}, (_,i)=> i+1);
  new Chart(document.getElementById('scaleLine'), { type: 'line', data: {labels: scaleLabels,
    datasets:[{ label:'Avg seconds', data: {{ scale_points|tojson }} }]},
    options:{ scales:{ x:{ ticks:{ color:'#e5e7eb'}}, y:{ ticks:{ color:'#e5e7eb'}}},
              plugins:{legend:{labels:{color:'#e5e7eb'}}}, color:'#e5e7eb'} });
  {% endif %}
</script>
</body>
</html>
"""


# =============================
# Routes
# =============================
@app.get("/")
def index():
    return render_template_string(INDEX_TMPL)


@app.post("/run")
def run_audit():
    url = request.form.get("url", "").strip()
    try:
        pages = int(request.form.get("pages", 2))
    except Exception:
        pages = 2
    try:
        users = int(request.form.get("users", 150))
    except Exception:
        users = 150

    if not url:
        return redirect(url_for('index'))

    # Crawl & audit
    results = crawl_site(url, max_pages=max(1, min(pages, 100)))

    # Aggregate
    counts = {"security": 0, "seo": 0, "accessibility": 0}
    for r in results:
        counts["security"] += len(r.get("security", []))
        counts["seo"] += len(r.get("seo", []))
        counts["accessibility"] += len(r.get("accessibility", []))

    total_issues = sum(counts.values())
    page_labels = [f"{i+1}" for i, _ in enumerate(results)]
    page_times = [r.get("load_time") or 0 for r in results]

    # Burst test (single URL root for now)
    load_results = run_load_test(url, users=users)
    load_summary = summarize_load_results(load_results)

    # Auto-scale simulation
    scaled = auto_scale(load_summary.get("avg"), 1.5, load_summary)

    # Build histogram arrays for chart
    histo = load_summary.get("histogram", {})
    hist_labels = [str(k) for k in sorted(histo.keys())]
    hist_values = [histo[k] for k in sorted(histo.keys())]

    # Make scale curve up to suggested servers + 4 for viz
    max_servers = max(1, scaled["servers"] + 4)

    base = load_summary.get("avg") or 0
    scale_points = [round(base / max(1, s), 3) for s in range(1, max_servers + 1)]

    # Recommendations
    recommendations = build_recommendations(results, load_summary, scaled)

    return render_template_string(
        INDEX_TMPL,
        url=url,
        pages=pages,
        users=users,
        results=results,
        counts=counts,
        total_issues=total_issues,
        page_labels=page_labels,
        page_times=page_times,
        load_summary=load_summary,
        hist_labels=hist_labels,
        hist_values=hist_values,
        scaled=scaled,
        scale_points=scale_points,
        recommendations=recommendations,
    )


# Map the form action used above
app.add_url_rule('/run', view_func=run_audit, methods=['POST'])


if __name__ == "__main__":
    app.run(debug=True)

