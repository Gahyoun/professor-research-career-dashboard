# 연구 토픽 흐름 (`#/topics`)

교수별 논문을 공유 참고문헌으로 클러스터링한 토픽을 연도·경력 시기 축에 배치하고, 영문 특징어와 의미 검색으로 여러 교수의 토픽을 같은 연도축에 비교한다.

## 화면

| 기능 | 내용 |
| --- | --- |
| 연구자·기관 검색 | 익명 ID·현재 기관·분야. 실명은 잠금 해제 후에만 검색 대상에 들어간다. |
| 토픽·키워드 검색 | 영문 질의, 한국어 질의는 용어집으로 영문 변환. 태그 일치(0.45)와 LSA 코사인(0.55)을 합산해 모든 연구자의 토픽을 순위화한다. |
| 단일 연구자 | 토픽 레인 × 연도(또는 경력 시기). 띠 두께 = 논문 수, 점선 = 모토픽 분기, NEW = 독립 신규, 회색 호 = ABA 경로. |
| 멀티 연구자 | 검색에 걸린 토픽을 **스택**(연구자별 레인) 또는 **오버랩**(연구자별 색 누적)으로 비교. |
| 논문 제목 | 실명 비밀번호로 잠금 해제한 뒤에만 연구자 화면의 "논문 목록"(토픽별 연도·제목·저널·DOI 링크)과 차트 툴팁에 표시. 연구자별 암호화 조각을 그 연구자를 열 때 받아 메모리에서만 복호화하고, 잠그면 지운다. PDF·SVG 내보내기에는 넣지 않는다. |
| 토픽 요약 | 토픽표에 Claude Code가 말뭉치(대표 논문의 제목·초록·출판일)로 쓴 한국어·영문 요약(주제, 시작 시기, 전개)을 표시. |

멀티 뷰의 토픽은 연구자마다 따로 클러스터링한 결과다. 같은 질의에 걸린 토픽을 같은 연도축에 놓은 비교이며, 전원을 다시 클러스터링한 공통 토픽축(`pipeline/scripts/build_multi.py`)과는 다르다.

## 공개 범위

전 인원 릴리스(`kstem-topic-alluvial/2`, `backend/topics/topic_batch.py export`)는 파일을 나눠 공개한다.

| 파일 | 내용 | 언제 읽나 |
| --- | --- | --- |
| `public/data/topics/index.json` | 익명 ID, 분야, 현재 기관, 경력 시기, 토픽(이름·특징어·base64 int8 LSA 벡터·탄생 연도·모토픽), `paper_cells` = `[연도, 토픽, 시기, 편수, 피인용 합]`, 공유 LSA 공간 | 페이지 진입 |
| `public/data/topics/detail/<익명 ID>.json` | 분기·합류 정보량(`info_flow.py`), 토픽별 요약 `{en, ko}` | 연구자 화면을 열 때 |
| `public/data/topics/titles/key.json`, `titles/<익명 ID>.json` | 논문 `{year, topic, title, venue, doi}`. 키 유도 값(PBKDF2-SHA256 600,000회)은 한 번, 연구자별 AES-256-GCM 조각(AAD `topic-titles-v2`) | 잠금 해제 후 연구자 화면을 열 때 |

- **논문 제목·DOI·실명·professor_uid·work ID 없음** — 내보내기가 공개 색인에서 이 키를 발견하면 쓰기를 거부하고, `normalizeTopicIndex`도 제목 필드를 발견하면 로딩을 거부한다.
- 잠금 해제 시 키를 한 번만 유도해 메모리(추출 불가 CryptoKey)에 두고, 연 연구자의 제목 조각만 내려받아 복호화한다. 이전 형식의 단일 `encrypted_titles.json`도 읽는다.
- `source: "demo"`인 색인은 화면에 "예시 데이터" 표시가 붙는다(`backend/topics/make_demo_index.py`). `method.recip = "not_computed"`이면 ABA 경로 표시를 숨긴다(전 인원 릴리스는 피인용 표본을 수집하지 않는다).

## 데이터 만들기 (전 인원)

비공개 원본 DB가 있는 환경에서 실행한다. 단계마다 결과를 저장하므로 중간에 끊겨도 같은 명령으로 이어서 하고, 입력이 바뀐 연구자만 다시 계산한다.

```bash
pip install -r backend/topics/pipeline/requirements.txt cryptography

export OPENALEX_API_KEY=...      # 선택: OpenAlex 한도 상향
export NAMES_PASSWORD=...        # 제목 조각 암호화

python3 backend/topics/topic_batch.py all --year 2026   # works → fetch → cluster → corpus
# Claude Code(이 저장소 폴더)에서:  /topic-summaries
python3 backend/topics/topic_batch.py export
```

원본 DB 경로는 `backend/cache/YEAR/source_db_path.txt`(릴리스 파이프라인이 기록) 또는 `--source-db`, 익명 ID 솔트는 `.private/anon_salt.bin`을 쓴다.

| 단계 | 하는 일 | 저장 위치 (커밋 금지) |
| --- | --- | --- |
| `works` | `work_authorship_evidence`에서 `keep` 판정 + KOAD `namesake_paper` 전부 제외 + phd_year−5 ≤ 연도 ≤ 릴리스 연도 논문(저자 순서 무관, `build_research_areas.py`와 같은 규칙). 공개 모집단에 있는 익명 ID만 | `.private/topics_YEAR.sqlite` |
| `fetch` | OpenAlex에서 참고문헌·초록·제목·출판일을 50편씩 OR 필터로 수집, 병합된 ID는 개별 조회로 보완 | `backend/cache/YEAR/topic_works.sqlite` |
| `cluster` | 연구자별 공유 참고문헌 코사인 가중 Louvain(공유 ≥2편, resolution 1.05). `--min-size`(기본 3)편 미만 군집은 연구자당 하나의 `Other` 토픽으로 묶는다. 영문 c-TF-IDF 이름·특징어, 모토픽, 분기·합류 정보량 계산 | 토픽 DB |
| `corpus` | 아직 요약이 없는 토픽마다 말뭉치 한 건: 특징어, 활동 기간, 연도별 편수, 출판일 순 대표 논문(활동 기간을 세 구간으로 나눠 구간마다 TF-IDF 중심에 가까운 논문, 최대 10편)의 날짜·제목·초록 발췌. 20건씩 청크 번호를 붙인다(`--chunk-size`) | 토픽 DB `summary_corpus` |
| Claude Code `/topic-summaries` | 세션이 청크를 읽고 직접 영문·한국어 요약을 써서 제출 | 토픽 DB `summaries` |
| `export` | 공유 LSA 공간을 만들고 위 공개 파일을 쓴다 | `public/data/topics` |

토픽 DB의 주요 테이블: `researcher_works`(연구자–논문), `topics`(토픽 이름·특징어·크기·모토픽·구성 해시), `topic_members`(토픽–논문), `researcher_runs`(입력 해시·경력 시기·정보량), `summary_corpus`(요약할 말뭉치), `summaries`(구성 해시별 요약과 상태).

**Claude Code가 말뭉치로 요약하기.** 파이썬은 모델을 부르지 않는다. 말뭉치를 DB에 쌓아 두면 Claude Code 세션이 `.claude/skills/topic-summaries`(슬래시 명령 `/topic-summaries`)의 절차대로 `backend/topics/topic_corpus.py`를 써서 작업한다.

```bash
python3 backend/topics/topic_corpus.py status            # 진행률과 남은 청크 번호
python3 backend/topics/topic_corpus.py rules             # 요약 규칙
python3 backend/topics/topic_corpus.py next --chunk 12   # 청크 12의 남은 토픽 말뭉치
python3 backend/topics/topic_corpus.py submit - <<'JSONL'
{"id": "<토픽 id>", "en": "...", "ko": "..."}
JSONL
```

`submit`은 두 언어가 모두 있고 논문 제목을 옮기지 않은 요약만 저장하고, 거부한 id를 알려 준다(다시 써서 제출). `next`는 아직 요약이 없는 토픽만 보여 주므로 같은 청크를 두 번 열어도 문제없고, 청크 번호 구간을 나눠 하위 에이전트나 여러 세션이 동시에 작업할 수 있다. 중간에 멈춰도 저장된 요약은 남고, `corpus`를 다시 돌리면 요약된 토픽은 빠진다.

**요약 규칙.** 말뭉치에는 실명·익명 ID·기관이 없다(특징어, 기간·연도별 편수, 대표 논문 날짜·제목·초록 발췌만). 요약은 무엇을 연구했는지와 언제 시작해 어디로 옮겨 갔는지를 쓴다. 요약은 구성 논문 집합의 해시에 묶여 있어, 다시 클러스터링해도 구성이 같으면 다시 쓰지 않는다. 요약이 논문 제목 전체(8단어보다 긴 제목은 연속 8단어)를 그대로 담으면 저장하지 않는다(`rejected_title_overlap`). 분야 용어 수준의 짧은 구절 겹침은 허용한다 — 제목은 잠금 해제 뒤에만 보이므로 요약으로 제목이 새면 익명성이 깨진다. 요약 규칙(`SUMMARY_SYSTEM`)이나 말뭉치 형식을 바꾸면 `PROMPT_VERSION`을 올린다 — 이전 버전 요약은 새 요약이 생길 때까지 공개된다.

**무인 실행 대안.** 사람이 세션을 지켜보지 않고 돌리려면 `topic_batch.py summarize`가 같은 말뭉치 문장을 토픽마다 `claude -p`(기본, `--cli-workers`, 사용량 한도 시 대기 후 재시도) 또는 Message Batches API(`--engine api`, ANTHROPIC_API_KEY)로 보낸다. `--dry-run`, `--limit N`, `--model`, `--effort` 옵션이 있다.

**개별 연구자 정밀 파이프라인.** `backend/topics/pipeline`(대표 논문으로 저자 ID 역추적 → 판별 → 토픽 → 라벨 → 분기, `--citers`로 ABA 경로 포함)과 `export_public_index.py`는 한 사람씩 사람이 라벨을 고쳐 가며 만드는 기존 절차로 남겨 둔다. 두 경로의 군집·분기 계산은 `pipeline/scripts/topics.py`의 `cluster`와 `branching.py`의 `parent_links`를 함께 쓴다.

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
