# 저수량 연구자 전수점검 (2026-11-05)

공개 논문 30편 미만 연구자(1,510명)를 대상으로, OpenAlex author ID 매핑 실패·분할·과다 판정으로
빠진 논문을 회수한다. 키와 실명 해제 비밀번호는 환경변수로만 읽는다(`OPENALEX_API_KEY`,
`NAMES_PASSWORD`). 작업 폴더 `WORK`에는 `global/papers.jsonl`, `global/works.jsonl.gz`(공개 논문의
OpenAlex 레코드 캐시), `global/kept_counts.json`이 있어야 하며, 산출물은 `WORK/audit/`에 쓴다.

| 단계 | 스크립트 | 내용 |
| --- | --- | --- |
| 1 | `triage.py WORK` | 공개 논문 → 주 author ID → `authors/{id}` 단건(무료)으로 논문 수·소속 이력 대조 |
| 2 | `harvest.py WORK` | Crossref(무료)에서 한글 이름 로마자 변형(`romanize.py`)·공개 논문 저자 표기로 후보 수집, 저자 명단 정확 일치만 |
| 3 | `verify.py WORK` | 후보를 OpenAlex 단건으로 확인하고 규칙 적용(아래) |
| 4 | `finalize.py WORK` | 추가 가드 → `verified_audit.json`(자동 반영) / `review_audit.json`(검토) |
| 5 | `patch_release_verified_works.py --verified WORK/audit/verified_audit.json --public-ids WORK/audit/anon_audit.json` | 공개 릴리스 반영 |

인정 규칙(모두 만족): 학술지 유형, 연도 ≥ 박사-5; 한글 이름의 엄격한 로마자 일치(이니셜만인 표기 불가)
또는 공개 논문의 저자 표기와 일치하는 authorship이 정확히 하나; 분야가 전공 home field 또는 공개 논문의
15%(2편) 이상 분야; 경력 기관×구간(±1년, 현재 재직 기관은 마지막 비교수 구간 이후 전체 — 교수 명부가
최근 연도만 관측하므로) 또는 소속 없음 + 공개 논문과 공저자 ID 2개 이상 공유. 병원·의대 소속 authorship
제외. 공저자/ID로 연결된 묶음 중 공개 논문·박사/박사후 구간에 닿는 묶음(없으면 전체 80% 이상인 단일
묶음)만 자동 반영.

추가 가드(`finalize.py`): 의학·간호·보건·치의학·약학 분야는 자동 반영하지 않음; 암·종양·약리·독성 소분야는
공개 논문의 15% 이상일 때만; 비교수 구간에 연 6편 초과 추가는 동명 PI로 보고 전부 검토로.

결과(2026-11-05): 후보 140,828 DOI → 자동 642명 4,354편(공개 반영 3,454편; 기존 논문이 OpenAlex로 해석되지
않는 연구자는 주제 지도를 잃지 않도록 건너뜀) / 검토 313명 794편. 무작위 16명 표본 판독 정밀도 약 85–90%.
