# 数据预处理模块交付要求（上游）

> 本文档由「大数据分析服务模块」定义，供「数据预处理与持久化模块」参照执行。
> 如有疑问请及时沟通，上游交付质量直接影响下游所有分析接口的正确性与性能。

---

## 一、数据存储要求

### 1.1 存储目标

清洗后的数据必须写入 **Hive 表** 或 **MySQL 表**，下游通过 SparkSession 读取。

| 项目 | 要求 |
|------|------|
| 表名 | `medical_data`（如使用 Hive，数据库名 `medical_db`） |
| 存储格式 | Hive: ORC / Parquet；MySQL: InnoDB |
| 分区键 | 按 `Discharge_Year` 分区（Hive 场景），显著提升下游按年份查询的性能 |
| 主键/唯一约束 | 建议以 `Permanent_Facility_Id` + `Discharge_Year` + 行号 组合作为去重依据 |

### 1.2 必须建表的字段（共 33 列）

上游在建表时必须包含以下全部字段，字段名使用下划线命名（空格替换为 `_`）：

| 原始字段名 | 清洗后字段名 | 类型 | 说明 |
|-----------|-------------|------|------|
| Hospital Service Area | Hospital_Service_Area | STRING | 医院服务区 |
| Hospital County | Hospital_County | STRING | 医院所在县 |
| Operating Certificate Number | Operating_Certificate_Number | STRING | 运营证书号 |
| Permanent Facility Id | Permanent_Facility_Id | STRING | 设施永久 ID |
| Facility Name | Facility_Name | STRING | 医院名称 |
| Age Group | Age_Group | STRING | 年龄段 |
| Zip Code - 3 digits | Zip_Code_3digits | STRING | 邮编前 3 位 |
| Gender | Gender | STRING | 性别 |
| Race | Race | STRING | 种族 |
| Ethnicity | Ethnicity | STRING | 民族 |
| Length of Stay | Length_of_Stay | INT | 住院天数 |
| Type of Admission | Type_of_Admission | STRING | 入院类型 |
| Patient Disposition | Patient_Disposition | STRING | 出院去向 |
| Discharge Year | Discharge_Year | INT | 出院年份 |
| CCSR Diagnosis Code | CCSR_Diagnosis_Code | STRING | 诊断编码 |
| CCSR Diagnosis Description | CCSR_Diagnosis_Description | STRING | 诊断描述 |
| CSR Procedure Code | CCSR_Procedure_Code | STRING | 手术编码 |
| CCSR Procedure Description | CCSR_Procedure_Description | STRING | 手术描述 |
| APR DRG Code | APR_DRG_Code | INT | DRG 编码 |
| APR DRG Description | APR_DRG_Description | STRING | DRG 描述 |
| APR MDC Code | APR_MDC_Code | INT | MDC 编码 |
| APR MDC Description | APR_MDC_Description | STRING | MDC 描述（科室分类） |
| APR Severity of Illness Code | APR_Severity_of_Illness_Code | INT | 疾病严重程度编码 |
| APR Severity of Illness Description | APR_Severity_of_Illness_Description | STRING | 疾病严重程度描述 |
| APR Risk of Mortality | APR_Risk_of_Mortality | STRING | 死亡风险等级 |
| APR Medical Surgical Description | APR_Medical_Surgical_Description | STRING | 内外科分类 |
| Payment Typology 1 | Payment_Typology_1 | STRING | 主要支付方式 |
| Payment Typology 2 | Payment_Typology_2 | STRING | 次要支付方式 |
| Payment Typology 3 | Payment_Typology_3 | STRING | 第三支付方式 |
| Birth Weight | Birth_Weight | INT | 出生体重 |
| Emergency Department Indicator | Emergency_Department_Indicator | STRING | 急诊标识 |
| Total Charges | Total_Charges | **DOUBLE** | 总费用（必须为数值类型） |
| Total Costs | Total_Costs | **DOUBLE** | 总成本（必须为数值类型） |

---

## 二、数据清洗要求

### 2.1 必须完成的清洗项

| # | 清洗项 | 说明 | 不完成的后果 |
|---|--------|------|-------------|
| 1 | **货币列转数值** | `Total_Charges` 和 `Total_Costs` 原始值含逗号和美元符号（如 `"320,922.43"`），必须去除逗号/符号后转为 DOUBLE | 下游每个查询都要写 `REPLACE(..., ',', '')`，严重拖慢性能 |
| 2 | **列名标准化** | 所有列名中的空格、连字符替换为下划线，统一大小写 | Spark SQL 反引号查询不稳定，字段名不一致会导致查询失败 |
| 3 | **去重** | 按全部字段去重，或按业务主键去重 | 聚合结果偏大，费用/病例数虚高 |
| 4 | **缺失值处理** | 数值列（`Length_of_Stay`、`Total_Charges`、`Total_Costs`、`Birth_Weight`）：填充 0 或中位数；分类列：填充 `'Unknown'` | 下游聚合时 NULL 会被跳过，导致计数不一致 |
| 5 | **异常值处理** | `Total_Charges` ≤ 0 的记录需标记或剔除；`Length_of_Stay` 负值需修正 | 排名、均值计算被极端值污染 |
| 6 | **类型转换** | `Discharge_Year` → INT；`Length_of_Stay` → INT；`APR_DRG_Code`/`APR_MDC_Code`/`APR_Severity_of_Illness_Code` → INT | 下游类型不匹配，无法做数值比较和排序 |

### 2.2 建议完成的清洗项

| # | 清洗项 | 说明 |
|---|--------|------|
| 7 | **枚举值标准化** | `Gender` 统一为 `M`/`F`；`Age_Group` 统一格式（如 `0 to 17`、`18 to 29`、`30 to 49`、`50 to 69`、`70 or Older`） |
| 8 | **文本Trim** | 所有 STRING 字段去除首尾空格、多余换行符 |
| 9 | **派生列** | 新增 `Age_Group_Order`（INT，1-5），方便按年龄排序 |

---

## 三、数据质量报告要求

上游完成清洗后，必须提供一份**数据质量报告**，包含以下内容：

### 3.1 基础统计

| 指标 | 说明 |
|------|------|
| 原始记录数 | CSV 文件总行数（不含表头） |
| 清洗后记录数 | 去重、去异常值后的有效记录数 |
| 去重数量 | 被移除的重复记录数 |
| 异常值处理数量 | 被剔除或修正的异常记录数 |

### 3.2 字段质量

对每个字段报告：

| 指标 | 说明 |
|------|------|
| 空值数量 | 该字段 NULL 或空字符串的记录数 |
| 空值率 | 空值数量 / 总记录数 |
| 唯一值数量 | 该字段去重后的不同取值数 |
| 样例值 | 前 5 个典型取值 |

### 3.3 交付格式

报告以 Markdown 文件形式交付，路径约定为：

```
data-analysis/docs/data-quality-report.md
```

---

## 四、增量更新要求

| 项目 | 要求 |
|------|------|
| 更新频率 | 明确告知（每日/每周/每月/一次性） |
| 增量数据格式 | 与全量数据一致（CSV 或数据库表） |
| 增量标识 | 新增记录需有时间戳或批次号，便于下游识别增量范围 |
| 更新通知机制 | 增量数据就绪后，需通知下游（消息/接口/文件标记均可） |

---

## 五、对接验收标准

上游交付后，下游按以下标准验收：

| # | 验收项 | 验收方法 | 通过标准 |
|---|--------|---------|---------|
| 1 | 表可读取 | `spark.table("medical_data").count()` | 返回值 > 0 |
| 2 | 字段名一致 | `spark.table("medical_data").columns` | 与本文档第二节字段名完全匹配 |
| 3 | 货币列为 DOUBLE | `spark.table("medical_data").schema["Total_Charges"].dataType` | 返回 `DoubleType` |
| 4 | 无全量重复 | `df.count() == df.dropDuplicates().count()` | 返回 True |
| 5 | 关键字段无空值 | `SELECT COUNT(*) FROM medical_data WHERE Facility_Name IS NULL` | 返回 0 |
| 6 | 年份字段可用 | `SELECT DISTINCT Discharge_Year FROM medical_data` | 返回合理的年份列表 |

---

## 六、沟通联系

- 下游模块负责人：大数据分析工程师
- 数据库表名/连接信息变更时请第一时间通知
- 清洗逻辑有调整请同步更新本文档
