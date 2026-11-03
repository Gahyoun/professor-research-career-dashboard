# 연구 토픽 흐름 (`#/topics`)

교수별 논문을 공유 참고문헌으로 클러스터링한 토픽을 연도·경력 시기 축에 배치하고, 토픽 태그(한/영)와 의미 검색으로 여러 교수의 토픽을 같은 연도축에 비교한다.

## 화면

| 기능 | 내용 |
| --- | --- |
| 연구자·기관 검색 | 익명 ID·현재 기관·분야. 실명은 잠금 해제 후에만 검색 대상에 들어간다. |
| 토픽·키워드 검색 | 한국어·영어 질의. 태그 일치(0.45)와 LSA 코사인(0.55)을 합산해 모든 연구자의 토픽을 순위화한다. |
| 단일 연구자 | 토픽 레인 × 연도(또는 경력 시기). 띠 두께 = 논문 수, 점선 = 모토픽 분기, NEW = 독립 신규, 회색 호 = ABA 경로. |
| 멀티 연구자 | 검색에 걸린 토픽을 **스택**(연구자별 레인) 또는 **오버랩**(연구자별 색 누적)으로 비교. |
| 논문 제목 | `encrypted_titles.json`이 있으면 잠금 해제 후 툴팁에 제목·저널·DOI 표시. |

멀티 뷰의 토픽은 연구자마다 따로 클러스터링한 결과다. 같은 질의에 걸린 토픽을 같은 연도축에 놓은 비교이며, 전원을 다시 클러스터링한 공통 토픽축(`pipeline/scripts/build_multi.py`)과는 다르다.

## 공개 범위

- `public/data/topics/index.json`: 익명 ID, 분야, 현재 기관, 경력 시기 라벨, 토픽 라벨·태그·특징어·LSA 벡터, 논문별 `{year, topic, era, cited}`, ABA 쌍의 연도·토픽. **논문 제목·DOI·실명 없음** — `normalizeTopicIndex`가 제목 필드를 발견하면 로딩을 거부한다.
- `public/data/topics/encrypted_titles.json`: `{anon_id: [{year, topic, title, venue, doi}]}`를 `encrypted_names.json`과 같은 방식(PBKDF2-SHA256 600,000회 → AES-256-GCM, AAD `topic-titles-v1`)으로 암호화.
- `source: "demo"`인 색인은 화면에 "예시 데이터" 표시가 붙는다. 현재 저장소의 색인은 `backend/topics/make_demo_index.py`로 만든 합성 데이터다.

## 데이터 만들기

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

## 태그와 검색

- **특징어(keywords)**: 커뮤니티(토픽) 하나를 문서 하나로 합친 c-TF-IDF. 커뮤니티의 60% 이상에 나오는 말은 먼저 제외한다(`topic_semantics.ctfidf_terms`).
- **태그(tags)**: 사람이 붙인 라벨을 `·`로 나눈 조각 + 특징어 + `tag_glossary.json`의 한↔영 대응. 한국어·영어 어느 쪽으로도 검색된다. 용어집은 자유롭게 늘린다.
- **의미 검색**: 전체 연구자의 논문(제목·초록·OpenAlex 토픽/키워드)을 하나의 TF-IDF→SVD(LSA) 공간에 넣고, 토픽 중심 벡터와 단어 벡터를 int8로 색인에 넣는다. 차원은 문서 수의 절반 이하. 브라우저는 질의 단어 벡터 평균과 토픽 벡터의 코사인만 계산한다. 한국어 질의는 용어집으로 영어 항으로 확장된 뒤 LSA에 들어간다.
