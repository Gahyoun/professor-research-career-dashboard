#!/usr/bin/env python3
"""alluvial.json → 파일 하나로 끝나는 HTML.

레이아웃을 파이썬에서 계산하고 SVG를 직접 찍는다. 차트 라이브러리를 쓰지 않으므로
오프라인에서도 열리고, 좁은 화면에서는 가로 스크롤로 읽힌다.

  python3 render_alluvial.py --data alluvial.json --out atlas.html
"""
import argparse, html, json, os
from collections import Counter

PALETTE = ["#2f6f9f", "#c2572c", "#5a8f5a", "#8a5fa8", "#c9972b",
           "#3f9b93", "#b0485f", "#7a6a4f", "#5b6ba8", "#9c7b3f"]


def ribbon(pts_top, pts_bot):
    """위/아래 경계점을 부드러운 베지어로 잇는 닫힌 패스."""
    def run(pts, rev=False):
        seq = pts[::-1] if rev else pts
        d = []
        for i, (x, y) in enumerate(seq):
            if i == 0:
                d.append(f"L{x:.1f},{y:.1f}" if rev else f"M{x:.1f},{y:.1f}")
            else:
                px, py = seq[i - 1]
                mx = (px + x) / 2
                d.append(f"C{mx:.1f},{py:.1f} {mx:.1f},{y:.1f} {x:.1f},{y:.1f}")
        return " ".join(d)
    return run(pts_top) + " " + run(pts_bot, rev=True) + " Z"


def build(D, title):
    """가로축을 1년 눈금으로 깐다. 기관은 상단 배경 띠로 내려가고, 논문은 발표 연도
    자리에 정확히 놓인다. 시기 칸으로 묶으면 같은 기관 안의 선후 관계가 뭉개진다."""
    topics, papers = D["topics"], D["papers"]
    years = [p["year"] for p in papers if p["year"]]
    y0, y1 = min(years), max(years)
    span = y1 - y0 + 1
    order = sorted(topics, key=lambda t: (t.get("birth_year") or 9999, -t["size"]))

    YW, LEFT, UNIT, GAP, MINT = 56, 272, 16, 22, 5
    # 상단: 기관 띠(겹치면 아래 줄로) → 연도 눈금 라벨
    spans = [e for e in D.get("era_span", []) if e.get("start")]
    rows, placed = [], []
    for e in spans:
        row = 0
        while any(p["row"] == row and not (e["start"] > p["end"] or e["end"] < p["start"])
                  for p in placed):
            row += 1
        placed.append(dict(e, row=row))
        rows.append(row)
    nrow = (max(rows) + 1) if rows else 0
    BAND0, BANDH = 44, 21
    tick_y = BAND0 + nrow * BANDH + 20
    TOP = tick_y + 26

    def cx(year):
        return LEFT + (year - y0 + 0.5) * YW

    cells = Counter((p["year"], p["topic"]) for p in papers if p["year"])
    lane_h = {t["id"]: max(MINT, max((cells.get((y, t["id"]), 0) for y in range(y0, y1 + 1)),
                                     default=0) * UNIT) for t in order}
    lane_y, cur = {}, TOP
    for t in order:
        lane_y[t["id"]] = cur + lane_h[t["id"]] / 2
        cur += lane_h[t["id"]] + GAP
    lanes_bottom = cur
    W = LEFT + span * YW + 40

    by_cell = {}
    for p in papers:
        if p["year"]:
            by_cell.setdefault((p["year"], p["topic"]), []).append(p)

    # ABA 띠 높이를 먼저 잡아 전체 높이를 확정한다
    agg = {}
    for rp in D.get("recip", []):
        fy, ty = rp.get("from_year"), rp.get("to_year")
        if fy and ty:
            agg.setdefault((fy, rp["from_topic"], ty, rp["to_topic"]), []).append(rp)
    # 가로로 겹치지 않는 경로끼리 같은 줄에 담아 띠 높이를 줄인다.
    # 줄마다 전 구간을 하나씩 쓰면 13줄이 되어 그림이 아래로 길어진다.
    flows = sorted(agg.items(), key=lambda kv: min(kv[0][0], kv[0][2]))
    row_end, slot_of = [], {}
    for key, rs in flows:
        lo, hi = min(key[0], key[2]), max(key[0], key[2])
        done = False
        for ri, end in enumerate(row_end):
            if lo > end:                       # 라벨 자리까지 한 해 띄운다
                row_end[ri] = hi + 1
                slot_of[key] = ri
                done = True
                break
        if not done:
            slot_of[key] = len(row_end)
            row_end.append(hi + 1)
    band = lanes_bottom + 10
    ROWH = 15
    H = (band + len(row_end) * ROWH + 26) if flows else lanes_bottom + 26

    sv = []
    # 연도 눈금
    for yr in range(y0, y1 + 1):
        x = cx(yr) - YW / 2
        sv.append(f'<line class="grid" x1="{x:.0f}" y1="{tick_y-12}" x2="{x:.0f}" y2="{H-22}"/>')
        sv.append(f'<text class="yr" x="{cx(yr):.0f}" y="{tick_y}">{yr}</text>')
    sv.append(f'<line class="grid" x1="{cx(y1)+YW/2:.0f}" y1="{tick_y-12}" '
              f'x2="{cx(y1)+YW/2:.0f}" y2="{H-22}"/>')

    # 기관 배경 띠
    for e in placed:
        xa, xb = cx(e["start"]) - YW / 2, cx(e["end"]) + YW / 2
        yy = BAND0 + e["row"] * BANDH
        sv.append(f'<rect class="eband" x="{xa:.0f}" y="{yy}" width="{xb-xa:.0f}" '
                  f'height="15" rx="2"><title>{html.escape(e["label"])} · '
                  f'{e["start"]}–{e["end"]} · {e["n"]}편</title></rect>')
        fit = max(3, int((xb - xa - 12) / 6.2))   # 좁은 띠에서 라벨이 넘치지 않게
        sv.append(f'<text class="era" x="{xa+7:.0f}" y="{yy+11}">'
                  f'{html.escape(e["label"][:fit])}</text>')

    # 분기선 — 모토픽 논문의 연도에서 새 토픽 첫 논문의 연도로
    for t in order:
        par = t.get("parent")
        if not par or not par.get("from_year") or not par.get("to_year"):
            continue
        xa, ya = cx(par["from_year"]), lane_y[par["from"]]
        xb, yb2 = cx(par["to_year"]) - 14, lane_y[t["id"]]
        mx = (xa + xb) / 2
        strong = par["sim"] >= 0.05
        sv.append(
            f'<path class="branch{"" if strong else " weak"}" fill="none" '
            f'stroke="#5d6775" stroke-width="1.6" '
            f'd="M{xa:.0f},{ya:.0f} C{mx:.0f},{ya:.0f} {mx:.0f},{yb2:.0f} {xb:.0f},{yb2:.0f}">'
            f'<title>T{par["from"]} ({par["from_year"]}) → T{t["id"]} ({par["to_year"]})'
            f'  유사도 {par["sim"]}\n{html.escape(par["via"][:70])}\n  ↓\n'
            f'{html.escape(par["to"][:70])}</title></path>')

    # 토픽 리본
    for i, t in enumerate(order):
        k = t["id"]
        col = PALETTE[i % len(PALETTE)]
        live = [y for y in range(y0, y1 + 1) if cells.get((y, k), 0)]
        if not live:
            continue
        a, b = min(live), max(live)
        top, bot = [], []
        for yr in range(a, b + 1):
            h = max(2.0, cells.get((yr, k), 0) * UNIT)
            for px in (cx(yr) - YW * 0.42, cx(yr) + YW * 0.42):
                top.append((px, lane_y[k] - h / 2))
                bot.append((px, lane_y[k] + h / 2))
        sv.append(f'<path class="rib" fill="{col}" d="{ribbon(top, bot)}"/>')

        for yr in live:
            n = cells[(yr, k)]
            sv.append(f'<circle class="dot" data-k="{yr}|{k}" cx="{cx(yr):.0f}" '
                      f'cy="{lane_y[k]:.0f}" r="10" fill="{col}"/>')
            sv.append(f'<text class="cnt" data-k="{yr}|{k}" x="{cx(yr):.0f}" '
                      f'y="{lane_y[k]+4:.0f}">{n}</text>')

        if not t.get("parent"):
            ht = max(MINT, cells.get((a, k), 0) * UNIT)
            sv.append(f'<text class="new" x="{cx(a):.0f}" y="{lane_y[k]-ht/2-5:.0f}">'
                      f'신규</text>')
        sv.append(f'<text class="lane" x="{LEFT-18}" y="{lane_y[k]-3:.0f}">'
                  f'{html.escape(f"T{k} · {t["label"]}"[:32])}</text>')
        sv.append(f'<text class="sub" x="{LEFT-18}" y="{lane_y[k]+12:.0f}">{t["size"]}편</text>')

    # ABA 경로 — A와 B의 실제 연도 양쪽에 꼭지를 단다
    def cell_bottom(yr, k):
        return lane_y[k] + max(MINT, cells.get((yr, k), 0) * UNIT) / 2

    for (fy, fk, ty, tk), rs in flows:
        if fk not in lane_y or tk not in lane_y:
            continue
        slot = slot_of[(fy, fk, ty, tk)]
        xa, xb = cx(fy), cx(ty)
        if fy == ty:
            xa, xb = xa - 16, xb + 16
        ya, yb2 = cell_bottom(fy, fk), cell_bottom(ty, tk)
        ybb = band + slot * ROWH
        wdt = 1.2 + len(rs) * 0.34
        ex = "\n".join(f"· {rp.get('from_year')} → [{rp['x'][:46]}, {rp['x_year']}] "
                        f"→ {rp.get('to_year')}" for rp in rs[:6])
        tip = (f"ABA {len(rs)}건  {fy} → {ty}"
               + (" · 같은 해" if fy == ty else "")
               + f"\nT{fk} 논문 → 타인 논문 → T{tk} 논문 (자기인용 제외)\n{ex}")
        dx = 12 if xb >= xa else -12
        sv.append(
            f'<path class="aba" fill="none" stroke="#b0485f" stroke-width="{wdt:.1f}" '
            f'd="M{xa:.0f},{ya:.0f} C{xa:.0f},{ya+16:.0f} {xa:.0f},{ybb:.0f} '
            f'{xa+dx:.0f},{ybb:.0f} L{xb-dx:.0f},{ybb:.0f} '
            f'C{xb:.0f},{ybb:.0f} {xb:.0f},{yb2+16:.0f} {xb:.0f},{yb2:.0f}">'
            f'<title>{html.escape(tip)}</title></path>')
        for px, py in ((xa, ya), (xb, yb2)):
            sv.append(f'<circle class="abatip" cx="{px:.0f}" cy="{py:.0f}" r="3.1" '
                      f'fill="#b0485f"/>')
        sv.append(f'<text class="rtx" x="{min(xa, xb)+16:.0f}" y="{ybb-4:.0f}">'
                  f'↺{len(rs)} {fy}–{ty}</text>')

    return W, H, "\n".join(sv)


TPL = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>@@TITLE@@</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@300;500;600&display=swap" rel="stylesheet">
<style>
:root{color-scheme:light;--bg:#eceef1;--ink:#171d26;--mut:#5d6775;--line:#c3c8d0;--card:#f7f8fa;
padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#12151c;--ink:#e7eaf0;--mut:#99a2b0;--line:#2f3744;--card:#1a1f29;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans KR",system-ui,sans-serif;font-weight:300;line-height:1.6}
.wrap{max-width:1180px;margin:0 auto;padding:28px 18px 56px}
h1{font-size:1.45rem;font-weight:600;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--mut);font-size:.86rem;margin:0 0 16px}
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 12px}
.tools input,.tools select{font-family:inherit;font-size:.86rem;font-weight:300;color:var(--ink);
background:var(--card);border:1px solid var(--line);border-radius:3px;padding:7px 10px}
.tools input{flex:1;min-width:190px}
.tools .n{color:var(--mut);font-size:.8rem}
.tools button{font-family:inherit;font-size:.8rem;background:none;border:1px solid var(--line);
color:var(--mut);border-radius:3px;padding:7px 10px;cursor:pointer}
.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:3px;padding:4px 0}
svg{display:block}
text{font-family:"IBM Plex Sans KR",sans-serif}
.era{font-size:10.5px;fill:var(--ink);font-weight:500}
.yr{font-size:9.5px;fill:var(--mut);opacity:.7;text-anchor:middle}
.eband{fill:var(--line);opacity:.45}
.grid{stroke:var(--line);stroke-width:1;opacity:.35}
.lane{font-size:12px;fill:var(--ink);text-anchor:end;font-weight:500}
text.sub{font-size:10.5px;fill:var(--mut);text-anchor:end}
.rib{opacity:.5}
.rib:hover{opacity:.78}
.dot{opacity:.95;cursor:pointer}
.cnt{font-size:10.5px;fill:#fff;text-anchor:middle;font-weight:600;pointer-events:none}
.branch{fill:none;stroke:var(--mut);stroke-width:1.6}
.branch.weak{stroke-dasharray:3 3;opacity:.6}
.new{font-size:9.5px;fill:var(--mut);text-anchor:middle;letter-spacing:.02em}
.aba{fill:none;stroke:#b0485f;opacity:.5;stroke-linecap:round}
.aba:hover{opacity:.95}
.abatip{fill:#b0485f;opacity:.85}
.rtx{font-size:9.5px;fill:#b0485f;opacity:.85}
.dim{opacity:.12}
.hit{stroke:var(--ink);stroke-width:2.5}
#card{position:fixed;z-index:50;max-width:380px;background:var(--card);border:1px solid var(--line);
border-radius:4px;padding:12px 14px;box-shadow:0 6px 22px rgba(0,0,0,.18);font-size:.84rem;display:none}
#card .hd{font-size:.75rem;color:var(--mut);margin-bottom:7px}
#card .it{padding:7px 0;border-top:1px solid var(--line)}
#card .it:first-of-type{border-top:none}
#card .tt{font-weight:500;line-height:1.45}
#card .mt{color:var(--mut);font-size:.78rem;margin-top:2px}
#card a{color:#b0485f;text-decoration:none;border-bottom:1px solid currentColor}
#res{margin-top:14px;font-size:.84rem}
#res .it{padding:8px 0;border-bottom:1px solid var(--line)}
#res .mt{color:var(--mut);font-size:.78rem}
#res a{color:#b0485f;text-decoration:none;border-bottom:1px solid currentColor}
#res .sc{display:inline-block;min-width:30px;color:var(--mut);font-size:.76rem}
.key{display:flex;flex-wrap:wrap;gap:16px;margin-top:18px;font-size:.8rem;color:var(--mut)}
.key b{font-weight:500;color:var(--ink)}
footer{margin-top:26px;font-size:.78rem;color:var(--mut);border-top:1px solid var(--line);padding-top:14px}
</style></head><body><div class="wrap">
<h1>@@TITLE@@</h1>
<p class="sub">@@SUBTITLE@@</p>
<div class="tools">
  <input id="q" type="search" placeholder="자연어로 검색 — 예: how networks break apart under node removal" autocomplete="off">
  <select id="tsel"><option value="">모든 토픽</option>@@TOPTS@@</select>
  <select id="psel" style="display:@@PDISP@@"><option value="">모든 연구자</option>@@POPTS@@</select>
  <span class="n" id="n"></span>
  <button id="clr">초기화</button>
</div>
<div class="scroll"><svg viewBox="0 0 @@W@@ @@H@@" width="@@W@@" height="@@H@@" xmlns="http://www.w3.org/2000/svg">@@SVG@@</svg></div>
<div id="res"></div>
<div class="key"><span><b>가로축</b> 1년 눈금 · 상단 띠는 소속 기관</span>
<span><b>리본 두께</b> 그 해 그 토픽의 논문 수</span>
<span><b>점에 올리면</b> 제목 · 저널 · DOI 바로가기</span>
<span><b>검색</b> 제목·초록·토픽으로 만든 LSA 공간에서 의미 검색 (없는 말은 부분일치로 후퇴)</span>
<span><b>실선 분기</b> 공유 참고문헌으로 이어지는 모토픽</span>
<span><b>점선</b> 약한 연결</span>
<span><b>신규</b> 선행 토픽과 공유 참고문헌 없음</span>
<span><b>↺</b> ABA 경로 — 초기 논문을 인용한 <b>타인 논문</b>을 후기 논문이 다시 인용 (자기인용 제외)</span></div>
<footer>@@FOOTER@@</footer>
</div>
<div id="card"></div>
<script>
const D = @@DATA@@;
const card = document.getElementById('card');
let pinned = null, hideT = null;

const esc = s => (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function item(p){
  const doi = p.doi ? ` · <a href="${esc(p.doi)}" target="_blank" rel="noopener">DOI</a>` : '';
  return `<div class="it"><div class="tt">${esc(p.title)}</div>`
       + `<div class="mt">${p.who ? esc(p.who) + ' · ' : ''}${esc(p.venue||'출처 미상')}`
       + ` · ${p.year} · 피인용 ${p.cited}${doi}</div></div>`;
}
function show(key, x, y){
  const ps = D.cells[key]; if(!ps) return;
  const [yr, k] = key.split('|');
  card.innerHTML = `<div class="hd">${yr} · ${esc(D.labels[k] || '')} · ${ps.length}편</div>`
                 + ps.map(item).join('');
  card.style.display = 'block';
  const w = card.offsetWidth, h = card.offsetHeight;
  card.style.left = Math.min(x + 14, innerWidth - w - 12) + 'px';
  card.style.top  = Math.max(8, Math.min(y + 14, innerHeight - h - 12)) + 'px';
}
function hide(){ if(!pinned) card.style.display = 'none'; }

document.querySelectorAll('.dot').forEach(el => {
  el.addEventListener('mouseenter', e => { clearTimeout(hideT); if(!pinned) show(el.dataset.k, e.clientX, e.clientY); });
  el.addEventListener('mouseleave', () => { hideT = setTimeout(hide, 260); });
  el.addEventListener('click', e => { e.stopPropagation(); pinned = null; show(el.dataset.k, e.clientX, e.clientY); pinned = el.dataset.k; });
});
card.addEventListener('mouseenter', () => clearTimeout(hideT));
card.addEventListener('mouseleave', () => { if(!pinned) hide(); });
document.addEventListener('click', () => { pinned = null; card.style.display = 'none'; });

const q = document.getElementById('q'), tsel = document.getElementById('tsel');
const psel = document.getElementById('psel');
const nEl = document.getElementById('n'), res = document.getElementById('res');
function subMatch(p, term){
  return (p.title + ' ' + (p.venue||'') + ' ' + p.year + ' ' + D.labels[p.topic]).toLowerCase().includes(term);
}
// 자연어 질의 → LSA 공간. 단어 벡터를 평균 내고 논문 벡터와 코사인을 잰다.
// 모델도 네트워크도 쓰지 않는다 — 벡터가 이미 이 파일 안에 있다.
function semScores(term){
  if(!D.sem) return null;
  const ws = (term.match(/[a-z][a-z-]{2,}/g) || []).map(w => D.sem.terms[w]).filter(Boolean);
  if(!ws.length) return null;
  const n = D.sem.dims, v = new Array(n).fill(0);
  ws.forEach(t => { for(let i=0;i<n;i++) v[i] += t[i]; });
  let m = Math.hypot(...v) || 1e-9;
  for(let i=0;i<n;i++) v[i] /= m;
  const out = {};
  for(const [id, pv] of Object.entries(D.sem.papers)){
    let s = 0; for(let i=0;i<n;i++) s += v[i]*pv[i];
    out[id] = s;
  }
  return out;
}
const SEM_MIN = 0.33;
function run(){
  const term = q.value.trim().toLowerCase(), topic = tsel.value;
  const who = psel ? psel.value : '';
  const byTopic = D.papers.filter(p =>
      (topic === '' || String(p.topic) === topic) && (who === '' || p.who === who));
  const sc = term ? semScores(term) : null;
  let hits, mode = '';
  if(!term){ hits = byTopic; }
  else if(sc){
    hits = byTopic.map(p => ({...p, score: sc[p.id] ?? 0}))
                  .filter(p => p.score >= SEM_MIN)
                  .sort((a,b) => b.score - a.score);
    mode = '의미 검색';
    if(!hits.length){ hits = byTopic.filter(p => subMatch(p, term)); mode = '부분일치'; }
  } else {
    hits = byTopic.filter(p => subMatch(p, term)); mode = '부분일치 (어휘에 없는 말)';
  }
  const keys = new Set(hits.map(p => p.year + '|' + p.topic));
  const active = term || topic !== '' || who !== '';
  document.querySelectorAll('.dot, .cnt').forEach(el => {
    el.classList.toggle('dim', active && !keys.has(el.dataset.k));
    el.classList.toggle('hit', active && el.tagName === 'circle' && keys.has(el.dataset.k));
  });
  document.querySelectorAll('.rib').forEach(el => el.classList.toggle('dim', active));
  nEl.textContent = active ? `${hits.length}편 일치${mode ? ' · ' + mode : ''}`
                           : `${D.papers.length}편`;
  res.innerHTML = active
    ? hits.map(p =>
        `<div class="it">${p.score !== undefined ? `<span class="sc">${p.score.toFixed(2)}</span> ` : ''}`
        + `<b>${p.year}</b> ${esc(p.title)}<div class="mt">`
        + (p.who ? esc(p.who) + ' · ' : '') + `${esc(D.labels[p.topic])}`
        + ` · ${esc(p.venue||'출처 미상')} · 피인용 ${p.cited}`
        + (p.doi ? ` · <a href="${esc(p.doi)}" target="_blank" rel="noopener">DOI</a>` : '') + `</div></div>`).join('')
    : '';
}
q.addEventListener('input', run);
tsel.addEventListener('change', run);
if(psel) psel.addEventListener('change', run);
document.getElementById('clr').addEventListener('click', () => {
  q.value=''; tsel.value=''; if(psel) psel.value=''; run(); });
run();
</script></body></html>"""


def page(D, title, footer, w, h, svg, sem=None, people=None, sub=None):
    """SVG + 데이터 → 자립 HTML 한 장. 단일/다중 연구자 렌더러가 공유한다."""
    cells = {}
    for p in D["papers"]:
        if p.get("year") is None:
            continue
        cells.setdefault(f'{p["year"]}|{p["topic"]}', []).append(
            {"title": p["title"], "venue": p.get("venue", ""), "year": p["year"],
             "cited": p.get("cited", 0), "doi": p.get("doi")})
    labels = {str(t["id"]): f'T{t["id"]} · {t["label"]}' for t in D["topics"]}
    data = {"cells": cells, "labels": labels,
            "papers": [{"id": p["id"], "title": p["title"], "venue": p.get("venue", ""),
                        "year": p["year"], "cited": p.get("cited", 0), "doi": p.get("doi"),
                        "topic": p["topic"], "who": p.get("who", "")}
                       for p in D["papers"] if p.get("year") is not None]}
    if sem:
        data["sem"] = sem
    opts = "".join(f'<option value="{t["id"]}">{html.escape(labels[str(t["id"])])}</option>'
                   for t in sorted(D["topics"], key=lambda t: t["id"]))
    if sub is None:
        sub = (f'유니크 논문 {len(D["papers"])}편 · 토픽 {len(D["topics"])}개 · '
               f'{min(p["year"] for p in D["papers"] if p["year"])}–'
               f'{max(p["year"] for p in D["papers"] if p["year"])}'
               + (f' · ABA 경로 {len(D["recip"])}건' if D.get("recip") else ""))
    popts = "".join(f'<option value="{html.escape(n)}">{html.escape(n)}</option>'
                    for n in (people or []))
    out = TPL
    for tok, val in (("@@TITLE@@", html.escape(title)), ("@@SUBTITLE@@", html.escape(sub)),
                     ("@@W@@", str(w)), ("@@H@@", str(h)), ("@@SVG@@", svg),
                     ("@@TOPTS@@", opts), ("@@FOOTER@@", html.escape(footer)),
                     ("@@POPTS@@", popts), ("@@PDISP@@", "inline" if people else "none"),
                     ("@@DATA@@", json.dumps(data, ensure_ascii=False)
                      .replace("</", "<\\/"))):
        out = out.replace(tok, val)
    return out


def render(D, title, footer, sem=None):
    """alluvial.json → 자립 HTML 한 장."""
    w, h, svg = build(D, title)
    return page(D, title, footer, w, h, svg, sem)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--out", default="atlas.html")
    p.add_argument("--title", default=None)
    p.add_argument("--semantic", default=None,
                   help="semantic_index.py 가 만든 색인. 있으면 자연어 검색이 켜진다")
    p.add_argument("--footer", default="출처: OpenAlex. 동명이인은 논문별 소속 원문과 "
                                       "경력 타임라인의 일치로 판별했고, preprint·저널판은 한 편으로 합쳤다.")
    a = p.parse_args()
    D = json.load(open(a.data))
    title = a.title or f"{D['name']} — 연구 토픽 분화"
    sem = json.load(open(a.semantic)) if a.semantic and os.path.exists(a.semantic) else None
    open(a.out, "w").write(render(D, title, a.footer, sem))
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()
