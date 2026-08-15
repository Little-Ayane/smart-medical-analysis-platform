# 数据库设计说明（P2 交付）

## 连接信息

| 项目 | 值 |
|------|-----|
| 数据库类型 | MySQL 8.0 |
| 数据库名 | `medical_db` |
| 默认端口 | 3306 |
| 字符集 | utf8mb4 |

> ⚠️ 注意：项目企划中数据库名为 `smart_health`，实际交付使用 `medical_db`，请队友在连接配置中使用 `medical_db`。

---

## 星型模型结构

```
                    ┌── dim_hospital      (医院, 206 家)
                    ├── dim_patient       (患者人口统计, 5301 种组合)
                    ├── dim_diagnosis     (CCSR 诊断, 478 种)
fact_discharge ─────├── dim_procedure     (CCSR 手术/操作, 320 种)
 (住院事实表)        ├── dim_drg           (APR-DRG 分组, 1318 种)
 2,100,546 行       ├── dim_payment       (支付方式组合, 428 种)
                    └── dim_time          (时间维度, 仅 2021 年)
```

---

## 表结构详情

### 事实表：`fact_discharge`（核心）

| 字段 | 类型 | 说明 |
|------|------|------|
| `fact_id` | BIGINT PK | 自增主键 |
| `hospital_id` | INT FK | → dim_hospital |
| `patient_demo_id` | INT FK | → dim_patient |
| `diagnosis_id` | INT FK | → dim_diagnosis |
| `procedure_id` | INT FK (可空) | → dim_procedure（非所有病例都有手术） |
| `drg_id` | INT FK | → dim_drg |
| `payment_id` | INT FK | → dim_payment |
| `year_id` | INT FK | → dim_time |
| `type_of_admission` | VARCHAR | 入院类型（Emergency/Newborn/Elective 等） |
| `patient_disposition` | VARCHAR | 出院去向（Home/Skilled Nursing 等） |
| `emergency_department_indicator` | CHAR(1) | 是否急诊：Y/N |
| `length_of_stay` | FLOAT | 住院天数 |
| `total_charges` | DECIMAL(12,2) | 总费用（美元） |
| `total_costs` | DECIMAL(12,2) | 总成本（美元） |
| `birth_weight` | FLOAT | 出生体重（克） |

---

### 维度表：`dim_hospital`

| 字段 | 类型 | 说明 |
|------|------|------|
| `hospital_id` | INT PK | 自增主键 |
| `permanent_facility_id` | INT | 医院唯一编码 |
| `facility_name` | VARCHAR(255) | 医院名称 |
| `operating_certificate_number` | VARCHAR(50) | 运营证书号 |
| `hospital_service_area` | VARCHAR(100) | 服务区域（如 New York City） |
| `hospital_county` | VARCHAR(100) | 所在县（如 Bronx） |

---

### 维度表：`dim_patient`

| 字段 | 类型 | 说明 |
|------|------|------|
| `patient_demo_id` | INT PK | 自增主键 |
| `age_group` | VARCHAR(50) | 年龄段（0-17 / 18-29 / 30-49 / 50-69 / 70 or Older） |
| `gender` | CHAR(1) | M / F |
| `race` | VARCHAR(100) | 种族 |
| `ethnicity` | VARCHAR(100) | 族裔（Spanish/Hispanic / Not Span/Hispanic） |
| `zip_code_3digits` | VARCHAR(10) | 邮编前3位 |

---

### 维度表：`dim_diagnosis`

| 字段 | 类型 | 说明 |
|------|------|------|
| `diagnosis_id` | INT PK | 自增主键 |
| `ccsr_diagnosis_code` | VARCHAR(20) | CCSR 诊断代码（如 INF012） |
| `ccsr_diagnosis_description` | VARCHAR(500) | 诊断描述（如 CORONAVIRUS DISEASE 2019） |

---

### 维度表：`dim_procedure`

| 字段 | 类型 | 说明 |
|------|------|------|
| `procedure_id` | INT PK | 自增主键 |
| `ccsr_procedure_code` | VARCHAR(20) | CCSR 手术代码（如 OTR004） |
| `ccsr_procedure_description` | VARCHAR(500) | 手术描述（如 ISOLATION PROCEDURES） |

---

### 维度表：`dim_drg`

| 字段 | 类型 | 说明 |
|------|------|------|
| `drg_id` | INT PK | 自增主键 |
| `apr_drg_code` | INT | DRG 代码 |
| `apr_drg_description` | VARCHAR(500) | DRG 描述 |
| `apr_mdc_code` | INT | 主要诊断类别代码 |
| `apr_mdc_description` | VARCHAR(500) | MDC 描述 |
| `apr_severity_code` | INT | 严重程度代码（1=Minor, 2=Moderate, 3=Major, 4=Extreme） |
| `apr_severity_description` | VARCHAR(100) | 严重程度描述 |
| `apr_risk_of_mortality` | VARCHAR(50) | 死亡风险 |
| `apr_medical_surgical_description` | VARCHAR(50) | 内科/外科 |

---

### 维度表：`dim_payment`

| 字段 | 类型 | 说明 |
|------|------|------|
| `payment_id` | INT PK | 自增主键 |
| `payment_typology_1` | VARCHAR(100) | 主要支付方（Medicare/Medicaid/Private 等） |
| `payment_typology_2` | VARCHAR(100) | 次要支付方（可为空） |
| `payment_typology_3` | VARCHAR(100) | 第三支付方（可为空） |

---

### 维度表：`dim_time`

| 字段 | 类型 | 说明 |
|------|------|------|
| `year_id` | INT PK | 自增主键 |
| `discharge_year` | INT | 出院年份（2021） |

---

## 外键关系一览

| 事实表字段 | 关联维度表 | 关联字段 |
|-----------|-----------|---------|
| `hospital_id` | `dim_hospital` | `hospital_id` |
| `patient_demo_id` | `dim_patient` | `patient_demo_id` |
| `diagnosis_id` | `dim_diagnosis` | `diagnosis_id` |
| `procedure_id` | `dim_procedure` | `procedure_id` |
| `drg_id` | `dim_drg` | `drg_id` |
| `payment_id` | `dim_payment` | `payment_id` |
| `year_id` | `dim_time` | `year_id` |

---

## 队友写 API 时的常用 JOIN 示例

### 示例 1：获取某医院的所有病例（含诊断+费用）

```sql
SELECT
    f.fact_id,
    h.facility_name,
    d.ccsr_diagnosis_description AS diagnosis,
    f.length_of_stay,
    f.total_charges,
    f.total_costs
FROM fact_discharge f
JOIN dim_hospital h ON f.hospital_id = h.hospital_id
JOIN dim_diagnosis d ON f.diagnosis_id = d.diagnosis_id
WHERE h.facility_name LIKE '%Montefiore%'
LIMIT 100;
```

### 示例 2：按诊断统计平均费用（给前端饼图/柱状图用）

```sql
SELECT
    d.ccsr_diagnosis_description AS diagnosis,
    COUNT(*) AS case_count,
    ROUND(AVG(f.total_charges), 2) AS avg_charge
FROM fact_discharge f
JOIN dim_diagnosis d ON f.diagnosis_id = d.diagnosis_id
GROUP BY d.diagnosis_id, d.ccsr_diagnosis_description
ORDER BY case_count DESC
LIMIT 10;
```

### 示例 3：按年龄段+性别统计病例数（给 ECharts 堆叠柱状图用）

```sql
SELECT
    p.age_group,
    p.gender,
    COUNT(*) AS case_count
FROM fact_discharge f
JOIN dim_patient p ON f.patient_demo_id = p.patient_demo_id
GROUP BY p.age_group, p.gender
ORDER BY case_count DESC;
```

### 示例 4：DRG 严重程度 vs 平均费用

```sql
SELECT
    drg.apr_severity_description AS severity,
    COUNT(*) AS cases,
    ROUND(AVG(f.total_costs), 2) AS avg_cost,
    ROUND(AVG(f.length_of_stay), 1) AS avg_los
FROM fact_discharge f
JOIN dim_drg drg ON f.drg_id = drg.drg_id
GROUP BY drg.apr_severity_description
ORDER BY avg_cost DESC;
```

### 示例 5：支付方式占比（给饼图用）

```sql
SELECT
    pay.payment_typology_1 AS payment_type,
    COUNT(*) AS cases,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS percentage
FROM fact_discharge f
JOIN dim_payment pay ON f.payment_id = pay.payment_id
GROUP BY pay.payment_typology_1
ORDER BY cases DESC;
```

---

## 数据规模

| 表 | 行数 |
|----|------|
| fact_discharge | 2,100,546 |
| dim_hospital | 206 |
| dim_patient | 5,301 |
| dim_diagnosis | 478 |
| dim_procedure | 320 |
| dim_drg | 1,318 |
| dim_payment | 428 |
| dim_time | 1 |

---

## 原始宽表（ODS 层）

同时保留了原始清洗后的宽表 `medical_data`（210 万行，33 列），字段与原始 CSV 一一对应，用于追溯和临时查询。

---

## 数据来源

纽约州 2021 年住院出院数据（SPARCS），清洗后去重率 0.05%，数据质量报告见 `data-analysis/docs/data-quality-report.md`。

---

## Python 连接示例（SQLAlchemy）

```python
from sqlalchemy import create_engine

engine = create_engine(
    "mysql+pymysql://root:密码@localhost/medical_db?charset=utf8mb4"
)

# 查询示例
import pandas as pd
df = pd.read_sql("""
    SELECT h.facility_name, COUNT(*) AS cases
    FROM fact_discharge f
    JOIN dim_hospital h ON f.hospital_id = h.hospital_id
    GROUP BY h.facility_name
    ORDER BY cases DESC
    LIMIT 10
""", engine)
print(df)
```
