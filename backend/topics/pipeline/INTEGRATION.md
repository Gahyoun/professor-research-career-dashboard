# 기존 동명이인 판별기·기관 데이터와 합치기

이미 OpenAlex 동명이인 판별기와 기관 정보 데이터를 가지고 있다면, 이 파이프라인의
`disambiguate.py` 를 떼어내고 그 자리에 끼우면 된다. 고칠 파일은
`adapters/external_disambiguator.py` 하나이고, 그 안의 TODO 두 함수가 전부다.

## 1. 계약 (contract)

파이프라인의 하위 단계가 읽는 것은 논문당 다음 필드뿐이다. 이것만 채우면 어떤 판별기든
붙는다.

| 필드 | 뜻 | 없으면 |
|---|---|---|
| `id` | OpenAlex work id (전체 URL) | 중복 제거·인용 연결 불가 |
| `title`, `publication_year` | | 시계열 배치 불가 |
| `referenced_works` | 직접 참고문헌 id 목록 | **클러스터링 자체가 불가** |
| `eras` | 시기 라벨 목록 (예: `["KIAS (2015-18)"]`) | 가로축 배치 불가 |
| `era_idx` | 그 라벨들의 인덱스. 배치는 `max(era_idx)` 를 쓴다 | 〃 |
| `cited_by_count` | 버전 대표 선택과 보고용 | 대충 돌아감 |
| `primary_location.source.display_name` | 저널명. preprint·비논문 판정용 | 〃 |

`seeds.json` 전체 모양:

```json
{"name": "...", "author_ids": ["A5XXXXXXXXX"],
 "eras": ["기관 A (~2010)", "기관 B (2011-13)", "..."],
 "works": [{"id": "https://openalex.org/W...", "title": "...", "publication_year": 2012,
            "referenced_works": ["https://openalex.org/W...", "..."],
            "eras": ["기관 B (2011-13)"], "era_idx": [1], "cited_by_count": 38,
            "primary_location": {"source": {"display_name": "Physical Review Letters"}}}]}
```

`referenced_works` 는 판별기가 들고 있지 않을 가능성이 크다. `fetch_works.py` 가 받아둔
`works.json` 에 있으므로, 어댑터는 **판별 결과(id 목록 또는 점수)** 만 외부에서 받고
본문은 `works.json` 에서 가져온다. 어댑터가 두 파일을 모두 받는 이유다.

## 2. 판별 결과 붙이기 (TODO 1)

`load_verdicts()` 가 `{work_id: bool}` 을 돌려주면 된다. 기억할 것 세 가지.

**id 정규화.** `W2059161157`, `openalex.org/W2059161157`, 전체 URL이 섞여 들어온다.
어댑터는 전부 `https://openalex.org/W...` 로 맞춘다. 여기서 틀어지면 조용히 0편이 나온다.

**점수형이면 임계값을 여기서 고정하고 적어둔다.** 임계값은 결과를 바꾸는 파라미터이므로
README 나 이 문서에 값과 근거를 남긴다. 나중에 "왜 이 논문이 빠졌나"는 반드시 나온다.

**판정이 없는 레코드를 버리지 말고 보고한다.** 판별기 입력 범위와 `fetch_works.py` 수집
범위가 다르면 차집합이 생긴다. 어댑터는 이것을 `판별기에 판정이 없는 레코드` 로 찍어준다.
이 목록이 길면 author ID 회수가 덜 된 것이다 — `--seed-title` 을 늘린다.

## 3. 기관 데이터로 시기 만들기 (TODO 2)

`load_eras()` 가 `[{label, start, end, ror, match, exclude}]` 를 연도순으로 돌려준다.
배정 우선순위는 어댑터가 이미 구현해 두었다.

1. **ROR id 일치** — 가장 정확. 기관 데이터에 ROR 이 있으면 반드시 쓴다.
2. **소속 원문 정규식** — ROR 이 없거나 OpenAlex 가 기관을 못 붙인 논문용.
3. **출판연도가 구간에 들어감** — 근거가 약하다. `era_evidence: "year-only"` 로 표시되고
   기본값에서는 제외된다. `--keep-year-only` 로 포함할 수 있지만, 포함했다면 보고한다.

세 가지 함정이 있다.

**ROR 만 믿으면 안 된다.** OpenAlex 의 `institutions` 는 정규화·추정값이고, 공저자의
소속이 본인 authorship 에 붙어 들어오는 사례가 실제로 있었다. ROR 일치가 나와도
소속 원문과 어긋나면 사람이 본다. 반대로 소속 원문만 믿으면 기관명 표기가 바뀐 시기를
놓친다. 둘을 같이 쓰되 우선순위를 고정하는 것이 어댑터의 역할이다.

**구간이 겹친다.** 겸직·방문·이직 직후 이중 소속은 정상이다. 겹치는 구간을 억지로
하나로 만들지 말고 `era_idx` 에 둘 다 담아둔다. 가로축 배치는 `max(era_idx)`(= 더 나중
소속)를 쓰므로, 과도기 논문이 다음 시기 칸에 놓인다. 이 규칙이 싫으면
`branching.py` 의 `max(w["era_idx"])` 한 줄만 바꾸면 된다.

**같은 기관, 다른 학과.** 기관 단위 데이터로는 못 거른다. 실제 사례: 본인은 기관 A
물리학과(2004–2010), 동명이인은 기관 A **기계공학과**(2005, 2008). 기관도 연도도 겹친다.
그 시기 era 에 `exclude: "Mechanical Engineering"` 을 넣는다. 기관 데이터에 학과 필드가
있다면 `match` 를 학과까지 포함해 만들면 더 깔끔하다.

## 4. 두 판별기를 함께 쓰기

기존 판별기와 이 저장소의 소속 연속성 규칙은 서로를 검증하는 데 쓸 수 있다. 둘 다 돌려
교차표를 찍는 것을 권한다.

```bash
python3 scripts/disambiguate.py --works works.json --timeline timeline.json --out seeds.rule.json
python3 adapters/external_disambiguator.py --works works.json \
    --verdicts verdicts.json --institutions institutions.json --out seeds.ext.json
python3 - <<'PY'
import json
A={w["id"] for w in json.load(open("seeds.rule.json"))["works"]}
B={w["id"] for w in json.load(open("seeds.ext.json"))["works"]}
print(f"둘 다 채택 {len(A&B)} / 규칙만 {len(A-B)} / 판별기만 {len(B-A)}")
PY
```

불일치가 전부 검수 대상이다. 경험상 불일치의 대부분은 **소속 결측 레코드**(학회 초록,
기관 리포지토리, 일부 preprint)이고, 그 다음이 **저자 레코드 분리**다. 둘 다 판별기
성능 문제가 아니라 OpenAlex 데이터 품질 문제이므로, 판별기를 고치기 전에 어느 쪽인지
먼저 가른다.

## 5. 판별 결과를 데이터로 남기기

사이트에 그림만 올리면 아무도 검증할 수 없다. 연구자별 디렉터리에 다음을 같이 둔다.
`build_site.py` 는 `alluvial.json` 을 자동으로 복사한다.

- `alluvial.json` — 최종 입력 데이터 (논문·토픽·분기·상호쌍)
- `cleaning-report.md` — 무엇을 왜 뺐는지 (`disambiguate.py --report`)
- `timeline.json` / `institutions.json` — 시기 정의 그 자체

정제 단계에서 버린 것을 숨기지 않는 것이 이 작업의 신뢰성 전부다.
