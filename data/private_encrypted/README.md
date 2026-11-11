# 암호화된 비공개 결정 기록

공개 저장소에 두되, 실명 해제와 같은 비밀번호로만 열립니다. 형식은 `public/data/encrypted_names.json`과
같습니다(PBKDF2-SHA256 600,000회 → AES-256-GCM, `aad` 포함). 복호화한 평문은 gzip 압축 JSON입니다.

| 파일 | 내용 |
| --- | --- |
| `audit_decisions_20261105.json` | 저수량 전수점검 결정: `accepted`(공개 ID별 [work_id, author_id, raw_author_name]), `review`(검토 대상과 사유), `corroboration`(require_corroboration으로 뺀 논문), `review_csv`(제목·DOI 포함 검토표) |

키는 공개 ID 기준입니다. 비공개 DB에 반영할 때(`apply_verified_works.py`)는 익명화 salt로 `professor_uid`에
대응시킨 뒤 `works` / `rejected_works`로 넣습니다.
