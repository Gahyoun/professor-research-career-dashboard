# 연구 토픽 흐름 (`#/topics`)

교수별 논문을 공유 참고문헌으로 클러스터링한 토픽을 연도·경력 시기 축에 배치하고, 영문 특징어와 의미 검색으로 여러 교수의 토픽을 같은 연도축에 비교한다.

## 화면

| 기능 | 내용 |
| --- | --- |
| 연구자·기관 검색 | 익명 ID·현재 기관·분야. 실명은 잠금 해제 후에만 검색 대상에 들어간다. |
| 토픽·키워드 검색 | 영문 질의, 한국어 질의는 용어집으로 영문 변환. 태그 일치(0.45)와 LSA 코사인(0.55)을 합산해 모든 연구자의 토픽을 순위화한다. |
| 단일 연구자 | 토픽 레인 × 연도(또는 경력 시기). 띠 두께 = 논문 수, 점선 = 모토픽 분기, NEW = 독립 신규, 회색 호 = ABA 경로. |
| 멀티 연구자 | 검색에 걸린 토픽을 **스택**(연구자별 레인) 또는 **오버랩**(연구자별 색 누적)으로 비교. |
| 논문 제목 | `titles/`가 있으면 잠금 해제 후 툴팁에 제목·저널·DOI 표시. 연구자를 열 때 그 연구자 파일만 받아 메모리에서 복호화. |

멀티 뷰의 토픽은 연구자마다 따로 클러스터링한 결과다. 같은 질의에 걸린 토픽을 같은 연도축에 놓은 비교이며, 전원을 다시 클러스터링한 공통 토픽축(`pipeline/scripts/build_multi.py`)과는 다르다.

## 공개 범위

- `public/data/topics/index.json`: 익명 ID, 분야, 현재 기관, 경력 시기 라벨, 토픽 이름·특징어(영문)·LSA 벡터, 논문별 `{year, topic, era, cited}`, ABA 쌍의 연도·토픽. **논문 제목·DOI·실명 없음** — `normalizeTopicIndex`가 제목 필드를 발견하면 로딩을 거부한다.
- `public/data/topics/titles/key.json` + `titles/<anon_id>.json`: 연구자별 `[{year, topic, title, venue, doi}]`를 AES-256-GCM으로 암호화. 키는 `NAMES_PASSWORD`에서 PBKDF2-SHA256 600,000회로 한 번 만들고(salt는 `key.json`), 파일마다 nonce가 따로이며 AAD `topic-titles-v2:<anon_id>`로 연구자에 묶인다. `key.json`의 `check`로 비밀번호를 확인한다. 만드는 법: `python3 -I backend/topics/encrypt_titles.py --manifest $W/manifest.txt --env-file <private>/names.env`.
- `public/data/topics/info/<anon_id>.json`: 연구자별 분기·합류 정보량 블록. 색인의 `info_path`가 있으면 연구자를 고를 때만 불러온다.
- `source: "demo"`인 색인은 화면에 "예시 데이터" 표시가 붙는다. 합성 예시(`backend/topics/make_demo_index.py`)는 검색 동작 테스트용으로 `tests/fixtures/topic_index_demo.json`에 남아 있다.
- 토픽 특징어에는 페이지 상용구·소속(orcid, author, university, department, seoul …)과 사람 이름이 들어가지 않는다. OpenAlex 초록 중 스크랩된 랜딩 페이지·표지 설명문("in article number …, A, B and co-workers")·정정 공지("… et al.")는 라벨 텍스트에서 빼고, 로마자 한국 이름 음절로만 된 구와 비공개 이름 목록(`--exclude-terms`)에 있는 구는 특징어로 쓰지 않는다.

## 데이터 만들기

### 전체 릴리스 (현재 공개 색인)

```bash
W="$PRIVATE/backend/cache/2026/topics_release"        # 비공개 작업 폴더, STEP_LOG.md와 단계별 kept/dropped
C="$HOME/Library/Caches/professor-career-dashboard/openalex"   # OpenAlex 캐시 (저장소 밖)
python3 -I backend/topics/build_release_topics.py select --private "$PRIVATE" --work-dir "$W"
python3 -I backend/topics/build_release_topics.py fetch  --work-dir "$W" --cache "$C" --env-file "$PRIVATE/.private/openalex.env"
python3 -I backend/topics/build_release_topics.py build  --private "$PRIVATE" --work-dir "$W" --cache "$C"
python3 -I backend/topics/export_public_index.py --manifest "$W/manifest.txt" --split-info \
    --exclude-terms "$W/03_name_terms.txt" --coverage "2025년까지 … 2026년은 partial" --out-dir public/data/topics
```

- 대상: identity_decision = keep, KOAD namesake 제외, article·review·letter·editorial, 출판연도 ≤ 2026(2026은 원본 snapshot까지).
- 토픽: bibliographic coupling network에서 weighted Louvain. edge는 공통 참고문헌 c_ij ≥ 2, 가중치 w_ij = c_ij / √(|R_i||R_j|) (Salton cosine), resolution 1.05, seed 4. edge 없는 논문과 1편짜리 community는 "Other".
- 경력 시기는 공개 `dashboard.json`의 career 구간이다. ABA 경로(피인용 수집)는 이 릴리스에서 계산하지 않았다(`method.recip = "not computed"`).
- API 키는 `--env-file` 안에서만 읽고 출력·기록하지 않는다. `NAMES_PASSWORD`가 있을 때만 `titles/`를 쓴다(또는 `encrypt_titles.py`로 따로 만든다).

### 연구자 한 명씩 (원본 파이프라인)

```bash
pip install -r backend/topics/pipeline/requirements.txt cryptography

# 1) KOAD 판정을 파이프라인 입력으로 (대시보드와 같은 논문 집합)
python3 backend/topics/koad_verdicts.py --koad-dir "$KOAD_RUN" \
    --professor-uid "$PROFESSOR_UID" --out "$WORK/<slug>/verdicts.json"

# 2) 수집 → 판별(어댑터) → 토픽 → 라벨 → 분기  (backend/topics/pipeline, 원본 run.sh와 같은 순서)
python3 backend/topics/pipeline/scripts/fetch_works.py --name "..." --seed-title "..." --out "$WORK/<slug>/works.json"
python3 backend/topics/pipeline/adapters/external_disambiguator.py --works "$WORK/<slug>/works.json" \
    --verdicts "$WORK/<slug>/verdicts.json" --institutions "$WORK/<slug>/institutions.json" --out "$WORK/<slug>/seeds.json"
python3 backend/topics/pipeline/scripts/topics.py --seeds "$WORK/<slug>/seeds.json" --out "$WORK/<slug>/topics.json"
python3 backend/topics/pipeline/scripts/label_topics.py --seeds "$WORK/<slug>/seeds.json" --topics "$WORK/<slug>/topics.json"
python3 backend/topics/pipeline/scripts/branching.py --seeds "$WORK/<slug>/seeds.json" \
    --topics "$WORK/<slug>/topics.json" --out "$WORK/<slug>/alluvial.json" --citers

# 3) 공개 색인 + 암호화 제목 (익명 ID는 공개 대시보드 모집단에 있어야 한다)
NAMES_PASSWORD=... python3 backend/topics/export_public_index.py \
    --researcher "$WORK/<slug>=P-XXXXXXXXXX" --out-dir public/data/topics
```

`$WORK`는 비공개 경로다. `works.json`, `seeds.json`, `alluvial.json`에는 제목이 있으므로 저장소에 커밋하지 않는다.

## 이름·특징어와 검색 (영문 기준)

커뮤니티(토픽)의 이름과 특징은 **영문 c-TF-IDF 용어**로만 붙인다. 기계 번역한 한국어 라벨·태그는 붙이지 않는다.

- **특징어(keywords)**: 커뮤니티 하나를 문서 하나로 합친 c-TF-IDF(1–2-gram). 커뮤니티의 60% 이상에 나오는 말은 먼저 제외한다. 구(phrase)는 자기 구성 단어와 빈도가 같아지므로 1.5배 가중해 "machine learning"이 "learning"보다 먼저 뽑히게 하고, 이미 뽑힌 말의 단어로만 이루어진 우연한 인접쌍("law spectral")은 버린다(`topic_semantics.ctfidf_terms`).
- **이름(label)**: 상위 특징어 3개를 `·`로 잇는다(`english_label`). 어간이 같거나 단어가 겹치는 항은 한 번만 쓴다. 사람이 고친 라벨은 **영문일 때만** 유지한다. 잔여 소군집은 `Other · …`.
- **태그(tags.en)**: 특징어 + 영문 라벨 조각. `tags.ko`는 스키마 호환용으로 비워 둔다.
- **한국어 검색어**: `tag_glossary.json`(ko→en)은 **질의 쪽에서만** 쓰인다. 한국어 단어를 영문 용어로 바꾼 뒤 특징어의 단어와 LSA 공간에 맞춘다. 용어집 정확 항목을 먼저 쓰고, 없을 때만 부분 일치를 쓴다("전자" ⊂ "유전자" 충돌 방지).
- **의미 검색**: 전체 연구자의 논문(제목·초록·OpenAlex 토픽/키워드)을 하나의 TF-IDF→SVD(LSA) 공간에 넣고, 토픽 중심 벡터와 단어 벡터를 int8로 색인에 넣는다. 차원은 문서 수의 절반 이하. 점수 = 0.55·LSA 코사인 + 0.45·특징어 일치(정확 1, 포함 0.8, 부분 0.5).

## 토픽 분기·합류 정보량 (`backend/topics/info_flow.py`)

연구자 상세 화면의 "토픽 분기·합류 정보량" 패널이 쓰는 측정입니다. 공개 색인을 만들 때
`export_public_index.py`가 함께 계산하며, 공개되는 것은 창 단위 집계(토픽×토픽 질량,
엔트로피)뿐입니다. 논문 ID와 참고문헌 목록은 공개 JSON에 들어가지 않습니다.

**결합분포.** 논문을 `--window`년(기본 3년) 창으로 나눕니다. 인접 창 t, t+1에서 t+1의
논문 q마다 질량 1을 두고, 그 질량을 직전 창 토픽 a에 Σ_{p∈a} cos(R_p, R_q) 비율로
나눕니다(R = 참고문헌 집합, bibliographic coupling). 직전 창과 공유 참고문헌이 없는
논문은 ∅→토픽(신규)으로, 다음 창 어떤 논문과도 연결되지 않는 t의 논문은 토픽→∅(종료)로
셉니다. 이렇게 얻은 P(K_t, K_{t+1})에서:

| 측정 | 식 | 해석 |
|---|---|---|
| 분기 | H(K_{t+1} \| K_t) | 기원 토픽을 알아도 남는 후속 토픽의 불확실성. 0 = 일대일 계승, 1 bit = 두 갈래 균등 분기 |
| 합류 | H(K_t \| K_{t+1}) | 후속 토픽을 알아도 남는 기원의 불확실성. 클수록 여러 토픽이 하나로 모임 |
| 연속성 | I(K_t; K_{t+1}) | 두 창 사이에 보존된 토픽 구조. NMI = 2I / (H_t + H_{t+1}) |
| 정규화 분기·합류 | H(K_{t+1}\|K_t)/H(K_{t+1}), H(K_t\|K_{t+1})/H(K_t) | 0 = 완전 결정, 1 = 독립. 토픽 수가 다른 연구자 비교용 |
| 다양성 | H(K_t), 2^H | 창 안의 유효 토픽 수 |
| 이동 | JSD(P_t ‖ P_{t+1}) | 토픽 비중의 변화(연결과 무관한 구성 변화) |

항등식 H(K_{t+1}) = I + H(K_{t+1}|K_t), H(K_t) = I + H(K_t|K_{t+1})가 성립하므로,
후속 창의 토픽 다양성은 "계승된 부분(I)"과 "분기로 새로 생긴 부분"으로, 직전 창의
다양성은 "계승된 부분"과 "합류로 사라진 구분"으로 정확히 나뉩니다.

**추정과 검정.** 창 하나에 논문이 10–30편이라 plug-in 엔트로피는 아래로 치우칩니다.
Miller–Madow 보정((m−1)/2N nats)을 쓰고, 창 내부 논문 부트스트랩으로 95% 구간을 냅니다.
영가설은 **창 내부 토픽 라벨 순열**입니다. 두 창의 토픽 구성과 coupling 그래프는 그대로
두고 논문–라벨 대응만 섞어, 같은 구성·같은 표본 크기에서 나오는 기준값을 줍니다.
연도를 섞는 영가설은 모든 창에 토픽을 섞어 H(K_t)를 키우므로 관측값과 비교할 수 없어
쓰지 않습니다.

**한계.** 토픽 자체가 coupling 군집이므로 연속성은 구조적으로 양수이고 z가 크게 나옵니다.
z는 "우연 이상"의 근거일 뿐 효과 크기가 아닙니다. 연구자 간 비교는 정규화 값과
영가설 대비 차이로 합니다. 논문 5편 미만 창의 전이는 빈 원으로 표시하며 해석하지 않습니다.
창 폭은 결과에 영향을 주므로(3년 기본) 논문에 쓸 때는 2·4년으로 민감도를 함께 보고합니다.

```bash
python3 backend/topics/info_flow.py --alluvial data/topics/<slug>/alluvial.json \
    --seeds data/topics/<slug>/seeds.json --out data/topics/<slug>/info_flow.json --width 3
```
