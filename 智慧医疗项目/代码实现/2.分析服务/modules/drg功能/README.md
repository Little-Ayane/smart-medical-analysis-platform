# DRG分析功能模块

## 模块简介

本模块提供DRG（Diagnosis Related Groups）相关的分析功能，包括费用排名、住院天数对比、死亡风险对比、CMI排名和离群识别。

## 功能列表

| 功能 | 说明 | 接口 |
|------|------|------|
| DRG费用排名 | 按DRG分组统计费用排名 | `/api/v1/drg/cost-ranking` |
| 住院天数对比 | 按DRG/诊断/严重程度对比住院天数 | `/api/v1/drg/stay-comparison` |
| 死亡风险对比 | 按死亡风险等级统计分布 | `/api/v1/drg/mortality-risk` |
| CMI排名 | 病例组合指数排名 | `/api/v1/drg/cmi-ranking` |
| 离群识别 | IQR/Z-score方法识别异常值 | `/api/v1/drg/outlier-detection` |

## 聚合结果查询（毫秒级）

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

## 启动方式

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env

# 启动服务
python main.py
```

服务默认运行在 `http://localhost:8001`

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `MYSQL_HOST` | MySQL地址 | localhost |
| `MYSQL_PORT` | MySQL端口 | 3306 |
| `MYSQL_USER` | MySQL用户名 | root |
| `MYSQL_PASSWORD` | MySQL密码 | （空） |
| `MYSQL_DATABASE` | 数据库名 | medical_db |
| `HIVE_HOST` | Hive地址 | localhost |
| `HIVE_PORT` | HiveServer2端口 | 10000 |
| `DATA_SOURCE` | 数据源类型 | mysql |

## 数据源切换

```bash
# 使用MySQL（默认，毫秒级响应）
DATA_SOURCE=mysql

# 使用Hive（离线分析）
DATA_SOURCE=hive
```

## 算法说明

### CMI（病例组合指数）

CMI = 该组平均费用 / 全体平均费用

- CMI > 1：该组病例复杂度高于平均水平
- CMI = 1：与平均水平相当
- CMI < 1：该组病例复杂度低于平均水平

### 离群识别

支持两种方法：

**IQR方法（默认）：**
- Q1 - 1.5 × IQR < 正常值 < Q3 + 1.5 × IQR
- 超出范围的为离群值

**Z-score方法：**
- |Z| > threshold（默认3）为离群值
- Z = (X - μ) / σ
