# OpenAlex 사용 메모

## 예산

키 없이 쓰면 **IP당 하루 $0.10을 공유**하고 요청당 약 $0.001이다. 하루 100회 남짓이
실질 한도이고, 같은 네트워크의 다른 사람과 나눠 쓴다. 전체 파이프라인은 한 연구자당
20–30회면 끝나도록 설계돼 있다.

- `fetch_works.py`: 대표 논문 수 + 논문 200편당 1회 (보통 3–5회)
- `disambiguate.py`, `topics.py`, `render_alluvial.py`: 호출 없음
- `branching.py --citers`: 시드 25편 묶음당 1–3회 (보통 5–10회)
- `connectivity_probe.py --depth2`: 1차 조상 100편당 1회 (13회 전후)

모든 스크립트가 `--cache` 디렉터리에 응답을 저장하므로 재실행은 공짜다.
키가 필요하면 `POST https://api.openalex.org/api-keys` 에 사용자 이메일을 보내면
확인 링크가 간다(하루 $1). 사용자 동의 없이 이메일을 보내지 말 것.

## 필요한 필드

```
id,doi,title,publication_year,cited_by_count,referenced_works,
authorships,primary_location,topics,type
```

`referenced_works` 가 핵심이다. 이것이 들어 있으면 **한 번 받은 논문에서 다음 층의
노드 ID를 공짜로 얻는다**. 그래서 깊은 인용망도 "메타데이터를 받을 노드만 고르는"
문제로 바뀐다.

`authorships[].raw_affiliation_strings` 는 동명이인 판별의 유일한 근거다.
`institutions` 는 OpenAlex가 정규화·추정한 값이라 다른 저자의 소속이 섞여 들어오는
경우가 있다(실측: 공저자의 소속이 본인 authorship에 붙은 사례 다수). 원문을 본다.

## 묶음 질의

- ID 조회: `filter=openalex_id:W1|W2|...` — 한 번에 **100개**
- 피인용: `filter=cites:W1|W2|...` — OR 지원됨. 결과는 합집합이라 어느 시드를 인용했는지는
  안 나오지만, 받은 논문의 `referenced_works` 로 역산하면 된다
- 제목 검색: `filter=title.search:...` (URL 인코딩)
- 정렬: `sort=cited_by_count:desc` — 발산하는 집합을 상위부터 표본 추출할 때

페이지는 `per-page=200` 이 최대. 200 미만이 오면 마지막 페이지다.

## 알아둘 함정

- **저자 레코드 분리**: 같은 사람이 여러 author ID로 갈린다. 대표 논문을 시기·공저자가
  다른 것으로 2–3편 넣어 ID를 모두 회수한다.
- **소속 결측**: 학회 초록, 기관 리포지토리 레코드, 일부 preprint는 authorship에 소속이
  없다. 자동 탈락하므로 공저자 기반으로 따로 건져 사람에게 확인받는다.
- **커버리지**: 국내 학회지·단행본·학위논문은 수록이 불균일하다. 한국어 저널은 제목이
  영문으로만 올라오는 경우가 많아 제목 검색이 실패할 수 있다.
- **`type` 필드를 믿지 말 것**: 초록과 논문이 같은 `article` 로 들어오는 경우가 있다.
  저널명(`primary_location.source.display_name`)으로 거르는 편이 정확하다.
