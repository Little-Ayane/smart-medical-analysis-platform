-- ============================================================
-- 图表端点提速：覆盖索引补充
-- ============================================================
-- 背景：fact_discharge 1038 万行 / 16.5GB，buffer pool 1GB。
--       聚合查询一旦无法走覆盖索引，就退化为千万次主键回表，单条 5~15 分钟。
--
-- 实测（同一查询，仅差一个 SUM(length_of_stay)）：
--   带 length_of_stay : key=drg_id            rows=10113585  Extra: Using where       → 分钟级
--   不带              : key=idx_year_drg_cost rows=5056792   Extra: Using index(覆盖) → 秒级
--
-- 既有的 idx_year_* 索引族都不含 length_of_stay，所以凡是要算 AVG(length_of_stay)
-- 的端点全部退化。本文件补齐这些"宽一列"的覆盖索引。
--
-- 注意：
--   1. 不删除任何既有索引 —— bigscreen 模块对 idx_year_drg_cost / idx_bs_area 等
--      有 FORCE INDEX 硬依赖。
--   2. 建完必须 ANALYZE TABLE（文件末尾），否则统计信息过时、优化器选错索引。
--      本项目踩过此坑：count 查询 8s → ANALYZE 后 0.5s。
--   3. 每个索引约 50~90s，全部约 6~9 分钟，占用约 2~3GB。
--
-- 用法：
--   /opt/mysql/bin/mysql --socket=/opt/mysql/mysql.sock -u root medical_db < add_cache_indexes.sql
-- ============================================================

USE medical_db;

-- DRG cost-ranking / stay-comparison：内层 GROUP BY drg_id 需要同时出
-- SUM(total_charges)/SUM(total_costs)/SUM(length_of_stay)
ALTER TABLE fact_discharge
  ADD INDEX idx_y_drg_full (discharge_year, drg_id, total_charges, total_costs, length_of_stay);

-- quality/length-of-stay（按 diagnosis）、cost 按 diagnosis 的成本聚合
ALTER TABLE fact_discharge
  ADD INDEX idx_y_diag_full (discharge_year, diagnosis_id, total_charges, total_costs, length_of_stay);

-- quality/facility-ranking、disease/region-diff（按 hospital_id）
ALTER TABLE fact_discharge
  ADD INDEX idx_y_hosp_full (discharge_year, hospital_id, total_charges, total_costs, length_of_stay);

-- quality/mortality：GROUP BY diagnosis_id + SUM(patient_disposition = 'Expired')
ALTER TABLE fact_discharge
  ADD INDEX idx_y_diag_dispo (discharge_year, diagnosis_id, patient_disposition);

-- analysis/emergency-compare：GROUP BY 急诊标识 + AVG(los) + AVG(charges)
ALTER TABLE fact_discharge
  ADD INDEX idx_emerg_los_chg (emergency_department_indicator, length_of_stay, total_charges);

-- analysis/avg-los：GROUP BY age_group + AVG(length_of_stay)
ALTER TABLE fact_discharge
  ADD INDEX idx_y_age_los (discharge_year, age_group, length_of_stay);

-- 强制：刷新统计信息，否则上面的索引可能不被优化器采用
ANALYZE TABLE fact_discharge;
