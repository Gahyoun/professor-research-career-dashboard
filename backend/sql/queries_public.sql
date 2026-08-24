-- 특정 학과 교수의 연도별 주저자 생산량
SELECT professor_id,year,total_count,impact_low_count,impact_medium_count,
       impact_high_count,mean_journal_2yr_citedness
FROM v_professor_dashboard
WHERE current_institution=:institution AND department=:department
ORDER BY professor_id,year;

-- 특정 박사 출신기관 교수 비교
SELECT p.professor_id,p.current_institution,p.department,
       SUM(y.total_count) AS lead_works,
       AVG(y.mean_journal_2yr_citedness) AS mean_journal_impact_proxy
FROM professors p
JOIN yearly_lead_output y USING(professor_id)
WHERE p.phd_institution=:phd_institution
GROUP BY p.professor_id,p.current_institution,p.department
ORDER BY lead_works DESC;

-- 분야 + 박사학위 국가 그룹의 연도별 생산량 (예: 물리 + 미국 박사)
SELECT y.year,COUNT(DISTINCT p.professor_id) AS professors,
       SUM(y.total_count) AS lead_works,
       SUM(y.impact_low_count) AS impact_low,
       SUM(y.impact_medium_count) AS impact_medium,
       SUM(y.impact_high_count) AS impact_high
FROM professors p JOIN yearly_lead_output y USING(professor_id)
WHERE p.subject=:subject AND p.phd_country=:phd_country
GROUP BY y.year
ORDER BY y.year;

-- 분야 + 특정 박사 출신기관 그룹 (예: 물리 + 서울대 박사)
SELECT p.professor_id,p.current_institution,y.year,y.total_count
FROM professors p JOIN yearly_lead_output y USING(professor_id)
WHERE p.subject=:subject AND p.phd_institution=:phd_institution
ORDER BY p.professor_id,y.year;

-- 웹의 수치 조건과 같은 질의: 영향도 M 이상 저널에 주저자 논문 N편 이상,
-- 서로 다른 저널 K개 이상을 낸 교수
SELECT p.professor_id,p.current_institution,
       SUM(j.lead_work_count) AS qualifying_lead_works,
       COUNT(*) AS qualifying_journals
FROM professors p JOIN professor_journal_output j USING(professor_id)
WHERE p.subject=:subject
  AND j.openalex_2yr_mean_citedness>=:minimum_impact
GROUP BY p.professor_id,p.current_institution
HAVING SUM(j.lead_work_count)>=:minimum_papers
   AND COUNT(*)>=:minimum_journals
ORDER BY qualifying_lead_works DESC,qualifying_journals DESC,p.professor_id;

-- 한 교수의 기관별 경력
SELECT stage,position_no,institution,start_period,end_period,confidence,evidence_basis,is_estimated,is_institution_successor
FROM career_segments
WHERE professor_id=:professor_id
ORDER BY start_year,start_period,stage,institution;

-- 교수 임용 뒤 생산량 변화
SELECT p.professor_id,p.appointment_year,y.year,y.total_count,y.mean_journal_2yr_citedness
FROM professors p JOIN yearly_lead_output y USING(professor_id)
WHERE p.professor_id=:professor_id AND y.year>=p.appointment_year
ORDER BY y.year;
