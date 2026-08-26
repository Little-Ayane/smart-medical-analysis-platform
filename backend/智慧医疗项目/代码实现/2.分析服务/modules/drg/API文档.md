# DRG分析功能 - API接口文档

## 基础信息

- **Base URL**: `http://localhost:8001`
- **API前缀**: `/api/v1`
- **数据格式**: JSON
- **在线文档**: `http://localhost:8001/docs` (Swagger UI)

---

## 一、DRG分析接口

### 1.1 DRG费用排名

**GET** `/api/v1/drg/cost-ranking`

按DRG分组统计费用排名。

**请求参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回条数 |
| `sort_by` | string | 否 | cases | 排序字段：cases/avg_charges/total_charges |
| `sort_order` | string | 否 | desc | 排序方向：asc/desc |
| `year` | int | 否 | - | 按年份筛选 |
| `hospital_area` | string | 否 | - | 按区域筛选 |

**响应示例：**

```json
{
  "title": "DRG费用排名",
  "columns": ["drg_code", "drg_desc", "mdc_code", "mdc_desc", "cases", "total_charges", "avg_charges"],
  "rows": [
    {
      "drg_code": 560,
      "drg_desc": "NEONATE BIRTH WEIGHT > 2499 GRAMS",
      "mdc_code": 15,
      "mdc_desc": "NEWBORN AND OTHER NEONATES",
      "cases": 139203,
      "total_charges": 1900707161.33,
      "avg_charges": 13654.21
    }
  ],
  "total": 20
}
```

---

### 1.2 住院天数对比

**GET** `/api/v1/drg/stay-comparison`

按不同维度对比住院天数。

**请求参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `group_by` | string | 否 | drg | 分组维度：drg/diagnosis/severity/mdc |
| `limit` | int | 否 | 20 | 返回条数 |
| `metrics` | string[] | 否 | - | 自定义指标 |

**分组维度说明：**

| 值 | 说明 |
|---|------|
| `drg` | 按DRG分组 |
| `diagnosis` | 按诊断分组 |
| `severity` | 按严重程度分组 |
| `mdc` | 按MDC大类分组 |

---

### 1.3 死亡风险对比

**GET** `/api/v1/drg/mortality-risk`

按死亡风险等级统计分布。

**请求参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `group_by` | string | 否 | risk_mortality | 分组维度 |

**响应示例：**

```json
{
  "title": "死亡风险对比 - 按risk_mortality分组",
  "rows": [
    {
      "risk_mortality": "Minor",
      "cases": 987564,
      "percentage": 48.86,
      "avg_charges": 44536.80,
      "avg_stay": 3.64
    },
    {
      "risk_mortality": "Extreme",
      "cases": 241819,
      "percentage": 11.96,
      "avg_charges": 152077.34,
      "avg_stay": 10.59
    }
  ],
  "total_cases": 2021253
}
```

---

### 1.4 CMI排名

**GET** `/api/v1/drg/cmi-ranking`

病例组合指数（Case Mix Index）排名。

**请求参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `group_by` | string | 否 | drg | 分组维度：drg/mdc/hospital |
| `limit` | int | 否 | 20 | 返回条数 |
| `sort_order` | string | 否 | desc | 排序方向 |

**响应示例：**

```json
{
  "title": "CMI排名 - 按drg分组",
  "rows": [
    {
      "drg_code": 2,
      "drg_desc": "HEART TRANSPLANT OR IMPLANT...",
      "cases": 150,
      "avg_charges": 500000.00,
      "cmi": 6.73,
      "weight_contribution": 0.005
    }
  ],
  "overall_avg_charges": 74309.65
}
```

---

### 1.5 离群识别

**GET** `/api/v1/drg/outlier-detection`

使用统计方法识别异常值。

**请求参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `metric` | string | 否 | avg_charges | 检测指标 |
| `group_by` | string | 否 | drg | 分组维度 |
| `method` | string | 否 | iqr | 检测方法：iqr/zscore |
| `threshold` | float | 否 | 1.5 | 阈值 |
| `limit` | int | 否 | 50 | 返回条数 |

**检测方法说明：**

| 方法 | 阈值含义 | 推荐值 |
|------|---------|--------|
| `iqr` | IQR倍数 | 1.5（标准）/ 3.0（宽松） |
| `zscore` | Z分数 | 2.0（严格）/ 3.0（标准） |

**响应示例：**

```json
{
  "title": "离群识别",
  "method": "iqr",
  "threshold": 1.5,
  "metric": "avg_charges",
  "outliers": [
    {
      "drg_code": 2,
      "drg_desc": "HEART TRANSPLANT...",
      "cases": 150,
      "avg_charges": 500000.00,
      "outlier_type": "high",
      "deviation": 425690.35
    }
  ],
  "outlier_count": 25,
  "normal_count": 301,
  "statistics": {
    "mean": 74309.65,
    "median": 45000.00,
    "std": 85000.00,
    "q1": 25000.00,
    "q3": 95000.00,
    "iqr": 70000.00
  }
}
```

---

### 1.6 DRG汇总信息

**GET** `/api/v1/drg/summary`

获取DRG数据的汇总统计信息。

**响应示例：**

```json
{
  "title": "DRG汇总信息",
  "total_drg": 326,
  "total_cases": 2021253,
  "total_charges": 150198609334.49,
  "avg_stay": 5.71,
  "risk_distribution": [...],
  "severity_distribution": [...]
}
```

---

## 二、聚合结果查询接口（毫秒级）

与核心功能模块共享的预聚合查询接口，响应时间 < 50ms。

| 接口 | 说明 |
|------|------|
| `GET /api/v1/agg/drg/ranking` | DRG费用排名 |
| `GET /api/v1/agg/hospital/stats` | 医院统计 |
| `GET /api/v1/agg/diagnosis/stats` | 诊断统计 |
| `GET /api/v1/agg/mortality/risk` | 死亡风险分布 |
| `GET /api/v1/agg/severity/stats` | 严重程度分布 |
| `GET /api/v1/agg/yearly/trend` | 年度趋势 |
| `GET /api/v1/agg/age/distribution` | 年龄分布 |
| `GET /api/v1/agg/payment/stats` | 支付方式分布 |
| `GET /api/v1/agg/summary` | 数据总览 |

---

## 三、系统接口

### 3.1 健康检查

**GET** `/api/v1/drg/health`

### 3.2 元数据查询

**GET** `/api/v1/drg/metadata`

---

## 四、错误响应

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 422 | 参数验证失败 |
| 500 | 服务器内部错误 |
