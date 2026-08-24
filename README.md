# Professor Research Career Dashboard

국내 기초자연과학 교수의 박사과정·포닥·교수 경력과 필터링된 주저자 논문 생산성을 보여주는 GitHub Pages 대시보드입니다. 개인 조회와 조건별 교수 그룹 조회를 모두 지원합니다.

## 구조

```text
backend/                 비공개 원본 DB를 읽는 수집·정규화·익명화 파이프라인
  cache/                 OpenAlex 재개용 캐시(커밋하지 않음)
  scripts/               연도별 릴리스 생성 도구
  sql/                   공개 SQLite 스키마와 예제 쿼리
frontend/                KRDS 기반 React 화면
data/releases/YYYY/      연도별 공개 릴리스 산출물
public/data/             현재 사이트가 읽는 JSON·암호화 실명 번들
public/downloads/        익명 SQLite·SQL 다운로드
```

공개 저장소에는 원본 DB, OpenAlex 키, 원본 OpenAlex 저자 ID, 내부 교수 ID, 평문 실명이 들어가지 않습니다. 실명은 PBKDF2-SHA256으로 키를 유도해 AES-GCM으로 암호화되며 브라우저에서만 복호화됩니다. 잠금 해제 전에는 익명 교수 ID만 보이고 그룹 쿼리도 비활성화됩니다.

## 화면 기능

- 개인 조회: `분야 → 현재 재직기관 → 교수(익명 Prof ID)` 순으로 선택
- 학력·경력: 학부 기관은 항목으로만 표시하고, 박사과정·기관별 포닥·교수 이동은 반기 단위 타임라인으로 표시
- 연도별 생산성: 빠진 해를 0으로 채운 연속 연도축에서 1저자 또는 교신저자 논문을 공개 저널 영향도 구간별로 표시
- 그룹 쿼리: 분야, 현재기관, 박사 출신기관·국가, 저널 영향도 M, 논문 N편, 서로 다른 저널 K개 조건을 조합
- 그룹 비교: 일치 교수 목록과 생산성을 그룹의 실제 최소–최대 연도 공통축으로 정규화해 비교
- 다운로드: 익명 공개 SQLite, 스키마, 예제 SQL

세부 판별 규칙은 [경력·기관·논문 분류 기준](docs/CLASSIFICATION_RULES.md), 데이터 구조는 [아키텍처](docs/ARCHITECTURE.md), 공개 범위는 [보안 문서](docs/SECURITY.md)를 참고합니다.

## 2027 데이터 추가

2027년 전체 DB를 만든 뒤 로컬에서 다음 파이프라인을 한 번 실행합니다. 동일 교수에게 추가 OpenAlex 저자 ID가 있으면 별도 비공개 JSON을 함께 넘깁니다.

```bash
export OPENALEX_API_KEY='...'
export NAMES_PASSWORD='...'
export AUTHOR_ALIASES_JSON='/absolute/path/to/openalex_author_aliases_2027.json' # 선택
./backend/scripts/update_release.sh 2027 /absolute/path/to/professor_affiliation_timeline_through_2027.sqlite
```

별칭 파일은 다음처럼 원본 명부의 교수 ID와 병합할 OpenAlex 저자 ID 배열을 갖습니다. 기본 ID와 겹쳐도 자동으로 제외되며, 저자 간 충돌은 빌드 오류로 중단됩니다.

```json
[
  {"source_professor_id":"원본-교수-ID","openalex_ids":["https://openalex.org/A123","https://openalex.org/A456"]}
]
```

`backend/cache/2027`은 재개용 비공개 캐시이며, `data/releases/2027`과 `public/`만 갱신됩니다. 같은 `.private/anon_salt.bin`을 보관하면 기존 교수의 익명 ID가 2027년에도 유지됩니다.

## 로컬 실행

```bash
pnpm install
pnpm dev
```

## 공개 지표

- 주저자: OpenAlex `author_position=first` 또는 `is_corresponding=true`
- 논문: 동명이인 필터에서 `keep` 판정이고, 저널에 실린 article/review/letter/editorial
- 저널 영향도: Clarivate JIF가 아닌 OpenAlex `summary_stats.2yr_mean_citedness`
- 기관명: OpenAlex/ROR 정규화 풀네임
- 동일 논문: 기본·보조 OpenAlex 저자 ID 사이에서 work ID 기준 한 번만 집계
