# 大数据分析服务模块 — RESTful API 接口文档

> 版本：v1.0 | 服务框架：Flask | 基础路径：`/api/v1` | 数据格式：JSON（UTF-8）
>
> **以实际代码为准**：标注「规划中/未实现」的接口尚未在代码中落地，部分能力已由
> `modules/` 下新接口替代（病种手术分析见《病种手术与支付分析接口文档》）。
> 当前已实现的接口：2.1 健康检查、2.2 聚合分析、2.5 支付方式占比、2.7 疾病趋势。

## 一、通用约定

### 1.1 统一响应格式（信封结构）

所有接口统一返回如下 JSON 结构，便于 AI 智能交互模块解析：

```json
{
  "code": 0,
  "message": "success",
  "data": { ... },
  "meta": {
    "dimension": "ccsr_diagnosis",
    "metric": "avg_length_of_stay",
    "total_records": 2100000,
    "query_ms": 128,
    "generated_at": "2026-08-13T10:00:00"
  }
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | int | 0 成功；非 0 为错误码 |
| `message` | string | 成功为 `success`，失败为友好错误提示 |
| `data` | object/array | 实际分析结果（结构化数据） |
| `meta.dimension` | string | 本次查询维度 |
| `meta.metric` | string | 本次查询指标 |
| `meta.total_records` | int | 参与计算的总记录数 |
| `meta.query_ms` | int | 查询耗时（毫秒） |
| `meta.generated_at` | string | 生成时间（ISO8601） |

### 1.2 错误码

| code | 说明 |
| --- | --- |
| 0 | 成功 |
| 400 | 参数错误（缺失/非法） |
| 401 | 未授权 |
| 404 | 资源不存在 |
| 408 | 查询超时 |
| 429 | 请求过于频繁 |
| 500 | 服务内部错误 |

### 1.3 通用查询参数

| 参数 | 类型 | 说明 | 示例 |
| --- | --- | --- | --- |
| `dimension` | string | 聚合维度 | `age_group` / `ccsr_diagnosis` / `facility` / `discharge_year` / `payment_typology` / `severity` |
| `metric` | string | 指标 | `count` / `avg_length_of_stay` / `total_charges` / `total_costs` / `avg_charges` |
| `year` | int | 出院年份过滤 | `2021` |
| `age_group` | string | 年龄段过滤 | `50 to 69` |
| `gender` | string | 性别过滤 | `M` / `F` |
| `payment` | string | 支付方式过滤 | `Medicare` |
| `top` | int | 返回 Top N（默认 20，最大 100） | `10` |
| `filters` | JSON | 复合过滤条件（URL 编码 JSON） | `{"discharge_year":2021,"gender":"F"}` |

---

## 二、接口清单

### 2.1 健康检查

```
GET /api/v1/health
```

**响应示例**
```json
{ "code": 0, "message": "success", "data": { "status": "ok", "db": "connected" }, "meta": { "query_ms": 1 } }
```

---

### 2.2 通用聚合分析（核心接口）

按任意维度聚合计算指定指标，AI 模块通过此接口适配各类自然语言提问。

```
GET /api/v1/analysis/aggregate?dimension=ccsr_diagnosis&metric=avg_length_of_stay&top=10
```

**请求示例**
```
GET /api/v1/analysis/aggregate?dimension=age_group&metric=total_charges&year=2021
```

**响应示例**
```json
{
  "code": 0,
  "message": "success",
  "data": [
    { "key": "0 to 17",       "value": 182345678.50, "count": 45210 },
    { "key": "18 to 29",      "value": 301223456.75, "count": 118034 },
    { "key": "70 or Older",   "value": 812900345.20, "count": 342118 }
  ],
  "meta": { "dimension": "age_group", "metric": "total_charges", "total_records": 2100000, "query_ms": 96 }
}
```

---

### 2.3 平均住院时长分析

> ⚠️ 规划中/未实现。平均住院日排行已由 `/api/v1/quality/length-of-stay` 提供。

```
GET /api/v1/analysis/length-of-stay?dimension=ccsr_diagnosis&top=10
```

**data 结构**
```json
{ "key": "CORONAVIRUS DISEASE 2019 (COVID-19)", "avg_los": 27.3, "count": 58932 }
```

---

### 2.4 费用分布分析

> ⚠️ 规划中/未实现。费用分布可由 `/api/v1/analysis/aggregate`（metric=total_charges/avg_charges/avg_costs）或 `/api/v1/cost/*` 替代。

```
GET /api/v1/analysis/charges?dimension=discharge_year
```

**data 结构**
```json
{ "key": "2021", "total_charges": 9234567890.00, "avg_charges": 43974.20, "avg_costs": 12230.55, "count": 210000 }
```

---

### 2.5 支付方式占比分析

```
GET /api/v1/analysis/payment-mix?year=2021
```

**data 结构**
```json
[
  { "payment": "Medicare", "count": 823400, "pct": 39.21 },
  { "payment": "Private Health Insurance", "count": 645120, "pct": 30.72 }
]
```

---

### 2.6 Top N 疾病诊断统计

> ⚠️ 规划中/未实现。诊断排行已由 `/api/v1/disease/top-diagnoses` 提供（返回 code+name，能力更强）。

```
GET /api/v1/analysis/top-diagnoses?top=10&year=2021
```

**data 结构**
```json
{ "key": "URINARY TRACT INFECTIONS", "count": 120450 }
```

---

### 2.7 疾病趋势分析（时间序列）

```
GET /api/v1/analysis/trend?dimension=discharge_year&diagnosis=INF012
```

**data 结构**
```json
[ { "year": 2019, "count": 12340 }, { "year": 2020, "count": 56780 }, { "year": 2021, "count": 58932 } ]
```

---

### 2.8 多维度交叉分析

> ⚠️ 规划中/未实现。维度交叉已由 `/api/v1/disease/heatmap`（dim1 × dim2 白名单）与 `/api/v1/payment/cross` 提供。

支持两个维度交叉（如 年龄段 × 年份）。

```
GET /api/v1/analysis/cross?dim1=age_group&dim2=discharge_year&metric=count
```

**data 结构**
```json
[
  { "dim1": "0 to 17",  "dim2": "2020", "value": 12340 },
  { "dim1": "0 to 17",  "dim2": "2021", "value": 14560 }
]
```

---

### 2.9 自然语言查询（AI 智能交互入口）

> ⚠️ 规划中/未实现。当前意图解析在 P4 AI 模块（3.AI交互/agent.py）内完成，直接调用上述分析接口，不经由此端点。

由 AI 智能交互模块调用，后端将自然语言解析后的意图参数传入。

```
POST /api/v1/analysis/query
Content-Type: application/json
```

**请求体**
```json
{
  "question": "2021年哪类疾病的平均住院时长最长？",
  "intent": { "dimension": "ccsr_diagnosis", "metric": "avg_length_of_stay", "year": 2021, "top": 5 },
  "conversation_id": "conv_12345"
}
```

**响应**：同 2.2，另返回 `meta.intent` 回显解析出的意图，供前端展示"系统理解了你的问题"。

---

## 三、二期扩展接口

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/v1/analysis/disease-association` | GET | 疾病关联分析（关联规则挖掘） |
| `/api/v1/analysis/predict-cost` | POST | 住院费用预测（机器学习） |
| `/api/v1/analysis/readmission-risk` | POST | 患者再入院风险评估 |
| `/api/v1/analysis/geo-distribution` | GET | 医院地理分布（供前端地图可视化） |

---

## 四、给各角色的接口契约要点

1. **P3（后端）**：严格按本文件实现接口，返回 `code/message/data/meta` 四段式信封；异常统一走错误码表，不抛裸异常。
2. **P4（AI）**：解析自然语言后，仅需把 `intent`（维度/指标/过滤条件）传给 2.2 或 2.9 接口，解析返回的 `data` 与 `meta` 生成文本摘要。
3. **P5（前端）**：根据 `data` 的 `key/value` 结构 + `meta.dimension/metric` 决定渲染柱状图/饼图/折线图；`meta.query_ms` 用于展示响应耗时。
