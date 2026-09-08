# 연구자 식별자 연계

확인일: 2026-09-08. OpenAlex 논문·소속 이력은 동일인 매칭의 근거이며 계정 소유자의 본인인증을 수행하지 않는다. 연구자 식별자를 확인해도 실제 박사 학과나 입학연도가 확인되는 것은 아니다.

## 식별자와 기관 연계

OpenAlex author ID는 알고리즘으로 묶인 저자 프로필을 가리킨다. ORCID는 외부 연구자 식별자이며, 국가연구자번호는 별도 체계다. 이들을 원본 명부의 내부 교수 ID에 연결하는 비공개 표를 둔다. 한 사람에게 OpenAlex ID가 여러 개 있을 수 있고, 한 OpenAlex ID가 서로 다른 명부 행에 잘못 연결되어 있을 수도 있으므로 일대일 대응을 가정하지 않는다. [OpenAlex 공식 저자 문서](https://help.openalex.org/data/authors/)

IRIS/NRI는 기존 NTIS·KRI 연구자번호를 국가연구자번호 체계로 통합하는 절차를 제공한다. 그러나 2025 KRI 매뉴얼에는 KRI와 IRIS에 서로 다른 번호가 있는 경우의 통합 절차도 명시되어 있다. 두 체계의 번호가 항상 같다고 가정하지 않는다. 번호를 문자열로 저장해 앞자리 0을 보존하고, 과거 KRI 연구자등록번호는 출처와 체계를 별도로 표시한다. KRI 로그인 ID나 인증 토큰을 연구자 식별자로 저장하지 않는다. [IRIS 공식 통합 안내](https://www.iris.go.kr/contents/retrieveNoticeView.do?blbdId=00000001&blltSeq=362), [2025 KRI 매뉴얼 공지](https://www.kri.go.kr/kri/rp/bbs_new/PG-RP-201-04jr.jsp?bbsseq=651&cntGbn=upCnt&go=1&idx=250200064)

2016년 KRI 연계 안내와 샘플은 기관용 웹 인터페이스다. 아래 항목은 당시 문서에서 확인한 것으로, 현재 기관별 계약과 서비스 활성화 범위는 담당 부서에 확인해야 한다.

- 연구업적 검증 URL은 논문 등의 업적 검증을 위한 것이며 연구자 계정의 본인인증 API가 아니다.
- 연구자 검색 팝업은 기관 ID·기관 인증번호·반환 URL을 요구하며, 선택 결과로 연구자명과 연구자등록번호를 돌려준다.
- 입력 연계는 기관 정보 및 암호화된 연구자등록번호를 이용한다. 입력 서비스에 데이터를 전송하는 동작은 이 프로젝트에서 구현하지 않았다.
- 승인된 기관의 연계가 존재하더라도 다른 연구용 웹서비스나 타 기관 연구자 전체에 대한 조회·저장 권한을 자동으로 뜻하지 않는다.

[한국연구재단 연계API 공지 및 첨부 샘플](https://www.kri.go.kr/kri/rp/bbs_new/PG-RP-201-04jr.jsp?bbsseq=651&cntGbn=upCnt&go=1&idx=160100057), [2025 KRI·NRI 매뉴얼 공지](https://www.kri.go.kr/kri/rp/bbs_new/PG-RP-201-04jr.jsp?bbsseq=651&cntGbn=upCnt&go=1&idx=250200064)

## 비공개 registry

`researchers`는 원본 교수 ID와 기존 공개 익명 ID를 연결한다. `openalex_author_links`는 원본의 기본·보조 저자 ID를 보존한다. `researcher_identifier_links`는 국가연구자번호·과거 KRI 번호·ORCID 후보와 검토 결과를 저장한다. 테이블 정의는 `backend/scripts/identity_registry_schema.sql`에 있다.

원본의 저자 연결은 가져온 주장으로 취급한다. 국가연구자번호를 추정하거나 생성하지 않는다. 서로 다른 원본 교수 ID가 같은 외부 식별자를 공유하면 관련 행을 모두 충돌 대상으로 남기며, 자동으로 한 사람을 선택하거나 명부 행을 병합하지 않는다. 기본 OpenAlex ID와 보조 ID를 합쳐 충돌을 검사한다.

식별자 연결은 `candidate`, `accepted`, `rejected`, `conflict` 상태로 나눈다. `accepted`는 출처를 검토한 동일인 연결을 뜻하며 본인인증 완료를 뜻하지 않는다. 실제 학위 학과 검증은 기존 학위 검증 DB에서 별도로 수행한다.

검토자는 저자 자신이 해당 논문의 어느 저자인지와 상충 근거가 없는지 확인해야 한다. 이름·논문 제목·DOI 하나의 일치로 확정하지 않는다. 독립적으로 대조한 ORCID 일치, 또는 서로 다른 논문 DOI 두 개 이상과 기관·시기 일치를 검토 근거로 요구한다. 이것은 이 프로젝트의 보수적 검토 기준이며, 정확도를 보장하는 통계적 판정 규칙이 아니다. 동일 논문의 공동저자들은 DOI를 공유하므로 저자 단위 대조가 필수다. 같은 원본 DB의 ORCID나 `keep` 판정을 반복해서 읽는 것은 독립 검증이 아니다.

검토 결과에는 공식 출처 URL, 확인일, 검토자, 구조화된 근거를 함께 저장한다. 코드의 형식·중복 검사는 출처를 직접 읽는 검토를 대신하지 않는다. 이미 채택된 식별자가 다른 연구자에게 다시 채택되거나, 한 연구자에게 같은 체계의 서로 다른 식별자가 동시에 채택되는 것을 거부한다.

국가연구자번호·과거 KRI 번호에는 `evidence.registry_observation`도 요구한다. 공식 기록에서 관측한 번호와 체계가 제출값과 정확히 같아야 하며, 공식 출처 URL과 비공개 검토 기록 참조를 남긴다. 로그인 후 확인하는 기록에는 공개 고유 URL이 없을 수 있으므로 검토 기록 참조를 함께 사용한다. 논문 저자의 일치와 특정 연구자번호의 관측을 별도로 확인하는 절차다.

registry는 `.private` 또는 `private` 디렉터리 아래에서만 만들고 파일 권한 0600, 전용 디렉터리 권한 0700을 사용한다. 이미 존재하는 DB를 초기화로 덮어쓰지 않는다. 일괄 수입 중 오류가 생기면 그 수입 전체를 되돌린다. CLI는 인원과 상태별 건수만 출력하며, 실제 식별자·원본 ID·ORCID는 로그에 출력하지 않는다. 공개 JSON·CSV·다운로드 DB·프런트엔드에는 이 registry를 포함하지 않는다.

2026년 원본을 대조한 초기 자료는 연구자 3,937명, OpenAlex 연결 3,489개, ORCID 연결 2,904개다. 기본·보조 ID를 합친 OpenAlex 충돌은 23그룹, ORCID 충돌은 18그룹이다. 충돌은 중복 명부와 오매칭 가능성을 모두 포함하며 오류로 확정한 수가 아니다. 모든 자료는 원본의 연결 주장 또는 검토 후보이며, 확인된 국가연구자번호·KRI 번호는 아직 없다.

## 작업 순서

기존 비공개 빌드 프로젝트와 익명화 salt를 사용한다. `PRIVATE_BUILD_PROJECT`와 `PRIVATE_DIRECTORY`는 운영자가 설정한 비공개 경로이며, `PRIVATE_DIRECTORY`에는 `private` 또는 `.private` 경로 요소가 있어야 한다.

```bash
python3 backend/scripts/build_identity_seed.py \
  --private-project "$PRIVATE_BUILD_PROJECT" \
  --public-data public/data/dashboard.json \
  --year 2026 \
  --output "$PRIVATE_DIRECTORY/identity-seed.json"

python3 backend/scripts/identity_registry.py init \
  --seed-json "$PRIVATE_DIRECTORY/identity-seed.json" \
  --output "$PRIVATE_DIRECTORY/researcher-identity.sqlite"

python3 backend/scripts/identity_registry.py import \
  --database "$PRIVATE_DIRECTORY/researcher-identity.sqlite" \
  --records-json "$PRIVATE_DIRECTORY/reviewed-identifiers.json"

python3 backend/scripts/identity_registry.py summary \
  --database "$PRIVATE_DIRECTORY/researcher-identity.sqlite"
```

보조 OpenAlex 연결 파일을 포함하려면 seed 생성기에 `--author-aliases`를 명시한다. 원본 교수 ID가 명부에 매핑되지 않는 보조 기록이나 잘못된 형식의 식별자는 private 감사 파일로 분리한다. 식별자에 출처가 있다는 것과 동일인 확인 완료는 구별한다.

검토 입력 파일은 식별자 기록의 JSON 배열이다. 각 기록에는 다음 필드를 둔다. 실제 값이 든 예시 파일은 저장소에 커밋하지 않는다.

| 필드 | 내용 |
| --- | --- |
| `source_professor_uid` | 비공개 원본 명부의 교수 ID |
| `namespace`, `identifier` | `national_researcher_number`, `legacy_kri_researcher_number`, `orcid` 중 하나와 문자열 식별자 |
| `status` | `candidate`, `accepted`, `rejected`, `conflict` |
| `source_kind`, `source_url` | 후보의 원본 DB 출처는 `source_database`와 null 가능. 채택에는 `official_registry`와 공식 HTTPS URL 필수 |
| `reviewed_by`, `checked_at` | 채택 시 검토자와 시간대가 있는 ISO 확인 시각 필수 |
| `evidence` | 채택 시 `human_reviewed`, `matched_author`, `no_conflict`를 명시적으로 true로 기록 |

논문 근거 분기는 서로 다른 `shared_dois` 두 개 이상과 `independent_publication_check`, `institution_time_agreement`를 요구한다. ORCID 분기는 `independent_orcid`에 `checked_independently`, `researcher_orcid`, `target_orcid`, `source_kind`, 해당 ORCID 프로필을 가리키는 `source_url`을 요구한다. 국가·과거 KRI 번호의 `registry_observation`에는 `namespace`, `identifier`, `source_url`, `record_reference`가 필요하다. 이 검토 입력은 사람이 확인한 내용을 기록하며, CLI가 외부 페이지를 자동 조회하지 않는다.

## 국내 박사 학과의 확인 경로

RISS에는 현재 공식 API 센터와 학위논문 검색 API가 있다. 검색 API는 학위논문 서지정보를 제공하며, 활용 대상은 비영리 기관·대학으로 안내되어 있다. 소속 대학 도서관을 통한 이용 가능성과 반환 필드의 학과·학위 정보 충실도를 확인할 수 있다. KISS의 이용 가능 범위는 별도 확인이 필요하며, RISS에 API가 없다고 전제해 학위논문 확인 경로를 폐기하지 않는다. [RISS 검색 API 공식 소개](https://www.riss.kr/apicenter/apiSearchIntro.do), [API 센터](https://www.riss.kr/apicenter/apiMain.do)

## 경상국립대학교 확인 경로

경상국립대학교는 KRI 공식 협정기관 목록에서 **연계 대학**으로 확인된다. 목록은 연계 대학을 대학 자체 시스템에서 연구업적을 등록·수정·삭제하는 유형으로 설명한다. 기존 교내 연계를 활용할 수 있는지 확인할 근거가 있으나, `gnu.ac.kr` 이메일 보유만으로 이번 연구용 서비스의 API 사용이 승인된 것으로 취급하지 않는다. [KRI 공식 협정기관 현황](https://www.kri.go.kr/kri/cm/PG-CM-700-01jl.jsp)

- 연구지원과 연구업적 관리: 055-772-2495
- 연구산학처 전산시스템 관리: 055-772-0218
- GNU RIMS 안내의 도서관 연구정보팀: 055-772-0533

담당 부서에는 기존 연계의 현재 담당자, 이번 연구용 서비스에서 연구자번호 조회·보관이 허용되는지, 학위 학과와 출처 정보를 받을 수 있는지, 기관 승인·반환 URL 등록 등 절차를 확인한다. 전임교원 업적 자동 전송과 외부 연구용 식별자 대조는 목적과 허용 범위가 다를 수 있다. 문의나 신청은 자동으로 발송하지 않았다.

[GNU 연구지원과 업무·연락처](https://www.gnu.ac.kr/main/jo/jobshare/selectJobShareView.do?deptCd=D1), [GNU RIMS 공식 안내](https://www.gnu.ac.kr/main/cm/cntnts/cntntsView.do?cntntsId=6264&mi=13344)
