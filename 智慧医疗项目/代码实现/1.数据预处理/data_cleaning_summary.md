# 数据清洗纪要

> 项目：智慧医疗大数据与AI大模型分析平台
> 数据库：MySQL 8.0 / `medical_db`
> 数据来源：纽约州住院出院数据（SPARCS），2020-2024 共 5 个年度
> 文档更新：2026-08-21

---

## 一、数据概况

| 指标 | 数值 |
|------|------|
| 原始 CSV 总行数 | ~10,417,455 |
| 清洗后有效行数 | 10,378,775 |
| 删除异常记录 | 38,680 |
| 数据保留率 | 99.63% |
| 字段列数 | 33 |
| 年度覆盖 | 2020 / 2021 / 2022 / 2023 / 2024 |

### 各年数据量

| 年份 | 行数 | 占比 |
|------|------|------|
| 2020 | 2,003,376 | 19.3% |
| 2021 | 2,055,590 | 19.8% |
| 2022 | 2,068,534 | 19.9% |
| 2023 | 2,090,242 | 20.1% |
| 2024 | 2,161,033 | 20.8% |

---

## 二、清洗流程

### 阶段 1：CSV 预处理与导入

| 步骤 | 脚本 | 说明 |
|------|------|------|
| 1.1 表头修复 | `fix_2024_header.py` | 2024 年 CSV 表头列名与其他年份不一致（如 "Health Service Area" 应为 "Hospital Service Area"），自动对齐列名 |
| 1.2 数据导入 | `clean_medical_data_final.py` | 逐年导入 5 个 CSV 到 MySQL `medical_data` 表。支持断点续传、UTF-8/GBK 编码兼容、2021 年存量数据保护、批量插入优化 |

### 阶段 2：数据清洗

| 步骤 | 脚本 | 说明 |
|------|------|------|
| 2.1 精准清洗 | `cleaning_strict_v3.py` | 删除 Gender='U'（1,277 行）、删除 Permanent_Facility_Id 为 NULL（38,050 行）、将字符串 'nan' 转为真正的 NULL |
| 2.2 异常值移除 | `clean_outliers.py` | 统一处理异常值：性别未知、医院 ID 缺失。共删除 38,680 条，保留率 99.63% |

### 阶段 3：星型模型 ETL

| 步骤 | 脚本 | 说明 |
|------|------|------|
| 3.1 Pass1 维度构建 | `build_star_v4.py` | 2-Pass 优化：1 次全表扫描收集 7 个维度唯一键 → 批量 INSERT 到 `_etl` 维度表。6.2 分钟完成 |
| 3.2 Pass2 事实表构建 | `build_star_v5.py` | 续跑版：从 `_etl` 维表加载 ID 字典 → 分块 SELECT + 每批 500 行独立 commit → INSERT 到 `fact_discharge_etl`。13.2 分钟完成 |
| 3.3 原子替换 | SQL (RENAME TABLE) | 将 `_etl` 表原子 RENAME 为正式表名，完成切换 |

### 阶段 4：验收

| 检查项 | 结果 |
|--------|------|
| 行数对比（medical_data vs fact_discharge） | PASS 10,378,775 = 10,378,775 |
| 5 年分布对比 | PASS 5/5 年份行数完全一致 |
| 外键完整性（7 个维度表，0 孤儿 ID） | PASS 7/7 |
| 映射失败数 | 0 |

---

## 三、星型模型表结构

### 事实表：fact_discharge（10,378,775 行）

| 字段 | 类型 | 说明 |
|------|------|------|
| fact_id | BIGINT PK | 自增主键 |
| hospital_id | INT FK | → dim_hospital |
| patient_demo_id | INT FK | → dim_patient |
| diagnosis_id | INT FK | → dim_diagnosis |
| procedure_id | INT FK | → dim_procedure |
| drg_id | INT FK | → dim_drg |
| payment_id | INT FK | → dim_payment |
| year_id | INT FK | → dim_time |
| type_of_admission | VARCHAR | 入院类型 |
| patient_disposition | VARCHAR | 出院去向 |
| emergency_department_indicator | CHAR(1) | 是否急诊 Y/N |
| length_of_stay | FLOAT | 住院天数 |
| total_charges | DECIMAL(12,2) | 总费用（美元） |
| total_costs | DECIMAL(12,2) | 总成本（美元） |
| birth_weight | FLOAT | 出生体重（克） |

### 维度表汇总

| 维度表 | 行数 | 自然键 | 说明 |
|--------|------|--------|------|
| dim_time | 5 | discharge_year | 2020-2024 |
| dim_hospital | 218 | permanent_facility_id | 医院信息 |
| dim_patient | 10,145 | (age_group, gender, race, ethnicity, zip_code_3digits) | 患者人口统计 |
| dim_diagnosis | 485 | ccsr_diagnosis_code | CCSR 诊断分类 |
| dim_procedure | 322 | ccsr_procedure_code | CCSR 手术分类 |
| dim_drg | 5,761 | (apr_drg_code, apr_mdc_code, apr_severity_code, apr_risk_of_mortality, apr_medical_surgical) | APR-DRG 分组 |
| dim_payment | 551 | (payment_typology_1, payment_typology_2, payment_typology_3) | 支付方式组合 |

> 注：dim_drg 使用 5 列自然键确保唯一性，3 列键会导致重复。

---

## 四、脚本文件清单

### 活跃脚本（scripts/ 目录）

| 脚本 | 用途 | 执行顺序 |
|------|------|----------|
| `fix_2024_header.py` | 修复 2024 年 CSV 表头列名 | 1 |
| `clean_medical_data_final.py` | CSV → MySQL 批量导入（断点续传） | 2 |
| `cleaning_strict_v3.py` | 精准清洗：删除异常行 + 'nan' → NULL | 3 |
| `clean_outliers.py` | 异常值移除（性别U、医院ID缺失） | 4 |
| `build_star_v4.py` | 星型模型 Pass1：收集维度键 + INSERT 维表 | 5 |
| `build_star_v5.py` | 星型模型 Pass2：映射 ID + INSERT 事实表 | 6 |
| `check_nulls.py` | 工具：检查各字段 NULL 分布 | - |
| `data_health_check.py` | 工具：数据全面体检 | - |

### 归档脚本（scripts/archive/ 目录）

以下脚本在开发过程中被迭代替代，保留供追溯：

| 脚本 | 替代原因 |
|------|----------|
| `cleaning_pipeline.py` | 早期 CSV 导入管线，被 `clean_medical_data_final.py` 替代 |
| `clean_new.py` | `clean_medical_data_final.py` 的早期版本 |
| `cleaning_strict_v2.py` | 被 v3 替代（v3 修复了数值字段 'nan' 比较报错） |
| `dedup_and_check.py` | 全表去重方案，被 TRUNCATE + 重新导入替代 |
| `dedup_by_year.py` | 按年去重方案，被 TRUNCATE + 重新导入替代 |
| `dedup_only.py` | 仅去重，被 TRUNCATE + 重新导入替代 |
| `fix_remaining_issues.py` | 修复残留问题，被 `clean_outliers.py` 替代 |
| `build_star_schema.py` | 星型模型 ETL v1，被 v4 替代 |
| `build_star_v2.py` | v2：严格维度去重，被 v4 替代 |
| `build_star_v3.py` | v3：零锁方案，被 v4 替代（GROUP BY 太慢） |
| `build_fact_fast.py` | 内存字典映射，因维度键冲突被 v4 替代 |
| `build_fact_indexed.py` | 索引加速 JOIN，被 v4 替代 |
| `continue_star_schema.py` | 续建脚本，被 v4 替代 |

---

## 五、关键技术决策

### 5.1 为什么用 2-Pass 而不是 SQL JOIN？

纯 SQL 方式需要 8 次全表扫描（7 次 GROUP BY 建维表 + 1 次 7 表 JOIN 建事实表），在 1037 万行上耗时极长且容易触发锁表溢出。2-Pass 方案只需 2 次全表扫描：
- **Pass 1**：扫描 1 次，收集维度唯一键到 Python Set → 批量 INSERT 维表
- **Pass 2**：扫描 1 次，用内存字典 O(1) 映射维度 ID → 批量 INSERT 事实表

### 5.2 为什么每批 500 行独立提交？

v4 使用 2000 行/批的单事务，在 35.8% 时触发 MySQL 1206 锁表溢出（单事务持有锁过多）。v5 改为每 500 行独立 commit，彻底规避此问题，速度反而更快（15K/s vs 4K/s）。

### 5.3 为什么用 _etl 临时表？

直接 TRUNCATE + INSERT 原表会持有元数据锁（MDL），阻塞所有查询。创建 `_etl` 表完全独立，构建完成后用 `RENAME TABLE` 原子切换，零停机。

### 5.4 dim_drg 为什么用 5 列自然键？

3 列键 (apr_drg_code, apr_mdc_code, apr_severity_code) 在 15,554 行中只有 1,814 个唯一值，导致 100% 映射失败。增加 apr_risk_of_mortality 和 apr_medical_surgical 后，5 列键产生 5,761 个唯一值，覆盖全部数据。

---

## 六、数据导出

星型表已导出压缩，供同事使用：

| 文件 | 路径 | 大小 |
|------|------|------|
| 压缩包 | `star_schema_2020-2024.zip` | 0.47 GB |
| 合并 SQL | `star_schema_export/star_schema.sql` | 0.96 GB |
| 维表 SQL | `star_schema_export/dims.sql` | 1.48 MB |
| 事实表 SQL | `star_schema_export/fact_discharge.sql` | 0.95 GB |

### 导入命令

```bash
# 一键全量导入（推荐）
mysql -u用户名 -p 数据库名 < star_schema.sql

# 分步导入
mysql -u用户名 -p 数据库名 < dims.sql
mysql -u用户名 -p 数据库名 < fact_discharge.sql
```
