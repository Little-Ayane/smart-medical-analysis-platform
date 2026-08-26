-- fact_discharge 反规范化列补索引（用于慢接口 WHERE 过滤，消除无索引全表扫描）
ALTER TABLE fact_discharge
  ADD INDEX idx_discharge_year (discharge_year),
  ADD INDEX idx_age_group (age_group),
  ADD INDEX idx_gender (gender),
  ADD INDEX idx_race (race),
  ADD INDEX idx_severity_desc (apr_severity_desc),
  ADD INDEX idx_risk_mortality (apr_risk_mortality),
  ADD INDEX idx_medical_surgical (apr_medical_surgical),
  ADD INDEX idx_payment1 (payment_typology_1),
  ALGORITHM=INPLACE, LOCK=NONE;
