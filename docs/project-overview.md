# 模块二：大数据分析服务 — 项目总览

> 负责人：大数据分析工程师
> 运行环境：Linux（Hadoop 3.3.4 / Spark 3.5.4 / Hive 3.1.3）
> 开发环境：本地 Windows 开发，Linux 部署运行
> 更新日期：2026-08-15

---

## 一、项目背景

智慧医疗大数据与AI大模型分析平台，分为三大模块：

```
模块一：数据预处理与持久化（上游）  →  模块二：大数据分析服务（你）  →  模块三：AI智能交互（下游）
```

- 数据来源：纽约州医院住院患者出院数据（原始 210 万条）
- 你的职责：基于预处理好的数据，用 Spark SQL 做多维度聚合分析，通过 Flask RESTful API 对外暴露接口
- 下游消费方：AI 智能交互模块（LangChain Agent），解析用户自然语言 → 调用你的 API → 返回文字摘要 + ECharts 图表

---

## 二、上游数据现状

### 2.1 已交付的数据（星型模型）

上游已提供 5 张 CSV 文件，位于 `star_schema/` 目录：

```
star_schema/
├── dim_facility.csv              # 维度表：39 家医院
├── dim_apr_drg.csv               # 维度表：333 个 DRG 编码
├── dim_ccsr_diagnosis.csv        # 维度表：348 种诊断
├── dim_ccsr_procedure.csv        # 维度表：247 种手术
└── fact_inpatient_discharge.csv  # 事实表：9777 条住院记录
```

### 2.2 各表结构

#### dim_facility（医院维度）

| 字段 | 类型 | 说明 |
|------|------|------|
| facility_id | INT | 主键 |
| operating_cert_number | STRING | 运营证书号 |
| permanent_facility_id | STRING | 设施永久 ID |
| facility_name | STRING | 医院名称 |
| hospital_county | STRING | 所在县 |
| service_area | STRING | 服务区 |

#### dim_apr_drg（DRG 维度）

| 字段 | 类型 | 说明 |
|------|------|------|
| drg_id | INT | 主键 |
| apr_drg_code | INT | DRG 编码 |
| apr_drg_desc | STRING | DRG 描述 |
| apr_mdc_code | INT | MDC 编码 |
| apr_mdc_desc | STRING | MDC 描述（科室分类） |

#### dim_ccsr_diagnosis（诊断维度）

| 字段 | 类型 | 说明 |
|------|------|------|
| diagnosis_id | INT | 主键 |
| ccsr_code | STRING | CCSR 诊断编码 |
| description | STRING | 诊断描述 |

#### dim_ccsr_procedure（手术维度）

| 字段 | 类型 | 说明 |
|------|------|------|
| procedure_id | INT | 主键 |
| ccsr_code | STRING | CCSR 手术编码 |
| description | STRING | 手术描述 |

#### fact_inpatient_discharge（住院事实表）

| 字段 | 类型 | 说明 |
|------|------|------|
| facility_id | INT | 外键 → dim_facility |
| diagnosis_id | INT | 外键 → dim_ccsr_diagnosis |
| procedure_id | INT | 外键 → dim_ccsr_procedure |
| drg_id | INT | 外键 → dim_apr_drg |
| age_group | STRING | 年龄段 |
| zip3 | STRING | 邮编前 3 位 |
| gender | STRING | 性别（M/F） |
| race | STRING | 种族 |
| ethnicity | STRING | 民族 |
| length_of_stay | INT | 住院天数 |
| type_of_admission | STRING | 入院类型 |
| patient_disposition | STRING | 出院去向 |
| discharge_year | INT | 出院年份 |
| apr_severity_code | INT | 疾病严重程度编码 |
| apr_severity_desc | STRING | 疾病严重程度描述 |
| apr_risk_mortality | STRING | 死亡风险等级 |
| apr_medical_surgical | STRING | 内外科分类 |
| payment_typology_1 | STRING | 主要支付方式 |
| payment_typology_2 | STRING | 次要支付方式（53.8% 为空） |
| payment_typology_3 | STRING | 第三支付方式（83.3% 为空） |
| birth_weight | INT | 出生体重（88% 为空，非新生儿） |
| ed_indicator | STRING | 急诊标识 |
| total_charges | DOUBLE | 总费用 |
| total_costs | DOUBLE | 总成本 |

### 2.3 数据质量验收结果

| 检查项 | 结果 |
|--------|------|
| 列名标准化（小写+下划线） | ✅ 通过 |
| 行列数一致性 | ✅ 全部 33 列，无错位 |
| 货币列已清洗（无逗号/符号） | ✅ 通过 |
| 外键关系完整 | ✅ 通过 |
| BOM 字符 | ⚠️ 所有文件仍有 UTF-8 BOM，加载时需用 `utf-8-sig` 编码 |
| dim_facility 有 1 行空值 | ⚠️ 影响极小 |
| fact 表 gender 有 3 条空值 | ⚠️ 占 0.03%，影响极小 |

### 2.4 需要上游继续做的事

| 优先级 | 事项 | 说明 |
|--------|------|------|
| 🟡 建议 | 去掉 BOM | 保存 CSV 时选 UTF-8 无 BOM |
| 🟡 建议 | 补全 dim_facility 空记录 | 1 条空行，填充为 'Unknown' |
| 🟡 建议 | fact 表 gender 空值填充 | 3 条，填充为 'Unknown' |
| 🔵 后续 | 提供完整 210 万数据 | 当前 9777 条为开发测试用 |
| 🔵 后续 | 增量更新机制 | 增量数据的到达频率和格式 |

---

## 三、下游接口规范

### 3.1 接口设计哲学

下游（AI 层）要求**少而通用的参数化接口**，而不是按业务模块拆分的专用接口。

```
❌ 你的旧规划：/api/v1/expense/ranking, /api/v1/disease/top, /api/v1/department/ranking ...
✅ 下游要求：  /analysis/aggregate?dimension=disease&metric=total_charges&top=10
```

AI 层解析用户意图后，只需拼参数，不用判断该调哪个接口。

### 3.2 一期接口（必须实现，6 个）

#### ① GET /analysis/aggregate — 通用聚合

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| dimension | string | 是 | 聚合维度：hospital / disease / department / age_group / gender / severity / admission_type |
| metric | string | 是 | 聚合指标：total_charges / avg_charges / cases / avg_stay / total_costs |
| top | int | 否 | 返回 Top N，默认 10 |
| year | int | 否 | 出院年份筛选 |
| region | string | 否 | 服务区筛选 |

**用途**：覆盖所有排名类需求。一个接口替代之前的 expense/ranking、disease/top、department/ranking 等。

**示例**：
```
GET /analysis/aggregate?dimension=disease&metric=total_charges&top=10&year=2021
→ 返回 Top 10 疾病的费用排名

GET /analysis/aggregate?dimension=hospital&metric=cases&top=5
→ 返回病例数最多的 5 家医院

GET /analysis/aggregate?dimension=age_group&metric=avg_charges
→ 返回各年龄段平均费用
```

---

#### ② GET /analysis/payment-mix — 支付占比

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| year | int | 否 | 出院年份筛选 |

**用途**：各支付方式（Medicare / Medicaid / Private 等）的病例数和费用占比。

---

#### ③ GET /analysis/trend — 时间趋势

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| year_start | int | 否 | 起始年份 |
| year_end | int | 否 | 结束年份 |
| metric | string | 否 | 指标：cases / total_charges / avg_charges，默认 cases |

**用途**：按年份的时间序列数据，用于折线图。

---

#### ④ GET /analysis/compare — 多维度对比

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| dimensions | string[] | 是 | 逗号分隔的维度列表，如 `age_group,gender` |
| metrics | string[] | 是 | 逗号分隔的指标列表，如 `total_charges,avg_charges,cases` |
| filters | string | 否 | 筛选条件，JSON 格式 |

**用途**：一次请求返回多个维度×多个指标的交叉组合结果。

**示例**：
```
GET /analysis/compare?dimensions=age_group,gender&metrics=avg_charges,cases
→ 返回各年龄×性别的平均费用和病例数
```

---

#### ⑤ GET /analysis/distribution — 分布统计

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| dimension | string | 是 | 分布维度：age_group / total_charges / length_of_stay |
| metric | string | 否 | 统计指标，默认 cases（计数） |
| bins | int | 否 | 分桶数，默认 10（数值型维度用） |

**用途**：生成直方图数据。

**示例**：
```
GET /analysis/distribution?dimension=age_group
→ 返回各年龄段的患者数量分布

GET /analysis/distribution?dimension=total_charges&bins=20
→ 返回费用的 20 桶直方图
```

---

#### ⑥ GET /analysis/summary — 汇总统计

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| metrics | string[] | 是 | 逗号分隔的指标，如 `total_charges,length_of_stay` |
| filters | string | 否 | 筛选条件，JSON 格式 |

**用途**：返回指定指标的均值、中位数、总和、标准差、最小值、最大值。

**示例**：
```
GET /analysis/summary?metrics=total_charges,length_of_stay
→ 返回费用和住院天数的统计摘要

GET /analysis/summary?metrics=total_charges&filters={"age_group":"70 or Older"}
→ 返回 70 岁以上患者的费用统计
```

---

### 3.3 二期接口（预留，3 个）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/analysis/correlation` | GET | 相关性分析，参数 `x_metric`、`y_metric` |
| `/analysis/predict` | POST | 费用预测/再入院风险，参数 `model_type`、`features` |
| `/analysis/disease_association` | GET | 疾病关联规则挖掘，参数 `diagnosis_codes` |

---

### 3.4 统一响应格式

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "summary": {
            "total": 12345,
            "avg": 45678.90,
            "median": 34567.00
        },
        "table": [
            {"dimension": "COVID-19", "metric_value": 12345678, "count": 5000}
        ],
        "echarts": {
            "type": "bar",
            "title": {"text": "...", "left": "center"},
            "xAxis": {"type": "category", "data": [...]},
            "yAxis": {"type": "value"},
            "series": [{"data": [...], "type": "bar"}]
        }
    }
}
```

前端/AI 层直接 `chart.setOption(data.echarts)` 渲染图表。

---

## 四、开发计划

### 4.1 最小闭环：先跑通 /analysis/aggregate

```
① 加载 5 张 CSV → Spark 注册临时视图
② JOIN 成宽表 medical_data
③ 写动态 GROUP BY SQL
④ 返回 JSON
⑤ Flask 暴露接口
```

跑通一个，其他 5 个接口就是改 SQL 的事。

### 4.2 开发顺序

| 阶段 | 任务 | 产出 |
|------|------|------|
| 第 1 步 | 搭项目骨架 | 目录结构、config.py、app.py、requirements.txt |
| 第 2 步 | Spark 引擎 + 数据加载 | analytics/engine.py、etl/data_loader.py |
| 第 3 步 | 实现 /analysis/aggregate | 完整链路跑通 |
| 第 4 步 | 实现剩余 5 个一期接口 | payment-mix、trend、compare、distribution、summary |
| 第 5 步 | ECharts 转换器 | analytics/transformers/echarts_transformer.py |
| 第 6 步 | Redis 缓存层 | cache/ 目录 |
| 第 7 步 | 单元测试 | tests/ 目录 |
| 第 8 步 | 文档 | API 文档、部署指南 |

### 4.3 关键技术点

| 技术点 | 说明 |
|--------|------|
| Spark SQL 动态 SQL | `/analysis/aggregate` 的 dimension 和 metric 是动态的，需拼接 SQL |
| 星型模型 JOIN | 事实表 JOIN 4 张维度表，获取可读的名称 |
| ECharts 配置生成 | 后端直接返回 ECharts option JSON，前端零转换 |
| Redis 缓存 | 按请求参数 hash 做缓存键，TTL 5-30 分钟 |
| 编码处理 | CSV 有 BOM，加载时用 `utf-8-sig` |

---

## 五、Linux 部署注意事项

本模块代码在 Linux 环境运行，开发时需注意：

| 项目 | 说明 |
|------|------|
| Python 版本 | 3.11 |
| Spark 提交 | `spark-submit` 或通过 PySpark 直接调用 |
| 文件路径 | Linux 用 `/`，开发时注意路径分隔符 |
| 环境变量 | 通过 `.env` 文件管理，不硬编码 |
| Redis | 需确保 Redis 服务已启动 |
| Hive | 如使用 Hive，需确保 Metastore 服务可用 |
| 日志 | 输出到 `logs/app.log` |

---

## 六、文件索引

| 文件 | 说明 |
|------|------|
| `ARCHITECTURE.md` | 完整架构设计（目录结构、代码示例、性能优化） |
| `docs/upstream-requirements.md` | 对上游的数据交付要求 |
| `docs/module2-implementation.md` | 原始实现清单（需按本文档更新） |
| `docs/project-overview.md` | **本文档** — 项目总览 |
| `P3接口参考(1).txt` | 下游接口规范原文 |
| `star_schema/` | 星型模型数据（5 张 CSV） |
| `sample_10000_cleaned.csv` | 原始 flat CSV 样本（仅参考） |
