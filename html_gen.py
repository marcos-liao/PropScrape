"""HTML output generator — kartu listing properti."""

import re
from datetime import datetime

PLATFORM_COLORS = [
    "#1a73e8", "#e63946", "#f4a261", "#2a9d8f", "#e76f51",
    "#457b9d", "#6a4c93", "#f72585", "#4cc9f0", "#52b788",
    "#d62828", "#023e8a", "#b5838d", "#6d6875", "#3a86ff",
]


def _platform_color(name: str) -> str:
    idx = abs(hash(name)) % len(PLATFORM_COLORS)
    return PLATFORM_COLORS[idx]


def _listing_to_card(l: dict, color: str) -> str:
    source = l.get("source", "")
    title  = l.get("title") or "(Tanpa judul)"
    price  = l.get("price_label", "")
    loc    = l.get("location", "—")
    desc   = (l.get("desc") or "").strip()
    agent  = l.get("agent") or "—"
    url    = l.get("url") or "#"
    img    = l.get("image") or ""

    img_block = (
        f'<img class="card-img" src="{img}" alt="" loading="lazy" '
        f'onerror="this.style.display=\'none\';this.nextSibling.style.display=\'flex\'">'
        f'\n    <div class="card-img-placeholder" style="display:none">🏠</div>'
        if img and img.startswith("http")
        else '<div class="card-img-placeholder">🏠</div>'
    )

    price_block = f'<div class="card-price">{price}</div>' if price else ""

    specs = []
    if l.get("lt"): specs.append(f"LT {l['lt']} m²")
    if l.get("lb"): specs.append(f"LB {l['lb']} m²")
    if l.get("kt"): specs.append(f"🛏 {l['kt']}")
    if l.get("km"): specs.append(f"🚿 {l['km']}")
    specs_block = (
        '<div class="specs">' + "".join(f'<span class="spec">{s}</span>' for s in specs) + "</div>"
        if specs else ""
    )
    desc_block = f'<div class="card-desc">{desc}</div>' if desc else ""

    badge_style = f"background:{color}22;color:{color};border-color:{color}"

    return f"""
  <div class="card" data-source="{source}">
    {img_block}
    <div class="card-body">
      <div class="source-badge" style="{badge_style}">{source}</div>
      <div class="card-title">{title}</div>
      {price_block}
      <div class="card-location">📍 {loc}</div>
      {specs_block}
      {desc_block}
    </div>
    <div class="card-footer">
      <div class="card-agent">👤 {agent}</div>
      <a class="btn-lihat" href="{url}" target="_blank" rel="noopener"
         style="background:{color}">Lihat →</a>
    </div>
  </div>"""


def generate_html(keyword: str, listings: list[dict], platforms: list[dict]) -> str:
    # Hitung per platform
    platform_counts: dict[str, int] = {}
    for l in listings:
        s = l.get("source", "Unknown")
        platform_counts[s] = platform_counts.get(s, 0) + 1

    # Warna per platform
    colors: dict[str, str] = {p["name"]: _platform_color(p["name"]) for p in platforms}

    # Filter buttons
    filter_btns = '<div class="badge all active" onclick="filterSource(\'all\')">Semua (' + str(len(listings)) + ")</div>\n"
    for name, count in sorted(platform_counts.items(), key=lambda x: -x[1]):
        color = colors.get(name, "#888")
        filter_btns += f'<div class="badge" style="background:{color}22;color:{color};border-color:{color}" onclick="filterSource(\'{name}\')">{name} ({count})</div>\n'

    # Cards
    cards_html = ""
    if listings:
        for l in listings:
            color = colors.get(l.get("source", ""), "#888")
            cards_html += _listing_to_card(l, color)
    else:
        cards_html = '<div class="empty">😕 Tidak ada listing ditemukan.</div>'

    # Platform discovery summary
    platform_summary = ""
    for p in platforms:
        c = colors.get(p["name"], "#888")
        cnt = platform_counts.get(p["name"], 0)
        platform_summary += f'<div class="p-item"><span class="p-dot" style="background:{c}"></span>{p["name"]} <em>({p["domain"]})</em> — {cnt} listing</div>\n'

    ts = datetime.now().strftime("%d %b %Y, %H:%M")

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Pencarian Properti: {keyword}</title>
  <style>
    :root {{ --bg:#f4f6f9; --card:#fff; --text:#1e293b; --sub:#64748b; --border:#e2e8f0; }}
    * {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{ font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); }}

    header {{ background:#1a73e8; color:#fff; padding:20px 32px; }}
    header h1 {{ font-size:1.4rem; font-weight:700; }}
    header .meta {{ font-size:.82rem; opacity:.8; margin-top:4px; }}

    .discovery-bar {{
      background:#fff; border-bottom:1px solid var(--border);
      padding:10px 32px; font-size:.78rem; color:var(--sub);
    }}
    .discovery-bar summary {{ cursor:pointer; font-weight:600; color:#1a73e8; }}
    .p-item {{ margin:4px 0; display:flex; align-items:center; gap:6px; }}
    .p-dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; flex-shrink:0; }}

    .filters {{
      background:#fff; padding:10px 32px;
      border-bottom:1px solid var(--border);
      display:flex; gap:6px; flex-wrap:wrap; align-items:center;
    }}
    .filters > span {{ font-size:.78rem; color:var(--sub); }}
    .badge {{
      padding:4px 12px; border-radius:20px; font-size:.73rem;
      font-weight:600; cursor:pointer; border:2px solid transparent;
      transition:opacity .2s;
    }}
    .badge.all {{ background:#1a73e8; color:#fff; border-color:#1a73e8; }}
    .badge:not(.all):hover {{ opacity:.75; }}

    .stats {{ padding:10px 32px; font-size:.82rem; color:var(--sub); }}

    .grid {{
      display:grid;
      grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
      gap:18px; padding:18px 32px 48px;
      max-width:1400px; margin:0 auto;
    }}

    .card {{
      background:var(--card); border-radius:12px;
      border:1px solid var(--border);
      box-shadow:0 2px 8px rgba(0,0,0,.07);
      overflow:hidden; display:flex; flex-direction:column;
      transition:transform .2s,box-shadow .2s;
    }}
    .card:hover {{ transform:translateY(-3px); box-shadow:0 8px 20px rgba(0,0,0,.12); }}

    .card-img {{ width:100%; height:195px; object-fit:cover; display:block; background:#e2e8f0; }}
    .card-img-placeholder {{
      width:100%; height:195px; display:flex;
      align-items:center; justify-content:center;
      background:linear-gradient(135deg,#e2e8f0,#cbd5e1);
      font-size:2.5rem; color:#94a3b8;
    }}

    .card-body {{ padding:14px; flex:1; display:flex; flex-direction:column; gap:7px; }}

    .source-badge {{
      display:inline-block; padding:2px 8px; border-radius:4px;
      font-size:.68rem; font-weight:700; width:fit-content;
      border:1.5px solid;
    }}
    .card-title {{
      font-size:.92rem; font-weight:600; line-height:1.4;
      display:-webkit-box; -webkit-line-clamp:2;
      -webkit-box-orient:vertical; overflow:hidden;
    }}
    .card-price {{ font-size:1.1rem; font-weight:700; color:#1a73e8; }}
    .card-location {{ font-size:.78rem; color:var(--sub); display:flex; gap:3px; }}
    .specs {{ display:flex; flex-wrap:wrap; gap:5px; }}
    .spec {{ background:var(--bg); border-radius:5px; padding:2px 7px; font-size:.72rem; color:var(--sub); }}
    .card-desc {{
      font-size:.76rem; color:var(--sub); line-height:1.5;
      display:-webkit-box; -webkit-line-clamp:3;
      -webkit-box-orient:vertical; overflow:hidden;
    }}
    .card-footer {{
      padding:10px 14px; border-top:1px solid var(--border);
      display:flex; align-items:center; justify-content:space-between; gap:8px;
    }}
    .card-agent {{ font-size:.73rem; color:var(--sub); flex:1; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }}
    .btn-lihat {{
      display:inline-block; color:#fff;
      padding:5px 12px; border-radius:6px;
      font-size:.75rem; font-weight:600;
      text-decoration:none; white-space:nowrap;
      transition:opacity .2s;
    }}
    .btn-lihat:hover {{ opacity:.85; }}
    .empty {{ grid-column:1/-1; text-align:center; padding:60px 20px; color:var(--sub); font-size:1rem; }}

    @media(max-width:600px) {{ .grid,.filters,.stats {{ padding-left:14px; padding-right:14px; }} }}
  </style>
</head>
<body>

<header>
  <h1>🏠 Pencarian Properti Indonesia</h1>
  <div class="meta">
    Keyword: <strong>"{keyword}"</strong> &nbsp;|&nbsp;
    {len(platforms)} platform ditemukan &nbsp;|&nbsp;
    {len(listings)} total listing &nbsp;|&nbsp;
    {ts}
  </div>
</header>

<div class="discovery-bar">
  <details>
    <summary>Platform yang ditemukan ({len(platforms)})</summary>
    <div style="margin-top:8px">
      {platform_summary}
    </div>
  </details>
</div>

<div class="filters">
  <span>Filter:</span>
  {filter_btns}
</div>

<div class="stats">
  Menampilkan <span id="showing">{len(listings)}</span> dari {len(listings)} properti
</div>

<div class="grid" id="grid">
  {cards_html}
</div>

<script>
  function filterSource(src) {{
    const cards = document.querySelectorAll('.card');
    let count = 0;
    cards.forEach(c => {{
      const show = src === 'all' || c.dataset.source === src;
      c.style.display = show ? '' : 'none';
      if (show) count++;
    }});
    document.getElementById('showing').textContent = count;
    document.querySelectorAll('.badge').forEach(b => b.classList.remove('active'));
  }}
</script>
</body>
</html>"""
