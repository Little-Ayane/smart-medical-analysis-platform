# 核心分析功能

智慧医疗数据分析平台 - 核心分析模块

## 数据库配置

### 获取数据

数据库dump文件请联系项目负责人获取，或从共享目录下载：
- 文件：`star_schema_dump.sql`
- 大小：约187MB
- 记录数：210万条住院记录

### 创建数据库

```sql
CREATE DATABASE IF NOT EXISTS medical_db DEFAULT CHARACTER SET utf8mb4;
```

### 导入数据

```bash
mysql -u root -p medical_db < star_schema_dump.sql
```

### 验证数据

```sql
USE medical_db;
SELECT COUNT(*) FROM fact_discharge;  -- 应返回约210万条
SELECT COUNT(*) FROM dim_drg;         -- 应返回1285条
```

---

## 功能特性

| 功能 | API接口 | 说明 |
|------|---------|------|
| 维度组合选择 | `POST /api/v1/analysis/dimension-combine` | 任意维度组合分析 |
| 指标切换 | `POST /api/v1/analysis/metric-switch` | 多指标组切换 |
| 逐级下钻 | `POST /api/v1/analysis/drill-down` | 层次化下钻查询 |
| 时间上卷 | `POST /api/v1/analysis/time-rollup` | 时间维度聚合 |
| 交叉透视 | `POST /api/v1/analysis/pivot` | 多维度交叉分析 |
| 汇总统计 | `POST /api/v1/analysis/summary` | 全局指标汇总 |
| 元数据查询 | `GET /api/v1/analysis/metadata` | 获取可用维度和指标 |
| 健康检查 | `GET /api/v1/analysis/health` | 服务状态检查 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置数据库

编辑 `.env` 文件，配置MySQL连接信息：

```env
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=123456
MYSQL_DATABASE=medical_db
```

### 3. 启动服务

```bash
python -m main
```

服务将在 http://localhost:8000 启动

### 4. 访问API文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API接口详情

### 维度组合选择

```http
POST /api/v1/analysis/dimension-combine
```

**请求示例：**
```json
{
    "dimensions": ["hospital_name", "age_group"],
    "metrics": ["cases", "total_charges"],
    "filters": {"year": 2021},
    "limit": 100
}
```

### 指标切换

```http
POST /api/v1/analysis/metric-switch
```

**请求示例：**
```json
{
    "dimensions": ["hospital_name"],
    "metric_groups": {
        "financial": ["total_charges", "avg_charges"],
        "operational": ["cases", "avg_stay"]
    }
}
```

### 逐级下钻

```http
POST /api/v1/analysis/drill-down
```

**请求示例：**
```json
{
    "current_level": "hospital_area",
    "current_value": "New York City",
    "drill_to": "hospital_county",
    "metrics": ["cases", "total_charges"]
}
```

### 时间上卷

```http
POST /api/v1/analysis/time-rollup
```

**请求示例：**
```json
{
    "time_level": "year",
    "metrics": ["cases", "total_charges"],
    "compare_previous": true
}
```

### 交叉透视

```http
POST /api/v1/analysis/pivot
```

**请求示例：**
```json
{
    "row_dimension": "age_group",
    "col_dimension": "gender",
    "metric": "avg_charges"
}
```

## 可用维度

| 维度名称 | 说明 |
|----------|------|
| hospital_name | 医院名称 |
| hospital_area | 服务区 |
| hospital_county | 所在县 |
| age_group | 年龄段 |
| gender | 性别 |
| race | 种族 |
| diagnosis_code | 诊断编码 |
| diagnosis_desc | 诊断描述 |
| drg_code | DRG编码 |
| drg_desc | DRG描述 |
| severity_desc | 严重程度 |
| risk_mortality | 死亡风险 |
| payment_type | 支付方式 |
| year | 年份 |

## 可用指标

| 指标名称 | 说明 |
|----------|------|
| cases | 病例数 |
| total_charges | 总费用 |
| avg_charges | 平均费用 |
| total_costs | 总成本 |
| avg_costs | 平均成本 |
| avg_stay | 平均住院天数 |
| max_stay | 最大住院天数 |
| cost_ratio | 成本收益率 |

## 文件结构

```
核心功能/
├── main.py              # 独立入口
├── analysis.py          # API路由
├── analysis_service.py  # 业务逻辑
├── database.py          # 数据库配置
├── mysql_dao.py         # 数据访问层
├── sql_builder.py       # SQL构建器
├── requirements.txt     # 依赖
├── .env                 # 环境变量
└── README.md            # 本文件
```

## 技术栈

- Python 3.11
- FastAPI
- MySQL 8.0
- PyMySQL
