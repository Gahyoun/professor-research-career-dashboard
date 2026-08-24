# Architecture

## Backend

백엔드는 배포 서버가 아니라 **연도별 정적 릴리스 생성 파이프라인**이다. 비공개 SQLite를 읽고 OpenAlex 역할·저널 지표를 보강한 다음 공개 최소 데이터만 만든다.

1. `prepare_release.py`: 비공개 DB에서 OpenAlex 저자 ID와 선택적 별칭 ID 목록을 추출한다.
2. `enrich_openalex_works.mjs`: 기본 저자 ID의 1저자·교신저자 여부, 저널 ID, 논문 인용수를 수집한다.
3. `enrich_openalex_alias_works.mjs`: 한 교수에게 연결된 추가 OpenAlex 저자 ID를 같은 방식으로 수집한다.
4. `fetch_openalex_sources.mjs`: 저널의 공개 2년 평균 인용도를 수집한다.
5. `build_release.py`: work ID 중복을 제거한 뒤 익명 ID, 경력구간, 연도별·저널별 집계, 공개 SQLite, 암호화 실명 번들을 생성한다.
6. `validate_release.py`: 무결성·개인정보·기관 풀네임·연속 연도축·JSON/SQLite 정합성과 표본 경력 회귀 검사를 수행한다.

캐시는 배치 파일 단위로 저장하므로 중단 후 같은 명령을 실행하면 완료된 배치를 건너뛴다.

## Frontend

프론트엔드는 GitHub Pages에서 동작하는 Vite/React 정적 앱이다. 서버나 비공개 DB에 연결하지 않고 `public/data/dashboard.json`만 읽는다.

- 기본 화면: 익명 교수 ID
- 개인 필터: 분야, 현재기관, 교수
- 잠금 해제 그룹 쿼리: 분야, 현재기관, 박사 출신기관·국가, 저널 영향도, 논문 수, 저널 수
- 경력: 박사과정, 기관별 포닥, 첫 교수기관(존재할 때), 현재기관
- 그래프: 연도별 주저자 논문을 저널 영향도 구간으로 누적 표시
- 그룹 비교: 일치 교수들을 실제 최소–최대 연도 공통축으로 그려 비교
- 실명·쿼리 잠금: 암호화 번들을 비밀번호로 브라우저 메모리에서만 복호화

## Release contract

`data/releases/YYYY/dashboard.json`의 형태는 연도와 무관하게 유지한다. 프론트엔드는 현재 릴리스만 복사한 `public/data/dashboard.json`을 읽으므로 2027년 DB 추가 때 화면 코드를 바꿀 필요가 없다.
