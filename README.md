# Professor Research Career Dashboard

국내 기초자연과학 교수 명부를 바탕으로 학력·경력의 겹침과 이동, 필터링된 주저자 논문 생산성을 탐색하는 GitHub Pages 대시보드입니다. 흰 바탕의 연구자 별자리, 학부→박사→현재기관 흐름, 기관별 시간 변화와 기존 개인 경력 조회를 제공합니다.

비밀번호를 입력하기 전에는 익명 연구자 ID로 탐색합니다. 실명은 기존 암호화 번들을 브라우저 메모리에서 복호화한 뒤 표시합니다. 이번 화면 확장은 기존 공개 릴리스와 암호화 실명 번들을 변경하지 않고, 검증된 보조 메타데이터를 선택적으로 결합합니다.

## 화면

| 경로 | 탐색 내용 |
| --- | --- |
| `#/constellations` | 학교별 출신기관 집합 또는 연구자별 학창·포닥·첫 조교수·현직 집합. 단계별 색상과 겹친 기간·구성원 근거를 함께 봅니다. 연구자 이름·익명 ID에는 현직 기관을 표시합니다. |
| `#/flows` | 학부→박사→현재기관의 3단계 Sankey와 학부 모교 재직 비율. 흐름을 선택해 구성원을 좁힙니다. |
| `#/institutions` | 같은 학기의 실제 명부를 비교해 기관별 관측 인원·소속 변경·박사 출신 구성을 분모와 누락 범위까지 확인합니다. |
| `#/career` | 기존 개인 경력·논문 생산성 조회, 잠금 해제 후 조건별 그룹 비교와 익명 자료 다운로드를 제공합니다. |

이 자료는 **현재 교수 명부에서 과거를 재구성한 표본**입니다. 과거 각 기관의 전체 인력이나 실제 교류망이 아닙니다. 연구자 생애 집합은 국내외 모두 학교와 해당 단계의 학과를 맞추며 포닥 단계만 기관 단위로 묶습니다. 현재 재직 학과를 박사 학과로 대체하지 않습니다. 추정 시기·논문 소속에서 추론한 학과와 관측된 교수 재직 근거는 화면에서 구분합니다.

사용법과 해석 범위는 [별자리·흐름·기관 변화](docs/CONSTELLATIONS_AND_FLOWS.md), 임베딩과 가중치는 [하이퍼그래프 방법](docs/HYPERGRAPH_METHOD.md)을 참고합니다. OpenAlex·ORCID·국가연구자번호의 비공개 대조 절차와 GNU의 KRI 기관 연계 확인 사항은 [연구자 식별자 연계](docs/IDENTITY_LINKAGE.md)에 정리했습니다.

## 구조

```text
backend/                 비공개 원본 DB를 읽는 수집·정규화·익명화 파이프라인
  cache/                 OpenAlex 재개용 캐시(커밋하지 않음)
  scripts/               연도별 릴리스 생성 도구
  sql/                   공개 SQLite 스키마와 예제 쿼리
frontend/                KRDS 기반 React 화면
data/releases/YYYY/      연도별 공개 릴리스 산출물
public/data/             현재 공개 JSON·보조 메타데이터·암호화 실명 번들
public/downloads/        익명 SQLite·SQL 다운로드
```

세부 판별 규칙은 [경력·기관·논문 분류 기준](docs/CLASSIFICATION_RULES.md), 데이터 구조는 [아키텍처](docs/ARCHITECTURE.md), 공개 범위는 [보안 문서](docs/SECURITY.md)를 참고합니다.

## 로컬 실행과 검증

Node.js 22.13 이상, pnpm, Python 3가 필요합니다.

```bash
pnpm install
pnpm dev
```

공개 전에는 다음 검사를 모두 실행합니다.

```bash
pnpm test
pnpm lint
pnpm typecheck
pnpm data:test
pnpm build
```

## 연도별 데이터와 메타데이터 갱신

다음 연도의 원본 DB를 준비하고, 비공개 환경에서 `OPENALEX_API_KEY`와 `NAMES_PASSWORD`를 설정한 뒤 기존 릴리스 파이프라인을 실행합니다. 아래 변수는 각자의 비공개 경로를 가리키며 값과 원본 자료를 저장소에 기록하지 않습니다.

```bash
./backend/scripts/update_release.sh 2027 "$SOURCE_DATABASE"
```

추가 OpenAlex 저자 ID가 있으면 `AUTHOR_ALIASES_JSON`으로 비공개 별칭 파일을 지정할 수 있습니다. `backend/cache/YYYY`는 커밋하지 않는 재개용 캐시입니다. 기존 `.private/anon_salt.bin`을 유지해야 같은 연구자의 익명 ID가 이어집니다.

보조 메타데이터는 해당 연도 공개 JSON을 먼저 생성한 뒤 별도로 재생성합니다. 정확한 명령과 선택적 학위 검증 DB 결합 절차는 [메타데이터 갱신](docs/CONSTELLATIONS_AND_FLOWS.md#메타데이터-갱신)을 따릅니다. 국내·해외 박사학위논문 후보는 [RISS API와 상세 학위기록 검토](docs/RISS_DEGREE_VERIFICATION.md)로 검색하고, [비공개 학위–논문 DB](docs/THESIS_LINKAGE.md)에 출처와 검토 상태를 저장합니다. 공개 JSON과 보조 JSON의 SHA-256이 manifest와 모두 일치할 때만 화면이 보조 정보를 사용합니다.

## 공개 지표

- 주저자: OpenAlex `author_position=first` 또는 `is_corresponding=true`
- 논문: 동명이인 필터에서 `keep` 판정이고, 저널에 실린 article/review/letter/editorial
- 저널 영향도: Clarivate JIF가 아닌 OpenAlex `summary_stats.2yr_mean_citedness`
- 기관명: OpenAlex/ROR 정규화 풀네임
- 동일 논문: 기본·보조 OpenAlex 저자 ID 사이에서 work ID 기준 한 번만 집계
