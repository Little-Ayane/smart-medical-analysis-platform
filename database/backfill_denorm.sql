-- =============================================================================
-- fact_discharge 反规范化回填脚本（11 列中的剩余 4 列）
-- -----------------------------------------------------------------------------
-- 背景：medical_db.fact_discharge 已新增 11 列反规范化字段（原 15 列 → 26 列），
--       用于消除 DRG/核心分析/急诊 等慢接口对 7 张维度表的 JOIN。
--       其中 7 列已回填（age_group/gender/race/apr_severity_code/apr_severity_desc/
--       apr_risk_mortality/apr_medical_surgical），本脚本回填剩余 4 列：
--         discharge_year         <- dim_time.discharge_year     (via year_id)
--         payment_typology_1     <- dim_payment.payment_typology_1 (via payment_id)
--         payment_typology_2     <- dim_payment.payment_typology_2
--         payment_typology_3     <- dim_payment.payment_typology_3
-- 说明：脚本幂等（只更新仍为 NULL 的行），可安全重复执行。
-- =============================================================================

-- 关 binlog，降低大表 UPDATE 的 redo 开销（需 SUPER 权限，root 具备）
SET SESSION sql_log_bin = 0;

-- -----------------------------------------------------------------------------
-- 1) 回填 discharge_year（dim_time 仅 5 行，按 year_id 逐行显式更新，走 idx_year）
-- -----------------------------------------------------------------------------
UPDATE fact_discharge SET discharge_year = 2020 WHERE year_id = 1 AND discharge_year IS NULL;
UPDATE fact_discharge SET discharge_year = 2021 WHERE year_id = 2 AND discharge_year IS NULL;
UPDATE fact_discharge SET discharge_year = 2022 WHERE year_id = 3 AND discharge_year IS NULL;
UPDATE fact_discharge SET discharge_year = 2023 WHERE year_id = 4 AND discharge_year IS NULL;
UPDATE fact_discharge SET discharge_year = 2024 WHERE year_id = 5 AND discharge_year IS NULL;

-- -----------------------------------------------------------------------------
-- 2) 回填 payment_typology_1/2/3（dim_payment 551 行，JOIN 走 payment_id 索引）
--    注意：下方单条 `UPDATE ... JOIN` 在 128MB 缓冲池下会锁 ~2000 万行、仅 ~4500 行/秒，
--    实际生产请改用按 payment_id 分批的方式（见同目录 backfill_payment.py，~10000 行/秒）。
-- -----------------------------------------------------------------------------
UPDATE fact_discharge f
JOIN dim_payment p ON f.payment_id = p.payment_id
SET f.payment_typology_1 = p.payment_typology_1,
    f.payment_typology_2 = p.payment_typology_2,
    f.payment_typology_3 = p.payment_typology_3
WHERE f.payment_typology_1 IS NULL
   OR f.payment_typology_2 IS NULL
   OR f.payment_typology_3 IS NULL;

-- -----------------------------------------------------------------------------
-- 3) 校验（执行后应看到 4 列均已回填，NULL 数与源维度表一致）
-- -----------------------------------------------------------------------------
SELECT 'discharge_year' AS col, COUNT(*) AS total,
       SUM(discharge_year IS NULL) AS null_cnt
FROM fact_discharge
UNION ALL SELECT 'payment_typology_1', COUNT(*), SUM(payment_typology_1 IS NULL) FROM fact_discharge
UNION ALL SELECT 'payment_typology_2', COUNT(*), SUM(payment_typology_2 IS NULL) FROM fact_discharge
UNION ALL SELECT 'payment_typology_3', COUNT(*), SUM(payment_typology_3 IS NULL) FROM fact_discharge;
