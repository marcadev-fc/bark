#!/usr/bin/env python3
"""
Bark — Voyager Uptime Page Generator
Generates a static HTML index dashboard + per-suite detail pages from Datadog Synthetics.

Usage:
  # Explicit suite IDs:
  python3 generate-uptime-page.py <domain> <output_dir> <suite_id> [suite_id ...]

  # Crawler-based discovery (shows activated + pending journeys):
  python3 generate-uptime-page.py <domain> <output_dir> --crawler <crawler_id> [suite_id ...]

Examples:
  python3 generate-uptime-page.py app.datadoghq.com ~/Desktop/dashboard abc-123-xyz
  python3 generate-uptime-page.py app.datadoghq.com ~/Desktop/dashboard --crawler <crawler_id> abc-123-xyz

Requirements:
  - dd-auth (https://github.com/DataDog/dd-auth) installed and configured
"""
import subprocess, json, sys, os, re, datetime
from urllib.parse import unquote

# ── Auth / fetch ──────────────────────────────────────────────────────────────

def fetch(domain, url):
    """Authenticated GET via dd-auth."""
    r = subprocess.run(
        ['bash', '-c',
         f'eval $(dd-auth --domain {domain} --output) && '
         f'curl -sf -H "DD-API-KEY: $DD_API_KEY" -H "DD-APPLICATION-KEY: $DD_APP_KEY" "{url}"'],
        capture_output=True, text=True
    )
    return json.loads(r.stdout)

def dogweb_base(domain):
    """Return the dogweb (dd.*) base URL for a given domain."""
    if domain.startswith("app."):
        return f"https://dd.{domain[4:]}"
    if domain.startswith("dd."):
        return f"https://{domain}"
    return f"https://dd.{domain}"

# ── Helpers ───────────────────────────────────────────────────────────────────

def uptime_color(pct):
    if pct is None: return "#94a3b8"
    if pct >= 99.9: return "#22c55e"
    if pct >= 99.0: return "#f59e0b"
    return "#ef4444"

def type_icon(t):
    return {"browser": "🌐", "api": "⚡", "network": "🔗"}.get(t, "🔬")

def shorten_name(name, test_type):
    if test_type == "network":
        return name.replace("Network Path: ", "")
    if test_type == "browser":
        return name
    m = re.match(r'^(?:GET|POST|PUT|DELETE|PATCH)\s+(\S+)\s+\((.+?)\)$', name)
    if m:
        raw_path, _ = m.groups()
        segments = [s for s in raw_path.split("?")[0].split("/") if s]
        if "countryLang" in raw_path:
            qs = raw_path.split("?")[1] if "?" in raw_path else ""
            pp = re.search(r'pagePath=([^&]+)', qs)
            pg = unquote(pp.group(1)).rstrip("/").split("/")[-1] if pp else ""
            return f"Country/Lang — {pg}" if pg else "Country/Lang API"
        if "image" in raw_path.lower() or "/is/image/" in raw_path:
            img = segments[-1] if segments else "image"
            return f"Image — {img[:30]}"
        if segments:
            last = re.sub(r'\.(html?|json|xml|js|css)$', '', segments[-1])
            return last.replace("-", " ").replace("_", " ").title()[:40]
        return raw_path[:40]
    return name[:50]

def generate_context(name, test_type, short_name=""):
    if test_type == "browser":
        label = short_name or "critical user flows"
        return f"Runs a real browser through {label} — catches broken UI before users do"
    if test_type == "network":
        host = name.replace("Network Path: ", "").split(":")[0]
        return f"Checks network reachability and round-trip latency to {host}"
    m = re.match(r'^(?:GET|POST|PUT|DELETE|PATCH)\s+(\S+)\s+\((.+?)\)$', name)
    if m:
        raw_path, _ = m.groups()
        if "countryLang" in raw_path:
            return "Locale config — confirms regional visitors get the correct language and content"
        if "image" in raw_path.lower() or "/is/image/" in raw_path:
            label = short_name or "product image"
            return f"Image CDN — confirms {label} loads correctly; broken images hurt engagement"
        segs = [s for s in raw_path.split("?")[0].split("/") if s]
        if segs:
            last = re.sub(r'\.(html?|json|xml|js|css)$', '', segs[-1]).replace("-"," ").replace("_"," ")
            return f"Verifies the {last} endpoint returns correct data — downstream features depend on this"
    return "Monitors API availability and response integrity"

def extract_endpoint(name, test_type):
    """Extract the raw endpoint/target from a test name for display."""
    if test_type == "network":
        return name.replace("Network Path: ", "").strip()
    if test_type == "browser":
        return name
    m = re.match(r'^((?:GET|POST|PUT|DELETE|PATCH)\s+\S+)\s+\(', name)
    if m:
        endpoint = m.group(1)
        return endpoint.split("?")[0]
    return name

def card_title(name, test_type, short_name=""):
    """Concise, human-readable summary of what the test validates."""
    if test_type == "browser":
        return "The full user journey runs smoothly from start to finish"
    if test_type == "network":
        return "The site stays fast and reachable for every visitor"
    m = re.match(r'^(?:GET|POST|PUT|DELETE|PATCH)\s+(\S+)\s+\((.+?)\)$', name)
    if m:
        raw_path, _ = m.groups()
        if "countryLang" in raw_path:
            return "Every region gets the right language and content"
        if "image" in raw_path.lower() or "/is/image/" in raw_path:
            return "Product images load fast and without errors"
        segs = [s for s in raw_path.split("?")[0].split("/") if s]
        if segs:
            last = re.sub(r'\.(html?|json|xml|js|css)$', '', segs[-1]).replace("-"," ").replace("_"," ").lower()
            return f"{last.capitalize()} data loads correctly for every request"
    return "The API responds with the right data every time"


# ── SVG / HTML components ─────────────────────────────────────────────────────

def ring_svg(pct, color, size=96):
    """Circular progress ring — pure SVG, no JS needed."""
    r = size // 2 - 10
    cx = cy = size // 2
    circ = 2 * 3.14159265 * r
    offset = circ * (1 - (pct or 0) / 100)
    label = f"{pct:.1f}%" if pct is not None else "—"
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" style="display:block;margin:auto">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#1e3a5f" stroke-width="8"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="8"'
        f' stroke-dasharray="{circ:.2f}" stroke-dashoffset="{offset:.2f}"'
        f' stroke-linecap="round" transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy+6}" text-anchor="middle" fill="{color}"'
        f' font-size="16" font-weight="800" font-family="-apple-system,BlinkMacSystemFont,sans-serif">{label}</text>'
        f'</svg>'
    )

def mini_pulse_segs(flags, count=28):
    """Just the <i> segment elements for a compact pulse bar."""
    display = list(reversed(flags))[:count]
    display.reverse()
    return "".join(
        f'<i class="mp {"p" if f is True else ("f" if f is False else "n")}"></i>'
        for f in display
    )

def mini_pulse_html(flags, count=28):
    """Compact pulse bar for cards."""
    return f'<div class="mpb">{mini_pulse_segs(flags, count)}</div>'

def state_badge_html(passed):
    if passed is True:  return '<span class="badge pass">Passing</span>'
    if passed is False: return '<span class="badge fail">Failing</span>'
    return '<span class="badge unknown">—</span>'


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_suite_data(domain, base_url, suite_id, ts_24h_ms):
    suite_data = fetch(domain, f"{base_url}/api/v2/synthetics/suites/{suite_id}")
    suite      = suite_data["data"]["attributes"]
    suite_name = suite["name"]
    tests_raw  = suite.get("tests", [])

    tests = []
    for t in tests_raw:
        pid = t["public_id"]
        print(f"    {pid}...")
        try:
            detail       = fetch(domain, f"{base_url}/api/v1/synthetics/tests/{pid}")
            results_data = fetch(domain, f"{base_url}/api/v1/synthetics/tests/{pid}/results?count=200&from_ts={ts_24h_ms}")
            results      = results_data.get("results", [])
            flags        = [r.get("result", {}).get("passed", None) for r in results]
            passed       = sum(1 for f in flags if f is True)
            uptime       = round((passed / len(flags)) * 100, 2) if flags else None
            last_passed  = flags[0] if flags else None
            last_ts      = results[0].get("check_time", 0) // 1000 if results else None
            failures     = [r for r in results if r.get("result", {}).get("passed") is False]
            last_fail_ts = max((f.get("check_time", 0) // 1000 for f in failures), default=0)
            raw_name     = detail.get("name", pid)
            ttype        = detail.get("type", "api")
            test_url     = detail.get("config", {}).get("request", {}).get("url", "")
            short        = shorten_name(raw_name, ttype)
            tests.append({
                "public_id":    pid,
                "raw_name":     raw_name,
                "short_name":   short,
                "card_title":   card_title(raw_name, ttype, short),
                "endpoint":     extract_endpoint(raw_name, ttype),
                "context":      generate_context(raw_name, ttype, short),
                "type":         ttype,
                "uptime":       uptime,
                "results":      flags,
                "last_passed":  last_passed,
                "last_ts":      last_ts,
                "last_fail_ts": last_fail_ts,
                "test_url":     test_url,
            })
        except Exception as e:
            print(f"      failed: {e}")
            tests.append({"public_id": pid, "raw_name": pid, "short_name": pid,
                          "context": "", "type": "api", "uptime": None,
                          "results": [], "last_passed": None, "last_ts": None, "last_fail_ts": 0})

    last_ts_overall   = max((t["last_ts"] for t in tests if t["last_ts"]), default=None)
    last_fail_overall = max((t.get("last_fail_ts", 0) for t in tests), default=0)
    all_flags         = [f for t in tests for f in t["results"]]
    all_valid         = [f for f in all_flags if f is not None]
    uptime_24h        = round(sum(1 for f in all_valid if f) / len(all_valid) * 100, 1) if all_valid else None
    any_failed        = any(t["last_passed"] is False for t in tests)
    has_data          = any(t["last_passed"] is not None for t in tests)
    suite_passing     = False if any_failed else (True if has_data else None)

    from urllib.parse import urlparse as _up
    app_domain = next(
        (_up(t["test_url"]).hostname for t in tests if t.get("test_url")),
        None
    )

    return {
        "suite_id":      suite_id,
        "suite_name":    suite_name,
        "app_domain":    app_domain,
        "uptime_24h":    uptime_24h,
        "suite_passing": suite_passing,
        "tests":         tests,
        "last_ts":       last_ts_overall,
        "last_fail_ts":  last_fail_overall,
        "all_flags":     all_flags,
    }


def fetch_crawler_journeys(domain, crawler_id):
    """Return (journeys, start_url) from the crawler's latest job."""
    url = f"{dogweb_base(domain)}/api/v2/synthetics/crawlers/jobs/latest"
    data = fetch(domain, url)
    included_by_id = {item["id"]: item for item in data.get("included", [])}

    journeys = []
    start_url = ""
    for item in data.get("data", []):
        if item["id"] != crawler_id:
            continue
        start_url = item.get("attributes", {}).get("start_url", "")
        rel = item.get("relationships", {}).get("latest_job", {}).get("data")
        if not rel:
            break
        job = included_by_id.get(rel["id"])
        if not job:
            break
        for ref in job.get("relationships", {}).get("user_journeys", {}).get("data", []):
            jid = ref["id"]
            journey = included_by_id.get(jid)
            if journey:
                attrs = journey["attributes"]
                journeys.append({
                    "id":          jid,
                    "title":       attrs.get("title", "Untitled"),
                    "description": attrs.get("description", ""),
                    "intents":     attrs.get("intents", []),
                })
            else:
                journeys.append({"id": jid, "title": "Unknown", "description": "", "intents": []})
        break

    return journeys, start_url


# ── CSS shared between pages ──────────────────────────────────────────────────

SHARED_CSS = """
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#090c1a;color:#e2e8f0;min-height:100vh}
    .header{background:#0d0e1f;border-bottom:1px solid #1e1040;padding:16px 36px;display:flex;align-items:center;justify-content:space-between;gap:16px}
    .header-left{display:flex;align-items:center;gap:12px}
    .back-link{color:#64748b;text-decoration:none;font-size:12px;opacity:.7;white-space:nowrap}
    .back-link:hover{opacity:1;color:#a78bfa}
    .page-title{font-size:20px;font-weight:700;color:#f1f5f9}
    .page-sub{font-size:11px;color:#64748b;margin-top:3px;font-family:monospace}
    .dd-link{color:#8b5cf6;text-decoration:none;font-size:12px;opacity:.8;white-space:nowrap}
    .dd-link:hover{opacity:1;text-decoration:underline}
    .section{margin:20px 36px}
    .section-title{font-size:10px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px}
    .badge{font-size:10px;font-weight:700;padding:2px 8px;border-radius:999px}
    .badge.pass{background:#14532d;color:#86efac}
    .badge.fail{background:#450a0a;color:#fca5a5}
    .badge.unknown{color:#475569}
    .footer{text-align:center;padding:18px;color:#2d1b69;font-size:10px;background:#090c1a}
"""


# ── Index page renderer ───────────────────────────────────────────────────────

def render_index_html(all_suites, base_url, domain, generated_at,
                      pending_journeys=None, app_name=None):
    pending_journeys = pending_journeys or []
    app_name   = app_name or domain
    n_passing  = sum(1 for s in all_suites if s["suite_passing"] is True)
    n_failing  = sum(1 for s in all_suites if s["suite_passing"] is False)
    n_total    = len(all_suites) + len(pending_journeys)

    # ── Operational status line ──
    n_act = len(all_suites)
    if n_act == 0:
        op_html = f'<span class="op-msg nodata">{app_name} — no journeys activated yet</span>'
    elif n_failing == 0:
        op_html = (f'<span class="op-icon ok">✓</span>'
                   f' <strong>{app_name}</strong> is operational'
                   f' — all {n_act} journey{"s" if n_act != 1 else ""} passing')
    else:
        op_html = (f'<span class="op-icon fail">⚠</span>'
                   f' <strong>{app_name}</strong>'
                   f' — {n_passing} of {n_act} journey{"s" if n_act != 1 else ""} passing,'
                   f' {n_failing} failing')

    # ── Activated suite cards ──
    cards_html = ""
    for s in all_suites:
        color      = uptime_color(s["uptime_24h"])
        passing    = s["suite_passing"]
        card_cls   = "passing" if passing is True else ("failing" if passing is False else "nodata")
        state_label = "✓ Passing" if passing is True else ("✗ Failing" if passing is False else "— No data")
        n_tests    = len(s["tests"])
        pulse      = mini_pulse_html(s["all_flags"])
        name_short = s["suite_name"][:48] + ("…" if len(s["suite_name"]) > 48 else "")
        last_fail  = s.get("last_fail_ts", 0) or 0
        last_fail_label = (datetime.datetime.fromtimestamp(last_fail).strftime("Last failure %d %b %H:%M")
                           if last_fail else "No failures in window")

        pct_label = f"{s['uptime_24h']:.1f}%" if s["uptime_24h"] is not None else "—"
        segs      = mini_pulse_segs(s["all_flags"])
        cards_html += f"""
    <a href="{s['suite_id']}.html" class="card {card_cls}"
       data-name="{s['suite_name'].lower()}" data-lastfail="{last_fail}">
      <div class="card-top">
        <div class="card-name" title="{s['suite_name']}">{name_short}</div>
        <span class="card-state {card_cls}">{state_label}</span>
      </div>
      <div class="card-uptime">
        <span class="card-pct" style="color:{color}">{pct_label}</span>
        <div class="mpb">{segs}</div>
      </div>
      <div class="card-window">Last 24 hours</div>
      <div class="card-foot">
        <span class="card-count">{n_tests} test{"s" if n_tests != 1 else ""}</span>
        <span class="card-last">{last_fail_label}</span>
      </div>
    </a>"""

    # ── Pending journey cards ──
    for j in pending_journeys:
        title_short = j["title"][:52] + ("…" if len(j["title"]) > 52 else "")
        desc        = j.get("description", "")[:130] + ("…" if len(j.get("description","")) > 130 else "")
        intent_tags = "".join(
            f'<span class="intent-tag">{i["verb"]} {i["object"]}</span>'
            for i in j.get("intents", [])[:3]
        )
        cards_html += f"""
    <div class="card pending" data-name="{j['title'].lower()}" data-lastfail="0">
      <div class="card-top">
        <div class="card-name" title="{j['title']}">{title_short}</div>
        <span class="card-state pending">⏳ Pending</span>
      </div>
      <div class="pending-body">
        <div class="pending-desc">{desc}</div>
        <div class="pending-intents">{intent_tags}</div>
      </div>
      <div class="pending-cta">
        <code class="jid">{j["id"][:8]}…</code>
        <span>Run <code>/activate-voyager-suite</code> to enable</span>
      </div>
    </div>"""

    # ── Hero pills ──
    pills = []
    if n_passing:  pills.append(f'<span class="pill passing">✓ {n_passing} passing</span>')
    if n_failing:  pills.append(f'<span class="pill failing">✗ {n_failing} failing</span>')
    if pending_journeys: pills.append(f'<span class="pill pending">⏳ {len(pending_journeys)} pending</span>')
    pills_html = "".join(pills)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Bark — {app_name}</title>
  <style>
    {SHARED_CSS}
    /* ── Hero ── */
    .hero{{
      padding: 52px 64px 32px;
      background: linear-gradient(145deg, #1a0d2e 0%, #0f1535 45%, #0a1628 100%);
      border-bottom: 1px solid #2d1b69;
      position: relative;
      overflow: hidden;
    }}
    .hero::before{{
      content: "";
      position: absolute;
      inset: 0;
      background: radial-gradient(ellipse 55% 70% at 85% 40%, #632ca622, transparent),
                  radial-gradient(ellipse 30% 40% at 15% 80%, #3b82f610, transparent);
      pointer-events: none;
    }}
    .hero-nav{{position:absolute;top:32px;right:64px;z-index:1}}
    .bark-logo{{
      font-size: 13px;
      font-weight: 800;
      letter-spacing: .18em;
      text-transform: uppercase;
      color: #7c3aed;
      margin-bottom: 28px;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .bark-logo::before{{
      content: "🐶";
      font-size: 16px;
      letter-spacing: 0;
    }}
    .bark-logo-sep{{color:#334155;font-weight:300;letter-spacing:0}}
    .bark-logo-sub{{color:#475569;font-weight:500;letter-spacing:.04em;text-transform:none;font-size:12px}}
    .hero-h1{{
      font-size: clamp(26px, 3.8vw, 46px);
      font-weight: 800;
      line-height: 1.15;
      color: #f1f5f9;
      letter-spacing: -.02em;
    }}
    .hero-h1 .accent{{ color: #a78bfa; }}
    .hero-sub{{
      font-size: clamp(13px, 1.4vw, 15px);
      color: #64748b;
      line-height: 1.6;
      margin-top: 14px;
      margin-bottom: 0;
    }}
    .hero-meta{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
    .pill{{font-size:11px;font-weight:600;padding:4px 12px;border-radius:999px}}
    .pill.passing{{background:#14532d;color:#86efac}}
    .pill.failing{{background:#450a0a;color:#fca5a5}}
    .pill.pending{{background:#1e3a5f;color:#93c5fd}}
    .hero-domain{{font-size:11px;color:#334155;font-family:monospace;margin-left:4px}}
    /* ── Operational banner ── */
    .op-bar{{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 56px;
      border-bottom: 1px solid #1e1040;
      font-size: 14px;
      color: #94a3b8;
      background: #0d0e1f;
    }}
    .op-bar strong{{color:#e2e8f0}}
    .op-icon{{font-style:normal;margin-right:4px}}
    .op-icon.ok{{color:#22c55e}}
    .op-icon.fail{{color:#ef4444}}
    .op-msg.nodata{{color:#475569}}
    .controls-row{{display:flex;align-items:center;gap:20px;flex-shrink:0}}
    .sort-row{{display:flex;align-items:center;gap:10px}}
    .sort-label{{font-size:11px;color:#475569;font-weight:600;text-transform:uppercase;letter-spacing:.07em}}
    .sort-btn{{
      background: #1e293b;
      border: 1px solid #334155;
      color: #94a3b8;
      font-size: 12px;
      font-weight: 600;
      padding: 5px 14px;
      border-radius: 6px;
      cursor: pointer;
      transition: background .12s, color .12s, border-color .12s;
    }}
    .sort-btn:hover{{background:#334155;color:#e2e8f0}}
    .sort-btn.active{{background:#7c3aed22;border-color:#7c3aed88;color:#a78bfa}}
    /* ── Card grid ── */
    .cards{{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
      padding: 24px 56px 52px;
      background: linear-gradient(180deg, #0d0e1f 0%, #090c1a 100%);
    }}
    @media(max-width:1100px){{.cards{{grid-template-columns:repeat(3,minmax(0,1fr))}}}}
    @media(max-width:780px){{.cards{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
    @media(max-width:520px){{.cards{{grid-template-columns:1fr;padding:16px 20px 36px}}}}
    .card{{
      background: #12102a;
      border-radius: 12px;
      padding: 18px 16px 14px;
      text-decoration: none;
      display: flex;
      flex-direction: column;
      gap: 10px;
      border: 1px solid #2d1b6944;
      transition: transform .15s, box-shadow .15s, border-color .15s;
    }}
    .card:not(.pending):hover{{
      transform: translateY(-3px);
      box-shadow: 0 12px 36px #00000070, 0 0 0 1px #632ca630;
      border-color: #632ca650;
    }}
    .card.passing{{border-top: 2px solid #22c55e60}}
    .card.failing{{border-top: 2px solid #ef444460}}
    .card.nodata{{border-top: 2px solid #2d1b6940}}
    .card.pending{{border-top: 2px solid #3b82f625; opacity:.65; cursor:default}}
    .card-top{{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;min-height:42px}}
    .card-name{{font-size:13px;font-weight:600;color:#e2e8f0;line-height:1.35;
      display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;flex:1;min-width:0}}
    .card-state{{font-size:10px;font-weight:700;padding:2px 8px;border-radius:999px;white-space:nowrap;flex-shrink:0;margin-top:1px}}
    .card-state.passing{{background:#14532d;color:#86efac}}
    .card-state.failing{{background:#450a0a;color:#fca5a5}}
    .card-state.nodata{{background:#1a1040;color:#475569}}
    .card-state.pending{{background:#1a1040;color:#818cf8}}
    .card-uptime{{display:flex;align-items:center;gap:8px;padding:4px 0 2px;width:100%}}
    .card-pct{{font-size:18px;font-weight:800;font-variant-numeric:tabular-nums;flex-shrink:0;line-height:1;white-space:nowrap;letter-spacing:-0.02em}}
    .card-window{{text-align:center;font-size:10px;color:#2d1b69;font-weight:600;text-transform:uppercase;letter-spacing:.07em;margin-top:2px}}
    .mpb{{display:flex;gap:2px;align-items:flex-end;flex:1;min-width:0;overflow:hidden;height:30px}}
    i.mp{{display:inline-block;width:4px;flex-shrink:1;border-radius:2px;font-style:normal}}
    i.mp.p{{background:#22c55e;height:100%}}
    i.mp.f{{background:#ef4444;height:100%}}
    i.mp.n{{background:#1e1040;height:50%}}
    .card-foot{{display:flex;justify-content:space-between;align-items:center;padding-top:6px;border-top:1px solid #1e1040}}
    .card-count{{font-size:11px;color:#64748b}}
    .card-last{{font-size:10px;color:#475569}}
    .pending-body{{display:flex;flex-direction:column;gap:10px;flex:1}}
    .pending-desc{{font-size:11px;color:#64748b;line-height:1.5}}
    .pending-intents{{display:flex;flex-wrap:wrap;gap:5px}}
    .intent-tag{{font-size:10px;background:#0f172a;color:#7c9aba;padding:2px 8px;border-radius:4px;border:1px solid #1e3a5f}}
    .pending-cta{{font-size:10px;color:#334155;display:flex;flex-direction:column;gap:3px;padding-top:6px;border-top:1px solid #1e3a5f}}
    code.jid{{font-family:monospace;color:#64748b;font-size:10px}}
    .footer{{text-align:center;padding:20px;color:#2d1b69;font-size:10px;background:#090c1a}}
  </style>
</head>
<body>

<div class="hero">
  <div class="hero-nav">
    <span></span>
    <a class="dd-link" href="{base_url}/synthetics/bits-testing-agents" target="_blank">View in Datadog ↗</a>
  </div>
  <div class="bark-logo">
    Bark
    <span class="bark-logo-sep">·</span>
    <span class="bark-logo-sub">powered by Datadog Synthetics</span>
  </div>
  <h1 class="hero-h1">
    Don't wait for your customers<br>
    to <span class="accent">start barking at you</span>.
  </h1>
  <p class="hero-sub">
    Check uptimes backed by real Datadog Synthetics tests.
  </p>
</div>

<div class="op-bar">
  <span class="op-msg-wrap">{op_html}</span>
  <div class="sort-row">
    <span class="sort-label">Sort by</span>
    <button class="sort-btn active" data-sort="name" onclick="sortCards('name')">Name A–Z</button>
    <button class="sort-btn" data-sort="lastfail" onclick="sortCards('lastfail')">Last degradation</button>
  </div>
</div>

<div class="cards" id="cards-grid">{cards_html}
</div>

<div class="footer">Bark · {generated_at}</div>

<script>
function sortCards(by) {{
  const grid = document.getElementById('cards-grid');
  const cards = Array.from(grid.children);
  cards.sort((a, b) => {{
    if (by === 'name') {{
      return (a.dataset.name || '').localeCompare(b.dataset.name || '');
    }} else {{
      const af = Number(a.dataset.lastfail) || 0;
      const bf = Number(b.dataset.lastfail) || 0;
      if (bf !== af) return bf - af;
      return (a.dataset.name || '').localeCompare(b.dataset.name || '');
    }}
  }});
  cards.forEach(c => grid.appendChild(c));
  document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`[data-sort="${{by}}"]`).classList.add('active');
}}
sortCards('name');
</script>
</body>
</html>"""


# ── Detail page renderer ──────────────────────────────────────────────────────

def render_detail_html(data, base_url, generated_at, multi_suite):
    suite_id      = data["suite_id"]
    suite_name    = data["suite_name"]
    tests         = data["tests"]
    uptime_24h    = data["uptime_24h"]
    suite_passing = data["suite_passing"]
    up_color      = uptime_color(uptime_24h)
    up_pct        = (f"{uptime_24h:.1f}".rstrip('0').rstrip('.') + '%') if uptime_24h is not None else "—"
    up_cls        = "passing" if suite_passing is True else ("failing" if suite_passing is False else "nodata")
    up_label      = "✓ Passing" if suite_passing is True else ("✗ Failing" if suite_passing is False else "— No data")

    # Op-bar status
    n_total   = len(tests)
    n_passing = sum(1 for t in tests if t["last_passed"] is True)
    n_failing = sum(1 for t in tests if t["last_passed"] is False)
    t_word    = f'test{"s" if n_total != 1 else ""}'
    if n_total == 0:
        op_html = f'<span class="op-msg nodata">{suite_name} — no test data available</span>'
    elif n_failing == 0:
        op_html = (f'<span class="op-icon ok">✓</span>'
                   f' <strong>{suite_name}</strong> is operational'
                   f' — all {n_total} {t_word} passing')
    else:
        op_html = (f'<span class="op-icon fail">⚠</span>'
                   f' <strong>{suite_name}</strong>'
                   f' — {n_passing} of {n_total} {t_word} passing, {n_failing} failing')

    # Test cards
    test_cards = ""
    for t in tests:
        color      = uptime_color(t["uptime"])
        pct        = (f"{t['uptime']:.1f}".rstrip('0').rstrip('.') + '%') if t["uptime"] is not None else "—"
        ts_str     = (datetime.datetime.fromtimestamp(t["last_ts"]).strftime("%H:%M %d %b")
                      if t["last_ts"] else "—")
        dd_url     = f"{base_url}/synthetics/details/{t['public_id']}"
        pulse      = mini_pulse_html(t["results"])
        card_cls   = "passing" if t["last_passed"] is True else ("failing" if t["last_passed"] is False else "nodata")
        type_label = "network path" if t['type'] == "network" else t['type']
        last_fail  = t.get("last_fail_ts", 0) or 0
        test_cards += f"""
    <a class="tcard {card_cls}" href="{dd_url}" target="_blank"
       data-name="{t['short_name'].lower()}" data-lastfail="{last_fail}" data-type="{t['type']}">
      <div class="tcard-top">
        <div class="tcard-name-wrap">
          <div class="tcard-name tcard-endpoint">{t['endpoint']}</div>
        </div>
        {state_badge_html(t['last_passed'])}
      </div>
      <div class="tcard-uptime">
        <span class="tcard-pct" style="color:{color}">{pct}</span>
        {pulse}
      </div>
      <div class="tcard-foot">
        <span class="tcard-type">{type_label}</span>
        <span class="tcard-ts">{ts_str}</span>
      </div>
    </a>"""

    back_link = '<a class="back-link" href="index.html">← All journeys</a>'

    # Filter buttons — only show types that actually exist in this suite
    type_label_map = {"browser": "Browser", "api": "API", "network": "Network path"}
    present_types  = sorted({t["type"] for t in tests}, key=lambda x: list(type_label_map).index(x) if x in type_label_map else 99)
    filter_btns = '<button class="sort-btn active" data-filter="all" onclick="filterCards(\'all\')">All</button>'
    for tp in present_types:
        label = type_label_map.get(tp, tp.title())
        filter_btns += f'<button class="sort-btn" data-filter="{tp}" onclick="filterCards(\'{tp}\')">{label}</button>'

    # Build a time-aligned aggregate: for each slot, any fail=fail, all pass=pass, else nd
    max_len = max((len(t["results"]) for t in tests), default=0)
    agg_flags = []
    for i in range(max_len):
        slot = [t["results"][i] for t in tests if i < len(t["results"])]
        valid = [r for r in slot if r is not None]
        if not valid:
            agg_flags.append(None)
        elif any(r is False for r in valid):
            agg_flags.append(False)
        else:
            agg_flags.append(True)
    overall_pulse = mini_pulse_html(agg_flags, count=len(agg_flags))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{suite_name} — Bark</title>
  <style>
    {SHARED_CSS}
    /* ── Detail hero ── */
    .detail-hero{{
      padding: 32px 56px 44px;
      background: linear-gradient(145deg, #1a0d2e 0%, #0f1535 45%, #0a1628 100%);
      border-bottom: 1px solid #2d1b69;
      position: relative;
      overflow: hidden;
    }}
    .detail-hero::before{{
      content:""; position:absolute; inset:0; pointer-events:none;
      background: radial-gradient(ellipse 55% 70% at 85% 40%, #632ca622, transparent),
                  radial-gradient(ellipse 30% 40% at 15% 80%, #3b82f610, transparent);
    }}
    .dh-nav{{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}}
    .bark-logo{{font-size:13px;font-weight:800;letter-spacing:.18em;text-transform:uppercase;
                color:#7c3aed;margin-bottom:28px;display:flex;align-items:center;gap:10px}}
    .bark-logo::before{{content:"🐶";font-size:16px;letter-spacing:0}}
    .bark-logo-sep{{color:#334155;font-weight:300;letter-spacing:0}}
    .bark-logo-sub{{color:#475569;font-weight:500;letter-spacing:.04em;text-transform:none;font-size:12px}}
    .dh-uptime{{display:flex;align-items:center;gap:24px;margin-top:4px}}
    .dh-pct{{font-size:clamp(36px,5vw,64px);font-weight:800;font-variant-numeric:tabular-nums;line-height:1;flex-shrink:0;letter-spacing:-0.02em}}
    .dh-bar-col{{flex:1;min-width:0;display:flex;flex-direction:column;gap:6px}}
    .dh-bar-col .mpb{{height:40px;flex:none;width:100%}}
    .dh-bar-col .mpb i.mp{{flex-grow:1;max-width:10px}}
    .dh-bar-sub{{display:flex;justify-content:space-between;align-items:center}}
    .dh-bar-label{{font-size:11px;color:#64748b}}
    .dh-ts-label{{font-size:10px;color:#475569;font-weight:600;text-transform:uppercase;letter-spacing:.07em}}
    .uh-badge{{padding:5px 14px;border-radius:999px;font-size:12px;font-weight:600}}
    .uh-badge.passing{{background:#14532d;color:#86efac}}
    .uh-badge.failing{{background:#450a0a;color:#fca5a5}}
    .uh-badge.nodata{{background:#1a1040;color:#475569}}
    /* ── Op-bar + sort ── */
    .op-bar{{display:flex;align-items:center;justify-content:space-between;
             padding:12px 56px;border-bottom:1px solid #1e1040;
             font-size:14px;color:#94a3b8;background:#0d0e1f}}
    .op-bar strong{{color:#e2e8f0}}
    .op-icon{{font-style:normal;margin-right:4px}}
    .op-icon.ok{{color:#22c55e}}
    .op-icon.fail{{color:#ef4444}}
    .op-msg.nodata{{color:#475569}}
    .controls-row{{display:flex;align-items:center;gap:20px;flex-shrink:0}}
    .sort-row{{display:flex;align-items:center;gap:10px}}
    .sort-label{{font-size:11px;color:#475569;font-weight:600;text-transform:uppercase;letter-spacing:.07em}}
    .sort-btn{{background:#1e293b;border:1px solid #334155;color:#94a3b8;font-size:12px;font-weight:600;
               padding:5px 14px;border-radius:6px;cursor:pointer;transition:background .12s,color .12s,border-color .12s}}
    .sort-btn:hover{{background:#334155;color:#e2e8f0}}
    .sort-btn.active{{background:#7c3aed22;border-color:#7c3aed88;color:#a78bfa}}
    /* ── Content ── */
    .content{{padding:24px 56px 52px;background:linear-gradient(180deg,#0d0e1f 0%,#090c1a 100%)}}
    .section-title{{font-size:10px;font-weight:700;color:#2d1b69;text-transform:uppercase;
                    letter-spacing:.1em;margin-bottom:14px}}
    /* ── Pulse bars ── */
    .mpb{{display:flex;gap:2px;align-items:flex-end;flex:1;min-width:0;overflow:hidden;height:30px}}
    i.mp{{display:inline-block;width:4px;flex-shrink:1;border-radius:2px;font-style:normal}}
    i.mp.p{{background:#22c55e;height:100%}}
    i.mp.f{{background:#ef4444;height:100%}}
    i.mp.n{{background:#1e1040;height:50%}}
    /* ── Test cards grid ── */
    .test-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}}
    @media(max-width:1100px){{.test-grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}}}
    @media(max-width:780px){{.test-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
    @media(max-width:520px){{.test-grid{{grid-template-columns:1fr}}}}
    .tcard{{background:#12102a;border-radius:12px;padding:18px 16px 14px;
            display:flex;flex-direction:column;gap:10px;text-decoration:none;color:inherit;
            border:1px solid #2d1b6944;transition:transform .15s,box-shadow .15s,border-color .15s}}
    .tcard.passing{{border-top:2px solid #22c55e60}}
    .tcard.failing{{border-top:2px solid #ef444460}}
    .tcard.nodata{{border-top:2px solid #2d1b6940}}
    .tcard:hover{{transform:translateY(-3px);box-shadow:0 12px 36px #00000070,0 0 0 1px #632ca630;border-color:#632ca655}}
    .tcard-top{{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;min-height:42px}}
    .tcard-name-wrap{{flex:1;min-width:0}}
    .tcard-name{{font-size:13px;font-weight:600;color:#e2e8f0;line-height:1.4;
                display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
    .tcard-endpoint{{font-family:monospace;font-size:11px;font-weight:500;color:#a5b4fc;word-break:break-all}}
    .tcard-uptime{{display:flex;align-items:center;gap:8px;padding:2px 0}}
    .tcard-pct{{font-size:18px;font-weight:800;font-variant-numeric:tabular-nums;flex-shrink:0;line-height:1;white-space:nowrap;letter-spacing:-0.02em}}
    .tcard-foot{{display:flex;align-items:center;justify-content:space-between;margin-top:2px}}
    .tcard-type{{background:#1a1040;color:#818cf8;font-size:10px;padding:2px 7px;border-radius:4px;font-family:monospace}}
    .tcard-ts{{color:#3d2a69;font-size:10px}}
  </style>
</head>
<body>
<div class="detail-hero">
  <div class="dh-nav">
    {back_link}
    <a class="dd-link" href="{base_url}/synthetics/test-suite/details/{suite_id}" target="_blank">View in Datadog ↗</a>
  </div>
  <div class="bark-logo">
    Bark
    <span class="bark-logo-sep">·</span>
    <span class="bark-logo-sub">powered by Datadog Synthetics</span>
  </div>
  <div class="dh-uptime">
    <div class="dh-pct" style="color:{up_color}">{up_pct}</div>
    <div class="dh-bar-col">
      {overall_pulse}
      <div class="dh-bar-sub">
        <span class="dh-bar-label">Last 24 hours · {len(tests)} test{"s" if len(tests) != 1 else ""}</span>
        <span class="dh-ts-label">Oldest → Newest</span>
      </div>
    </div>
    <span class="uh-badge {up_cls}">{up_label}</span>
  </div>
</div>

<div class="op-bar">
  <span class="op-msg-wrap">{op_html}</span>
  <div class="controls-row">
    <div class="sort-row">
      <span class="sort-label">Type</span>
      {filter_btns}
    </div>
    <div class="sort-row">
      <span class="sort-label">Sort</span>
      <button class="sort-btn active" data-sort="name" onclick="sortCards('name')">Name A–Z</button>
      <button class="sort-btn" data-sort="lastfail" onclick="sortCards('lastfail')">Last degradation</button>
    </div>
  </div>
</div>

<div class="content">
  <div class="test-grid" id="cards-grid">{test_cards}
  </div>
</div>

<div class="footer">Bark · {generated_at}</div>

<script>
let activeFilter = 'all';

function filterCards(type) {{
  activeFilter = type;
  document.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('active'));
  document.querySelector(`[data-filter="${{type}}"]`).classList.add('active');
  applyFilterSort();
}}

function sortCards(by) {{
  document.querySelectorAll('[data-sort]').forEach(b => b.classList.remove('active'));
  document.querySelector(`[data-sort="${{by}}"]`).classList.add('active');
  applyFilterSort();
}}

function applyFilterSort() {{
  const by   = document.querySelector('[data-sort].active')?.dataset.sort || 'name';
  const grid = document.getElementById('cards-grid');
  const cards = Array.from(grid.children);
  cards.forEach(c => c.style.display = (activeFilter === 'all' || c.dataset.type === activeFilter) ? '' : 'none');
  cards.sort((a, b) => {{
    if (by === 'name') return (a.dataset.name || '').localeCompare(b.dataset.name || '');
    const af = Number(a.dataset.lastfail) || 0;
    const bf = Number(b.dataset.lastfail) || 0;
    return bf !== af ? bf - af : (a.dataset.name || '').localeCompare(b.dataset.name || '');
  }});
  cards.forEach(c => grid.appendChild(c));
}}
applyFilterSort();
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage: generate-uptime-page.py <domain> <output_dir> [--crawler <id>] <suite_id> ...")
        sys.exit(1)

    domain     = sys.argv[1]
    output_dir = sys.argv[2]
    rest       = sys.argv[3:]
    base_url   = f"https://{domain}"
    os.makedirs(output_dir, exist_ok=True)

    # Parse --crawler flag
    crawler_id = None
    suite_ids  = []
    i = 0
    while i < len(rest):
        if rest[i] == "--crawler" and i + 1 < len(rest):
            crawler_id = rest[i + 1]
            i += 2
        else:
            suite_ids.append(rest[i])
            i += 1

    if not suite_ids and not crawler_id:
        print("Usage: generate-uptime-page.py <domain> <output_dir> [--crawler <id>] <suite_id> ...")
        sys.exit(1)

    ts_24h_ms    = int((datetime.datetime.now() - datetime.timedelta(hours=24)).timestamp() * 1000)
    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Fetch crawler journeys if requested
    crawler_journeys = []
    app_name = None
    if crawler_id:
        print(f"\nFetching journeys for crawler {crawler_id}...")
        crawler_journeys, crawler_start_url = fetch_crawler_journeys(domain, crawler_id)
        if crawler_start_url:
            try:
                from urllib.parse import urlparse as _up
                app_name = _up(crawler_start_url).hostname or None
            except Exception:
                pass
        print(f"  Found {len(crawler_journeys)} journeys{' for ' + app_name if app_name else ''}:")
        for j in crawler_journeys:
            print(f"    • {j['title']} ({j['id'][:8]}…)")

    # Fetch suite data for all given suite IDs
    all_data = []
    for suite_id in suite_ids:
        print(f"\nSuite {suite_id}...")
        data = fetch_suite_data(domain, base_url, suite_id, ts_24h_ms)
        all_data.append(data)

    # If app_name wasn't set by the crawler, derive it from the first test URL in any suite
    if not app_name and all_data:
        app_name = next(
            (s["app_domain"] for s in all_data if s.get("app_domain")),
            None
        )

    # If crawler mode: match suites to journeys, collect unmatched as pending
    pending_journeys = []
    if crawler_journeys:
        suite_by_name = {s["suite_name"].strip().lower(): s for s in all_data}
        matched_ids   = set()
        for j in crawler_journeys:
            if j["title"].strip().lower() in suite_by_name:
                matched_ids.add(j["id"])
            else:
                pending_journeys.append(j)
        if pending_journeys:
            print(f"\n  {len(pending_journeys)} journeys not yet activated:")
            for j in pending_journeys:
                print(f"    ⏳ {j['title']}")

    multi_suite = (len(all_data) + len(pending_journeys)) > 1

    # Render detail pages for activated suites
    for data in all_data:
        detail_html = render_detail_html(data, base_url, generated_at, multi_suite=multi_suite)
        detail_path = os.path.join(output_dir, f"{data['suite_id']}.html")
        with open(detail_path, "w") as f:
            f.write(detail_html)
        print(f"  → {detail_path}")

    # Render index
    index_html = render_index_html(all_data, base_url, domain, generated_at,
                                   pending_journeys=pending_journeys, app_name=app_name)
    index_path = os.path.join(output_dir, "index.html")
    with open(index_path, "w") as f:
        f.write(index_html)

    print(f"\n✅  {index_path}")
    print(f"    file://{os.path.abspath(index_path)}")

if __name__ == "__main__":
    main()
