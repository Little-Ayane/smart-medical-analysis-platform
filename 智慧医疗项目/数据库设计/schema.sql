-- ============================================================
-- 智慧医疗大数据与AI大模型分析平台 —— 数据库设计（星型模式）
-- 引擎：MySQL 8.0 / 字符集：utf8mb4
-- 数据规模：事实表 200万+ 条住院出院记录
-- 设计：1 张事实表 + 4 张维度表，索引针对聚合维度优化
-- ============================================================

CREATE DATABASE IF NOT EXISTS smart_health
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_general_ci;

USE smart_health;

-- ------------------------------------------------------------
-- 维度表 1：医疗机构
-- ------------------------------------------------------------
CREATE TABLE dim_facility (
    facility_id           BIGINT       NOT NULL AUTO_INCREMENT COMMENT '医院维度主键（代理键）',
    operating_cert_number VARCHAR(32)  DEFAULT NULL COMMENT '医院运营证书编号',
    permanent_facility_id VARCHAR(32)  DEFAULT NULL COMMENT '医疗机构永久ID',
    facility_name         VARCHAR(255) DEFAULT NULL COMMENT '医疗机构名称',
    hospital_county       VARCHAR(64)  DEFAULT NULL COMMENT '医院所在县',
    service_area          VARCHAR(64)  DEFAULT NULL COMMENT '医院服务区域',
    city                  VARCHAR(64)  DEFAULT NULL COMMENT '城市',
    PRIMARY KEY (facility_id),
    UNIQUE KEY uk_facility (operating_cert_number, permanent_facility_id, facility_name),
    KEY idx_facility_county (hospital_county),
    KEY idx_facility_area (service_area)
) ENGINE=InnoDB COMMENT='医疗机构维度表';

-- ------------------------------------------------------------
-- 维度表 2：CCSR 诊断字典
-- ------------------------------------------------------------
CREATE TABLE dim_ccsr_diagnosis (
    diagnosis_id    BIGINT       NOT NULL AUTO_INCREMENT,
    ccsr_code       VARCHAR(16)  NOT NULL COMMENT 'CCSR诊断代码',
    description     VARCHAR(255) DEFAULT NULL COMMENT 'CCSR诊断描述',
    PRIMARY KEY (diagnosis_id),
    UNIQUE KEY uk_ccsr_diag_code (ccsr_code)
) ENGINE=InnoDB COMMENT='CCSR诊断字典维度表';

-- ------------------------------------------------------------
-- 维度表 3：CCSR 操作字典
-- ------------------------------------------------------------
CREATE TABLE dim_ccsr_procedure (
    procedure_id    BIGINT       NOT NULL AUTO_INCREMENT,
    ccsr_code       VARCHAR(16)  NOT NULL COMMENT 'CCSR操作代码',
    description     VARCHAR(255) DEFAULT NULL COMMENT 'CCSR操作描述',
    PRIMARY KEY (procedure_id),
    UNIQUE KEY uk_ccsr_proc_code (ccsr_code)
) ENGINE=InnoDB COMMENT='CCSR操作字典维度表';

-- ------------------------------------------------------------
-- 维度表 4：APR DRG 维度
-- ------------------------------------------------------------
CREATE TABLE dim_apr_drg (
    drg_id          BIGINT       NOT NULL AUTO_INCREMENT,
    apr_drg_code    VARCHAR(16)  DEFAULT NULL COMMENT 'APR DRG代码',
    apr_drg_desc    VARCHAR(255) DEFAULT NULL COMMENT 'DRG描述',
    apr_mdc_code    VARCHAR(16)  DEFAULT NULL COMMENT '主要诊断类别代码',
    apr_mdc_desc    VARCHAR(255) DEFAULT NULL COMMENT '主要诊断类别描述',
    PRIMARY KEY (drg_id),
    KEY idx_drg_mdc (apr_mdc_code)
) ENGINE=InnoDB COMMENT='APR DRG 维度表';

-- ------------------------------------------------------------
-- 事实表：住院患者出院记录（核心）
-- ------------------------------------------------------------
CREATE TABLE fact_inpatient_discharge (
    record_id                    BIGINT        NOT NULL AUTO_INCREMENT COMMENT '记录主键',
    facility_id                  BIGINT        DEFAULT NULL COMMENT '外键→dim_facility',
    diagnosis_id                 BIGINT        DEFAULT NULL COMMENT '外键→dim_ccsr_diagnosis',
    procedure_id                 BIGINT        DEFAULT NULL COMMENT '外键→dim_ccsr_procedure',
    drg_id                       BIGINT        DEFAULT NULL COMMENT '外键→dim_apr_drg',

    -- 患者人口统计学（无患者唯一ID，作为事实表属性）
    age_group                    VARCHAR(32)   DEFAULT NULL COMMENT '年龄组别',
    zip3                         CHAR(3)       DEFAULT NULL COMMENT '邮编前三位',
    gender                       CHAR(1)       DEFAULT NULL COMMENT '性别 M/F',
    race                         VARCHAR(64)   DEFAULT NULL COMMENT '种族',
    ethnicity                    VARCHAR(64)   DEFAULT NULL COMMENT '民族',

    -- 住院信息
    length_of_stay               INT           DEFAULT NULL COMMENT '住院天数',
    type_of_admission            VARCHAR(64)   DEFAULT NULL COMMENT '入院类型',
    patient_disposition          VARCHAR(128)  DEFAULT NULL COMMENT '离院去向',
    discharge_year               SMALLINT      DEFAULT NULL COMMENT '出院年份',

    -- 病情相关
    apr_severity_code            TINYINT       DEFAULT NULL COMMENT '病情严重程度代码',
    apr_severity_desc            VARCHAR(64)   DEFAULT NULL COMMENT '病情严重程度描述',
    apr_risk_mortality           TINYINT       DEFAULT NULL COMMENT '死亡风险等级',
    apr_medical_surgical         VARCHAR(32)   DEFAULT NULL COMMENT '内科/外科分类',

    -- 支付信息
    payment_typology_1           VARCHAR(64)   DEFAULT NULL COMMENT '主要支付方式',
    payment_typology_2           VARCHAR(64)   DEFAULT NULL COMMENT '次要支付方式',
    payment_typology_3           VARCHAR(64)   DEFAULT NULL COMMENT '第三支付方式',

    -- 其他
    birth_weight                 INT           DEFAULT NULL COMMENT '出生体重（克），非新生儿为NULL',
    ed_indicator                 CHAR(1)       DEFAULT NULL COMMENT '是否经急诊 Y/N',
    total_charges                DECIMAL(14,2) DEFAULT NULL COMMENT '总费用',
    total_costs                  DECIMAL(14,2) DEFAULT NULL COMMENT '总成本',

    PRIMARY KEY (record_id),
    -- 外键（出于批量入库性能考虑，可只保留索引、不强制外键约束）
    KEY idx_facility     (facility_id),
    KEY idx_diagnosis    (diagnosis_id),
    KEY idx_procedure    (procedure_id),
    KEY idx_drg          (drg_id),
    -- 聚合维度索引（分析服务高频查询字段）
    KEY idx_year         (discharge_year),
    KEY idx_age_group    (age_group),
    KEY idx_diag_code    (diagnosis_id, discharge_year),
    KEY idx_payment      (payment_typology_1),
    KEY idx_severity     (apr_severity_code)
) ENGINE=InnoDB COMMENT='住院患者出院记录事实表（200万+条）';

-- ============================================================
-- 常用分析示例查询（供大数据分析服务模块复用）
-- ============================================================

-- 1) 按疾病（CCSR诊断）统计平均住院时长
SELECT d.description                  AS diagnosis,
       COUNT(*)                       AS cnt,
       ROUND(AVG(f.length_of_stay),2) AS avg_los
FROM fact_inpatient_discharge f
JOIN dim_ccsr_diagnosis d ON f.diagnosis_id = d.diagnosis_id
GROUP BY d.description
ORDER BY cnt DESC
LIMIT 20;

-- 2) 按年份统计总费用分布
SELECT discharge_year,
       COUNT(*)                     AS cnt,
       ROUND(SUM(total_charges),2)  AS total_charges,
       ROUND(AVG(total_costs),2)    AS avg_costs
FROM fact_inpatient_discharge
GROUP BY discharge_year
ORDER BY discharge_year;

-- 3) 支付方式占比
SELECT payment_typology_1,
       COUNT(*)                            AS cnt,
       ROUND(COUNT(*)*100.0 / SUM(COUNT(*)) OVER(), 2) AS pct
FROM fact_inpatient_discharge
GROUP BY payment_typology_1
ORDER BY cnt DESC;

-- 4) 按年龄段 × 年份 的住院人数交叉聚合
SELECT age_group, discharge_year, COUNT(*) AS cnt
FROM fact_inpatient_discharge
GROUP BY age_group, discharge_year
ORDER BY discharge_year, age_group;
