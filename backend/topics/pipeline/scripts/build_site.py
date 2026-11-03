#!/usr/bin/env python3
"""alluvial.json 들을 모아 GitHub Pages 로 띄울 정적 사이트를 만든다.

연구자 한 명당 디렉터리 하나를 받아, 각자의 다이어그램 페이지와 전체 색인을 찍는다.
서버도 빌드 도구도 필요 없다 — 나오는 것은 HTML 뿐이고 docs/ 를 Pages 소스로 지정하면 끝.

  python3 build_site.py --data-dir data --out docs --site-title "연구 토픽 분화 지도"

data/
  sang-hoon-lee/alluvial.json
  another-person/alluvial.json
"""
import argparse, html, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_alluvial import render  # noqa: E402

INDEX = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@300;500;600&display=swap" rel="stylesheet">
<style>
:root{{color-scheme:light;--bg:#eceef1;--ink:#171d26;--mut:#5d6775;--line:#c3c8d0;--card:#f7f8fa;
padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{color-scheme:dark;--bg:#12151c;--ink:#e7eaf0;--mut:#99a2b0;--line:#2f3744;--card:#1a1f29;}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans KR",system-ui,sans-serif;font-weight:300;line-height:1.6}}
.wrap{{max-width:760px;margin:0 auto;padding:40px 20px 64px}}
h1{{font-size:1.6rem;font-weight:600;margin:0 0 6px}}
p.lede{{color:var(--mut);margin:0 0 30px}}
a.card{{display:block;text-decoration:none;color:inherit;background:var(--card);
border:1px solid var(--line);border-radius:3px;padding:16px 18px;margin-bottom:10px}}
a.card:hover{{border-color:var(--mut)}}
.nm{{font-weight:500;font-size:1.05rem}}
.mt{{color:var(--mut);font-size:.84rem;margin-top:3px}}
footer{{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);color:var(--mut);font-size:.8rem}}
code{{font-size:.84em}}
</style></head><body><div class="wrap">
<h1>{title}</h1><p class="lede">{lede}</p>
{cards}
<footer>{footer}</footer></div></body></html>"""


def slug(s):
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out", default="docs")
    p.add_argument("--site-title", default="연구 토픽 분화 지도")
    p.add_argument("--lede", default="OpenAlex 인용 데이터로 재구성한 연구자별 토픽 분화. "
                                     "동명이인은 소속 연속성으로 걸러냈다.")
    p.add_argument("--footer", default="데이터: OpenAlex (CC0). "
                                       "파이프라인: openalex-topic-alluvial.")
    a = p.parse_args()

    os.makedirs(a.out, exist_ok=True)
    cards = []
    for name in sorted(os.listdir(a.data_dir)):
        path = os.path.join(a.data_dir, name, "alluvial.json")
        if not os.path.exists(path):
            continue
        D = json.load(open(path))
        s = slug(D["name"])
        title = f"{D['name']} — 연구 토픽 분화"
        ys = [p["year"] for p in D["papers"] if p["year"]]
        sub = (f"유니크 논문 {len(D['papers'])}편 · 토픽 {len(D['topics'])}개 · "
               f"{min(ys)}–{max(ys)}"
               + (f" · ABA 경로 {len(D['recip'])}건" if D.get("recip") else ""))
        os.makedirs(os.path.join(a.out, s), exist_ok=True)
        open(os.path.join(a.out, s, "index.html"), "w").write(render(D, title, a.footer))
        # 원자료도 같이 올려 둔다 — 남이 검증하거나 다시 쓸 수 있어야 한다
        json.dump(D, open(os.path.join(a.out, s, "alluvial.json"), "w"), ensure_ascii=False)
        new = sum(1 for t in D["topics"] if not t.get("parent"))
        cards.append(f'<a class="card" href="./{s}/"><div class="nm">'
                     f'{html.escape(D["name"])}</div><div class="mt">{html.escape(sub)} · '
                     f'독립 신규 토픽 {new}개</div></a>')
        print(f"  {s}/  ({len(D['papers'])}편)")

    if not cards:
        sys.exit(f"{a.data_dir} 안에 <이름>/alluvial.json 이 없다.")
    open(os.path.join(a.out, "index.html"), "w").write(
        INDEX.format(title=html.escape(a.site_title), lede=html.escape(a.lede),
                     cards="\n".join(cards), footer=html.escape(a.footer)))
    open(os.path.join(a.out, ".nojekyll"), "w").write("")
    print(f"→ {a.out}/index.html ({len(cards)}명)")


if __name__ == "__main__":
    main()
