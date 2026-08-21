# 核心分析功能 - API接口文档

## 基础信息

- **Base URL**: `http://localhost:8000`
- **API前缀**: `/api/v1`
- **数据格式**: JSON
- **在线文档**: `http://localhost:8000/docs` (Swagger UI)

---

## 一、核心分析接口

### 1.1 维度组合选择

**POST** `/api/v1/analysis/dimension-combine`

自由组合维度和指标进行聚合查询。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dimensions` | string[] | 是 | 维度列表，如 `["hospital_name", "drg_desc"]` |
| `metrics` | string[] | 是 | 指标列表，如 `["cases", "avg_charges"]` |
| `filters` | object | 否 | 筛选条件，如 `{"year": 2021}` |
| `sort` | object | 否 | 排序配置，如 `{"field": "cases", "order": "desc"}` |
| `limit` | int | 否 | 返回条数，默认100 |

**可用维度：**

| 维度名 | 说明 |
|--------|------|
| `hospital_name` | 医院名称 |
| `hospital_area` | 医院所属区域 |
| `hospital_county` | 医院所属县区 |
| `age_group` | 年龄段 |
| `gender` | 性别 |
| `race` | 种族 |
| `diagnosis_code` | 诊断编码 |
| `diagnosis_desc` | 诊断描述 |
| `procedure_code` | 手术编码 |
| `procedure_desc` | 手术描述 |
| `drg_code` | DRG编码 |
| `drg_desc` | DRG描述 |
| `mdc_code` | MDC编码 |
| `mdc_desc` | MDC描述 |
| `severity_desc` | 严重程度 |
| `risk_mortality` | 死亡风险 |
| `payment_type` | 支付方式 |
| `year` | 年份 |

**可用指标：**

| 指标名 | 说明 |
|--------|------|
| `cases` | 病例数 |
| `total_charges` | 总费用 |
| `avg_charges` | 平均费用 |
| `total_costs` | 总成本 |
| `avg_costs` | 平均成本 |
| `avg_stay` | 平均住院天数 |
| `max_stay` | 最大住院天数 |
| `min_stay` | 最小住院天数 |

**示例请求：**

```json
{
  "dimensions": ["hospital_name"],
  "metrics": ["cases", "avg_charges"],
  "filters": {"severity_desc": "Major"},
  "sort": {"field": "cases", "order": "desc"},
  "limit": 10
}
```

**示例响应：**

```json
{
  "columns": ["hospital_name", "cases", "avg_charges"],
  "rows": [
    {"hospital_name": "North Shore University Hospital", "cases": 47563, "avg_charges": 114955.32},
    {"hospital_name": "Mount Sinai Hospital", "cases": 46978, "avg_charges": 128568.47}
  ],
  "total": 10,
  "sql": "SELECT ..."
}
```

---

### 1.2 指标切换

**POST** `/api/v1/analysis/metric-switch`

按指标组切换查看不同维度的指标数据。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dimensions` | string[] | 是 | 维度列表 |
| `metric_groups` | object | 是 | 指标组，如 `{"费用": ["avg_charges"], "住院": ["avg_stay"]}` |
| `filters` | object | 否 | 筛选条件 |

**示例请求：**

```json
{
  "dimensions": ["drg_desc"],
  "metric_groups": {
    "费用指标": ["avg_charges", "total_charges"],
    "住院指标": ["avg_stay", "max_stay"]
  },
  "limit": 5
}
```

---

### 1.3 逐级下钻

**POST** `/api/v1/analysis/drill-down`

从汇总数据逐层下钻到明细。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `current_level` | string | 是 | 当前层级，如 `hospital_area` |
| `current_value` | string | 是 | 当前值，如 `New York City` |
| `drill_to` | string | 是 | 下钻目标，如 `hospital_name` |
| `metrics` | string[] | 是 | 指标列表 |
| `filters` | object | 否 | 筛选条件 |

**示例请求：**

```json
{
  "current_level": "hospital_area",
  "current_value": "New York City",
  "drill_to": "hospital_name",
  "metrics": ["cases", "avg_charges"]
}
```

---

### 1.4 时间上卷

**POST** `/api/v1/analysis/time-rollup`

按时间维度汇总数据。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `time_level` | string | 是 | 时间层级：`year`、`quarter`、`month` |
| `metrics` | string[] | 是 | 指标列表 |
| `filters` | object | 否 | 筛选条件 |
| `compare_previous` | bool | 否 | 是否与上期对比 |

---

### 1.5 交叉透视

**POST** `/api/v1/analysis/pivot`

行列维度交叉分析。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `row_dimension` | string | 是 | 行维度 |
| `col_dimension` | string | 是 | 列维度 |
| `metric` | string | 是 | 指标 |
| `filters` | object | 否 | 筛选条件 |

---

## 二、聚合结果查询接口（毫秒级）

预聚合结果表，直接查询，响应时间 < 50ms。

### 2.1 DRG费用排名

**GET** `/api/v1/agg/drg/ranking`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 20 | 返回条数 |
| `sort_by` | string | cases | 排序字段：cases/avg_charges/total_charges/avg_stay |
| `sort_order` | string | desc | 排序方向：asc/desc |

### 2.2 医院统计

**GET** `/api/v1/agg/hospital/stats`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 20 | 返回条数 |
| `sort_by` | string | cases | 排序字段 |
| `sort_order` | string | desc | 排序方向 |

### 2.3 诊断统计

**GET** `/api/v1/agg/diagnosis/stats`

### 2.4 死亡风险分布

**GET** `/api/v1/agg/mortality/risk`

### 2.5 严重程度分布

**GET** `/api/v1/agg/severity/stats`

### 2.6 年度趋势

**GET** `/api/v1/agg/yearly/trend`

### 2.7 年龄分布

**GET** `/api/v1/agg/age/distribution`

### 2.8 支付方式分布

**GET** `/api/v1/agg/payment/stats`

### 2.9 数据总览

**GET** `/api/v1/agg/summary`

**响应示例：**

```json
{
  "total_drg": 326,
  "total_hospitals": 204,
  "total_diagnosis": 471,
  "total_cases": 2021253,
  "data_source": "pre_aggregated (Spark SQL)"
}
```

---

## 三、系统接口

### 3.1 健康检查

**GET** `/api/v1/analysis/health`

### 3.2 元数据查询

**GET** `/api/v1/analysis/metadata`

返回所有可用的维度和指标列表。

---

## 四、错误响应

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 422 | 参数验证失败 |
| 500 | 服务器内部错误 |

**错误响应示例：**

```json
{
  "detail": "无效的维度: ['invalid_dim']"
}
```
