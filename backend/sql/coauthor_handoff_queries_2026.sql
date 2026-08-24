-- 공동연구자 전달용 읽기 전용 쿼리 (SQLite, 2026 릴리스)
--
-- 사용법
--   1. 아래 :parameter를 사용하는 DB 프로그램에서 값을 지정하거나,
--      실행 전에 :name 등을 실제 값으로 바꿉니다.
--   2. A 구역은 비공개 경력 DB, B 구역은 공개 생산성 DB에 각각 실행합니다.
--   3. 이 파일에는 INSERT/UPDATE/DELETE와 비밀번호·API 키가 없습니다.


-- ============================================================================
-- A. 실명·학력·경력 검토
-- DB: professor_affiliation_timeline_through_2026.sqlite
-- ============================================================================

-- A1. 분야 → 현재 재직기관 → 이름으로 교수 찾기
-- parameters: :subject, :institution, :name
SELECT
  p.professor_uid,
  p.name,
  p.subject,
  COALESCE(i.display_name,p.latest_institution_raw) AS current_institution,
  p.latest_rank,
  p.appointment_year,
  p.phd_year,
  p.openalex_id,
  p.orcid
FROM professors p
LEFT JOIN institution_units i ON i.unit_id=p.latest_institution_unit_id
WHERE (:subject IS NULL OR p.subject=:subject)
  AND (:institution IS NULL OR COALESCE(i.display_name,p.latest_institution_raw)
      LIKE '%' || :institution || '%')
  AND (:name IS NULL OR p.name LIKE '%' || :name || '%')
ORDER BY p.subject,current_institution,p.name;


-- A2. 한 교수의 학력
-- parameter: :professor_uid
SELECT
  e.degree_level,
  COALESCE(i.display_name,e.institution_raw) AS institution,
  e.country,
  e.inferred_start_year,
  e.award_year,
  e.confidence
FROM education e
LEFT JOIN institution_units i ON i.unit_id=e.institution_unit_id
WHERE e.professor_uid=:professor_uid
ORDER BY
  CASE e.degree_level
    WHEN 'bachelor' THEN 1 WHEN 'master' THEN 2 WHEN 'phd' THEN 3 ELSE 4
  END,
  e.award_year;


-- A3. 한 교수의 최종 경력 타임라인
-- raw affiliation_evidence가 아니라 박사·포닥·교수로 분류된 구간만 반환합니다.
-- parameter: :professor_uid
SELECT
  c.position_type,
  c.position_no,
  c.institution_name,
  c.start_period,
  c.end_period,
  c.nation,
  c.region,
  c.city,
  c.evidence_status,
  c.confidence,
  c.is_institution_successor,
  c.reasoning
FROM career_positions_v2 c
WHERE c.professor_uid=:professor_uid
ORDER BY c.start_year,c.start_period,c.position_type,c.position_no;


-- A4. 한 교수의 반기별 복수 소속
-- 연구년·겸임·대학/연구소 공동소속을 중복 삭제하지 않고 보여줍니다.
-- parameters: :professor_uid, :start_period, :end_period
SELECT
  a.period,
  a.institution_name,
  a.unit_label,
  a.nation,
  a.region,
  a.city,
  a.postal_code,
  a.campus_cluster_id,
  a.status,
  a.career_stage,
  a.faculty_position_no,
  a.confidence,
  a.work_count
FROM affiliation_periods a
WHERE a.professor_uid=:professor_uid
  AND (:start_period IS NULL OR a.period>=:start_period)
  AND (:end_period IS NULL OR a.period<=:end_period)
ORDER BY a.period,a.institution_name,a.unit_label;


-- A5. 첫 교수직과 이후 교수기관 이동
-- 기관 통합·교명 변경은 is_institution_successor로 식별합니다.
-- parameter: :professor_uid
SELECT
  c.position_no,
  c.institution_name,
  c.start_period,
  c.end_period,
  c.nation,
  c.region,
  c.is_institution_successor,
  c.confidence
FROM career_positions_v2 c
WHERE c.professor_uid=:professor_uid
  AND c.position_type='faculty'
ORDER BY c.position_no,c.start_period;


-- A6. 동명이인·잘못 집계된 논문 후보 감사
-- 후보 논문은 최종 경력·생산성에 포함되지 않습니다.
-- parameter: :professor_uid
SELECT
  d.publication_date,
  d.title,
  d.topic_name,
  d.field_name,
  d.domain_name,
  d.institution_names_json,
  d.candidate_score,
  d.severity,
  d.reasons_json,
  d.source_url
FROM duplicate_drop_candidate d
WHERE d.professor_uid=:professor_uid
ORDER BY d.candidate_score DESC,d.publication_date,d.work_id;


-- A7. 품질검사: 결과가 모두 0이어야 정상
SELECT
  (SELECT COUNT(*)
   FROM work_authorship_evidence w JOIN professors p USING(professor_uid)
   WHERE w.identity_decision='keep'
     AND p.phd_year IS NOT NULL
     AND w.publication_year<p.phd_year-5) AS pre_phd_keep_works,
  (SELECT COUNT(*)
   FROM affiliation_periods a JOIN professors p USING(professor_uid)
   WHERE p.phd_year IS NOT NULL AND a.year<p.phd_year-5) AS pre_phd_affiliations,
  (SELECT COUNT(*)
   FROM affiliation_periods a,json_each(a.source_work_ids_json) j
   JOIN work_authorship_evidence w
     ON w.professor_uid=a.professor_uid AND w.work_id=j.value
   WHERE w.identity_decision<>'keep') AS dropped_work_refs_in_timeline;


-- ============================================================================
-- B. 익명 논문 생산성·그룹 집계
-- DB: professor_dashboard_2026.sqlite
-- ============================================================================

-- B1. 한 익명 교수의 기본정보와 연도별 주저자 생산성
-- parameter: :professor_id  (예: P-XXXXXXXXXX)
SELECT
  p.professor_id,
  p.subject,
  p.current_institution,
  p.department,
  p.bachelor_institution,
  p.phd_institution,
  p.phd_country,
  p.phd_year,
  p.appointment_year,
  y.year,
  y.total_count,
  y.first_author_count,
  y.corresponding_author_count,
  y.impact_low_count,
  y.impact_medium_count,
  y.impact_high_count,
  y.mean_journal_2yr_citedness
FROM professors p
JOIN yearly_lead_output y USING(professor_id)
WHERE p.professor_id=:professor_id
ORDER BY y.year;


-- B2. 조건에 맞는 교수 목록
-- 영향도 M 이상 저널에 주저자 논문 N편 이상, 서로 다른 저널 K개 이상
-- parameters: :subject, :current_institution, :phd_institution,
--             :phd_country, :minimum_impact, :minimum_papers, :minimum_journals
SELECT
  p.professor_id,
  p.subject,
  p.current_institution,
  p.department,
  p.phd_institution,
  p.phd_country,
  SUM(j.lead_work_count) AS qualifying_lead_works,
  COUNT(*) AS qualifying_journals
FROM professors p
JOIN professor_journal_output j USING(professor_id)
WHERE (:subject IS NULL OR p.subject=:subject)
  AND (:current_institution IS NULL OR p.current_institution=:current_institution)
  AND (:phd_institution IS NULL OR p.phd_institution=:phd_institution)
  AND (:phd_country IS NULL OR p.phd_country=:phd_country)
  AND j.openalex_2yr_mean_citedness>=:minimum_impact
GROUP BY
  p.professor_id,p.subject,p.current_institution,p.department,
  p.phd_institution,p.phd_country
HAVING SUM(j.lead_work_count)>=:minimum_papers
   AND COUNT(*)>=:minimum_journals
ORDER BY qualifying_lead_works DESC,qualifying_journals DESC,p.professor_id;


-- B3. 분야·박사 출신기관/국가 그룹의 연도별 합계
-- 그래프에서는 반환된 실제 MIN(year)~MAX(year)를 공통 연도축으로 사용합니다.
-- parameters: :subject, :phd_institution, :phd_country
SELECT
  y.year,
  COUNT(DISTINCT p.professor_id) AS professor_count,
  SUM(y.total_count) AS lead_works,
  SUM(y.impact_low_count) AS impact_low,
  SUM(y.impact_medium_count) AS impact_medium,
  SUM(y.impact_high_count) AS impact_high
FROM professors p
JOIN yearly_lead_output y USING(professor_id)
WHERE (:subject IS NULL OR p.subject=:subject)
  AND (:phd_institution IS NULL OR p.phd_institution=:phd_institution)
  AND (:phd_country IS NULL OR p.phd_country=:phd_country)
GROUP BY y.year
ORDER BY y.year;


-- B4. 한 익명 교수의 기관별 경력
-- parameter: :professor_id
SELECT
  stage,
  position_no,
  institution,
  start_period,
  end_period,
  confidence,
  evidence_basis,
  is_estimated,
  is_institution_successor
FROM career_segments
WHERE professor_id=:professor_id
ORDER BY start_year,start_period,stage,institution;
