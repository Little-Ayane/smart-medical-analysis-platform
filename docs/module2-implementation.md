# 模块二：大数据分析服务 — 实现清单与对外接口

> 负责人：大数据分析工程师
> 技术栈：Hadoop 3.3.4 / Spark 3.5.4 / Hive 3.1.3 / Flask 3.0.3 / Redis 7.0.15 / Python 3.11
> 本文档定义本模块需要实现的全部功能、对外提供的 API 接口规范及响应格式。

---

## 一、实现总览

本模块需实现以下内容：

| 类别 | 数量 | 说明 |
|------|------|------|
| API 接口 | 19 个 | 覆盖费用、疾病、科室、趋势、区域、算法、系统 7 大模块 |
| 算法模块 | 5 个 | 描述性统计、相关性分析、趋势预测、异常检测、聚类分析 |
| 业务 Service | 7 个 | 每个 API 模块对应一个 Service |
| Spark SQL 查询类 | 5 个 | 费用、疾病、科室、趋势、区域 |
| 转换器 | 2 个 | ECharts 格式转换、统计指标计算 |
| ETL 模块 | 5 个 | 数据加载、清洗、转换、Schema 定义、数据校验 |
| 缓存模块 | 3 个 | Redis 连接、缓存管理、缓存键常量 |
| 中间件 | 3 个 | 认证、限流、全局异常处理 |
| 文档 | 4 份 | API 文档、数据接入指南、性能报告、部署指南 |
| 测试 | 7 个 | 各模块单元测试 |

---

## 二、项目目录结构

```
data-analysis/
│
├── ARCHITECTURE.md                  # 架构设计文档
├── README.md                        # 项目说明
├── requirements.txt                 # Python 依赖
├── config.py                        # 全局配置
├── .env                             # 环境变量
├── .gitignore
│
├── app.py                           # Flask 应用入口
├── wsgi.py                          # WSGI 生产入口
│
├── api/                             # API 接口层
│   ├── routes/                      # 路由蓝图（7 个模块）
│   ├── middleware/                   # 中间件
│   ├── schemas/                     # 请求/响应数据模型
│   └── validators/                  # 参数校验器
│
├── services/                        # 业务逻辑层（7 个 Service）
│
├── analytics/                       # 分析引擎层
│   ├── engine.py                    # SparkSession 管理
│   ├── queries/                     # Spark SQL 查询（5 个）
│   └── transformers/                # 结果转换器（2 个）
│
├── algorithms/                      # 算法库（5 个模块）
│   ├── descriptive_stats.py
│   ├── correlation.py
│   ├── trend_prediction.py
│   ├── anomaly_detection.py
│   └── clustering.py
│
├── cache/                           # 缓存层
│   ├── redis_client.py
│   ├── cache_manager.py
│   └── cache_keys.py
│
├── models/                          # 数据模型
├── dao/                             # 数据访问层
├── etl/                             # 数据预处理
├── utils/                           # 工具函数
├── tests/                           # 测试
├── scripts/                         # 脚本
├── data/                            # 数据文件
└── docs/                            # 文档
```

---

## 三、API 接口清单（19 个）

### 3.1 医疗费用分析（5 个接口）

#### ① 费用总览

```
GET /api/v1/expense/summary
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| year | int | 否 | 出院年份 |
| region | string | 否 | 医院服务区 |
| department | string | 否 | 科室/MDC |
| age_group | string | 否 | 年龄段 |

**返回示例：**
```json
{
    "code": 200,
    "message": "success",
    "data": {
        "summary": {
            "total_charges": 15234567890.00,
            "avg_charges": 72456.78,
            "median_charges": 34567.00,
            "total_records": 2100000
        },
        "distribution": {
            "labels": ["0-10000", "10000-20000", "..."],
            "counts": [120000, 230000, 0],
            "bin_edges": [0, 10000, 20000]
        },
        "echarts": {
            "type": "bar",
            "title": {"text": "住院费用分布", "left": "center"},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": ["0-10000", "..."]},
            "yAxis": {"type": "value", "name": "患者数量"},
            "series": [{"data": [120000, 230000], "type": "bar"}]
        }
    }
}
```

---

#### ② 按支付方式分析

```
GET /api/v1/expense/by-insurance
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| year | int | 否 | 出院年份 |
| region | string | 否 | 医院服务区 |
| department | string | 否 | 科室 |

**返回：** `data` 含各支付方式的患者数、总费用、平均费用、占比百分比、排名；`echarts` 为饼图配置。

---

#### ③ 按年龄+性别分析

```
GET /api/v1/expense/by-age-gender
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| year | int | 否 | 出院年份 |
| region | string | 否 | 医院服务区 |

**返回：** `data` 含各年龄×性别组合的患者数、总费用、平均费用；`echarts` 为分组柱状图。

---

#### ④ 费用-成本比率分析

```
GET /api/v1/expense/cost-ratio
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| year | int | 否 | 出院年份 |
| department | string | 否 | 科室 |

**返回：** `data` 各科室的总费用、总成本、成本收益率；`echarts` 为散点图。

---

#### ⑤ 费用排名

```
GET /api/v1/expense/ranking
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| dimension | string | 否 | hospital | 排名维度：hospital / department / disease |
| top_n | int | 否 | 10 | 返回数量 |
| metric | string | 否 | total | 指标：total / avg / median |
| year | int | 否 | - | 出院年份 |
| region | string | 否 | - | 医院服务区 |

**返回：** `data` Top N 排名列表（维度名称、病例数、总费用、平均费用）；`echarts` 为柱状图。

---

### 3.2 疾病分布分析（3 个接口）

#### ⑥ 高频疾病排名

```
GET /api/v1/disease/top
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| year | int | 否 | - | 出院年份 |
| region | string | 否 | - | 医院服务区 |
| top_n | int | 否 | 10 | 返回数量 |

**返回：** `data` Top N 疾病列表（诊断描述、病例数、占比、平均费用、平均住院天数）；`echarts` 为柱状图。

---

#### ⑦ 按严重程度分布

```
GET /api/v1/disease/by-severity
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| year | int | 否 | 出院年份 |
| disease | string | 否 | 疾病名称（模糊匹配） |

**返回：** `data` 各严重程度（Minor / Moderate / Major / Extreme）的病例数、费用统计；`echarts` 为饼图或堆叠柱状图。

---

#### ⑧ 疾病×区域交叉分析

```
GET /api/v1/disease/by-region
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| disease | string | 否 | 疾病名称（模糊匹配） |
| year | int | 否 | 出院年份 |

**返回：** `data` 疾病×区域的病例数矩阵；`echarts` 为热力图。

---

### 3.3 科室绩效分析（2 个接口）

#### ⑨ 科室绩效

```
GET /api/v1/department/performance
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| year | int | 否 | 出院年份 |
| department | string | 否 | 科室名称（模糊匹配） |

**返回：** `data` 各科室的病例数、总费用、平均费用、平均住院天数、死亡风险分布；`echarts` 为多维度柱状图。

---

#### ⑩ 科室综合排名

```
GET /api/v1/department/ranking
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| year | int | 否 | - | 出院年份 |
| metric | string | 否 | cases | 排名指标：cases / total_charges / avg_charges / avg_stay |
| top_n | int | 否 | 10 | 返回数量 |

**返回：** `data` Top N 科室排名；`echarts` 为柱状图。

---

### 3.4 时间趋势分析（2 个接口）

#### ⑪ 月度趋势

```
GET /api/v1/trend/monthly
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| year | int | 否 | - | 出院年份 |
| metric | string | 否 | cases | 指标：cases / total_charges / avg_charges |

**返回：** `data` 按月统计的病例数/费用数据；`echarts` 为折线图。

---

#### ⑫ 年度同比分析

```
GET /api/v1/trend/yearly-compare
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| metric | string | 否 | cases | 指标：cases / total_charges / avg_charges |

**返回：** `data` 各年数据 + 同比增长率；`echarts` 为柱状图 + 折线图组合。

---

### 3.5 区域分析（2 个接口）

#### ⑬ 区域费用/病例分布

```
GET /api/v1/region/overview
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| year | int | 否 | - | 出院年份 |
| metric | string | 否 | cases | 指标：cases / total_charges / avg_charges |

**返回：** `data` 各区域的病例数/费用统计；`echarts` 为柱状图。

---

#### ⑭ 区域对比分析

```
GET /api/v1/region/compare
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| region1 | string | 是 | 区域 1 名称 |
| region2 | string | 是 | 区域 2 名称 |
| metric | string | 否 | 对比指标：cases / total_charges / avg_charges / avg_stay |

**返回：** `data` 两个区域的对比数据；`echarts` 为对比柱状图。

---

### 3.6 算法分析（3 个接口）

#### ⑮ 异常检测

```
GET /api/v1/algorithm/anomaly
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| column | string | 是 | - | 检测列名（如 Total_Charges） |
| method | string | 否 | zscore | 检测方法：zscore / iqr |
| threshold | float | 否 | 3.0 | 阈值（Z-Score 模式） |
| year | int | 否 | - | 出院年份 |

**返回：**
```json
{
    "code": 200,
    "data": {
        "method": "zscore",
        "threshold": 3.0,
        "total_records": 2100000,
        "anomaly_count": 1234,
        "anomaly_rate": 0.059,
        "anomalies": [
            {"index": 12345, "value": 999999.99, "zscore": 5.6}
        ],
        "echarts": {
            "type": "scatter",
            "title": {"text": "费用异常检测结果"}
        }
    }
}
```

---

#### ⑯ 相关性分析

```
GET /api/v1/algorithm/correlation
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| columns | string | 是 | 逗号分隔的列名列表（如 Total_Charges,Length_of_Stay,Total_Costs） |
| method | string | 否 | 方法：pearson / spearman，默认 pearson |

**返回：**
```json
{
    "code": 200,
    "data": {
        "method": "pearson",
        "matrix": {
            "Total_Charges": {"Total_Charges": 1.0, "Length_of_Stay": 0.65, "Total_Costs": 0.89},
            "Length_of_Stay": {"Total_Charges": 0.65, "Length_of_Stay": 1.0, "Total_Costs": 0.72}
        },
        "top_correlations": [
            {"pair": ["Total_Charges", "Total_Costs"], "coefficient": 0.89}
        ],
        "echarts": {
            "type": "heatmap",
            "title": {"text": "相关性矩阵热力图"}
        }
    }
}
```

---

#### ⑰ 聚类分析

```
GET /api/v1/algorithm/cluster
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| features | string | 是 | - | 逗号分隔的特征列名 |
| n_clusters | int | 否 | 3 | 聚类数量 |
| method | string | 否 | kmeans | 聚类方法：kmeans |

**返回：**
```json
{
    "code": 200,
    "data": {
        "method": "kmeans",
        "n_clusters": 3,
        "total_records": 2100000,
        "clusters": [
            {
                "cluster_id": 0,
                "count": 800000,
                "percentage": 38.1,
                "centers": {"Total_Charges": 25000.0, "Length_of_Stay": 3.2}
            }
        ],
        "elbow": {"k": [2,3,4,5,6], "inertia": [1200, 800, 650, 580, 540]},
        "echarts": {
            "type": "scatter",
            "title": {"text": "聚类分析结果"}
        }
    }
}
```

---

### 3.7 系统接口（2 个接口）

#### ⑱ 健康检查

```
GET /api/v1/health
```

**返回：**
```json
{
    "code": 200,
    "data": {
        "status": "healthy",
        "spark": "connected",
        "redis": "connected",
        "hive": "connected",
        "timestamp": "2026-08-15T10:30:00"
    }
}
```

---

#### ⑲ 缓存统计

```
GET /api/v1/cache/stats
```

**返回：**
```json
{
    "code": 200,
    "data": {
        "hits": 12345,
        "misses": 678,
        "hit_rate": 94.79,
        "keys": 156
    }
}
```

---

## 四、统一响应格式规范

### 4.1 成功响应

```json
{
    "code": 200,
    "message": "success",
    "data": { ... }
}
```

### 4.2 错误响应

```json
{
    "code": 400,
    "message": "参数错误：year 必须为整数",
    "data": null,
    "errors": {"year": "类型错误，期望 int"}
}
```

### 4.3 分页响应

```json
{
    "code": 200,
    "message": "success",
    "data": [ ... ],
    "pagination": {
        "total": 1000,
        "page": 1,
        "page_size": 20,
        "total_pages": 50
    }
}
```

### 4.4 响应头

| Header | 说明 |
|--------|------|
| X-Cache | `HIT` 或 `MISS`，标识是否命中缓存 |
| X-Response-Time | 响应耗时（如 `235ms`） |

---

## 五、ECharts 对接说明（供前端/AI层参考）

所有接口返回的 `data.echarts` 字段为**完整的 ECharts option 配置**，前端可直接渲染：

```javascript
const res = await fetch('/api/v1/expense/summary?year=2021');
const { data } = await res.json();
const chart = echarts.init(document.getElementById('chart'));
chart.setOption(data.echarts);
```

支持的图表类型：

| echarts.type | 说明 | 使用场景 |
|-------------|------|---------|
| bar | 柱状图 | 费用排名、疾病排名、区域分布 |
| line | 折线图 | 月度趋势、年度趋势 |
| pie | 饼图 | 支付方式占比、严重程度分布 |
| scatter | 散点图 | 费用-成本关系、异常检测 |
| heatmap | 热力图 | 疾病×区域交叉分析、相关矩阵 |
| grouped_bar | 分组柱状图 | 年龄×性别分析 |

---

## 六、算法库接口（供 API 层调用）

### 6.1 描述性统计

```python
from algorithms.descriptive_stats import DescriptiveStats

# 单列统计摘要
result = DescriptiveStats.summary(df, "Total_Charges")
# 返回: {"count": ..., "mean": ..., "std": ..., "min": ..., "25%": ..., "50%": ..., "75%": ..., "max": ..., "skewness": ..., "kurtosis": ...}

# 分组统计
result = DescriptiveStats.group_summary(df, ["Age_Group", "Gender"], "Total_Charges")

# 频率分布表
result = DescriptiveStats.frequency_table(df, "CCSR_Diagnosis_Code", top_n=20)
```

### 6.2 相关性分析

```python
from algorithms.correlation import CorrelationAnalysis

# Pearson 相关系数
r = CorrelationAnalysis.pearson_correlation(df, "Total_Charges", "Length_of_Stay")

# 相关矩阵
matrix = CorrelationAnalysis.correlation_matrix(df, ["Total_Charges", "Length_of_Stay", "Total_Costs"])

# Top N 相关列
top = CorrelationAnalysis.top_correlations(df, "Total_Charges", n=5)
```

### 6.3 趋势预测

```python
from algorithms.trend_prediction import TrendPrediction

# 线性回归
result = TrendPrediction.linear_regression(df, "month", "cases")
# 返回: {"slope": ..., "intercept": ..., "r_squared": ..., "predictions": [...]}

# 移动平均
smoothed = TrendPrediction.moving_average(values, window=3)

# 指数平滑
smoothed = TrendPrediction.exponential_smoothing(values, alpha=0.3)
```

### 6.4 异常检测

```python
from algorithms.anomaly_detection import AnomalyDetection

# Z-Score 检测
anomalies = AnomalyDetection.zscore_detection(df, "Total_Charges", threshold=3.0)

# IQR 检测
anomalies = AnomalyDetection.iqr_detection(df, "Total_Charges", multiplier=1.5)

# 生成报告
report = AnomalyDetection.detect_and_report(df, "Total_Charges", method="zscore")
```

### 6.5 聚类分析

```python
from algorithms.clustering import ClusteringAnalysis

# K-Means 聚类
result = ClusteringAnalysis.kmeans_clustering(df, ["Total_Charges", "Length_of_Stay"], n_clusters=3)

# 肘部法则
elbow = ClusteringAnalysis.elbow_method(df, ["Total_Charges", "Length_of_Stay"], max_k=10)

# 聚类画像
profile = ClusteringAnalysis.cluster_profile(df, "cluster_id", ["Total_Charges", "Length_of_Stay"])
```

---

## 七、缓存策略

| 场景 | 缓存 Key 前缀 | TTL | 失效策略 |
|------|---------------|-----|---------|
| 费用总览 | `medical:expense:summary` | 10 分钟 | 手动清除 |
| 聚合查询 | `medical:{module}:{endpoint}` | 5 分钟 | TTL 自动过期 |
| 排行榜 | `medical:{module}:ranking` | 5 分钟 | TTL 自动过期 |
| 算法分析 | `medical:algorithm:{method}` | 30 分钟 | TTL 自动过期 |
| 健康检查 | 不缓存 | - | - |

---

## 八、性能目标

| 查询类型 | 目标响应时间 | 优化手段 |
|---------|------------|---------|
| 简单聚合（单表单条件） | < 1 秒 | Spark SQL + Redis 缓存 |
| 多维聚合（多表多条件） | < 3 秒 | 预计算 + 缓存 |
| 算法分析 | < 5 秒 | 异步计算 + 结果缓存 |
| 全表扫描 | < 10 秒 | 分区裁剪 + 列裁剪 |

---

## 九、交付清单

| # | 交付件 | 路径 | 状态 |
|---|--------|------|------|
| 1 | Flask 应用入口 | `app.py` + `wsgi.py` | 待开发 |
| 2 | 全局配置 | `config.py` + `.env` | 待开发 |
| 3 | API 路由（7 模块） | `api/routes/*.py` | 待开发 |
| 4 | 业务 Service（7 个） | `services/*.py` | 待开发 |
| 5 | Spark SQL 查询（5 个） | `analytics/queries/*.py` | 待开发 |
| 6 | ECharts 转换器 | `analytics/transformers/echarts_transformer.py` | 待开发 |
| 7 | 统计转换器 | `analytics/transformers/stats_transformer.py` | 待开发 |
| 8 | 算法库（5 个） | `algorithms/*.py` | 待开发 |
| 9 | 缓存模块 | `cache/*.py` | 待开发 |
| 10 | 中间件 | `api/middleware/*.py` | 待开发 |
| 11 | ETL 模块 | `etl/*.py` | 待开发 |
| 12 | 工具函数 | `utils/*.py` | 待开发 |
| 13 | 单元测试 | `tests/*.py` | 待开发 |
| 14 | API 接口文档 | `docs/api_documentation.md` | 待编写 |
| 15 | 数据接入指南 | `docs/data_access_guide.md` | 待编写 |
| 16 | 性能优化报告 | `docs/performance_report.md` | 待编写 |
| 17 | 部署指南 | `docs/deployment_guide.md` | 待编写 |
| 18 | 数据导入脚本 | `scripts/load_data.py` | 待开发 |
| 19 | 数据库初始化 | `scripts/init_db.py` | 待开发 |
