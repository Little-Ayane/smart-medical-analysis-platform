# 智慧医疗数据分析平台 - 数据分析服务

基于FastAPI的医疗数据分析后端服务，支持多维度数据分析和DRG分析。

## 功能特性

### DRG分析功能（主要）

| 功能 | API接口 | 说明 |
|------|---------|------|
| DRG费用排名 | `POST /api/v1/drg/cost-ranking` | 按DRG分组统计费用排名 |
| 住院天数对比 | `POST /api/v1/drg/stay-comparison` | 按DRG/诊断/严重程度分组对比 |
| 死亡风险对比 | `POST /api/v1/drg/mortality-risk` | 按风险等级统计分析 |
| CMI排名 | `POST /api/v1/drg/cmi-ranking` | 病例组合指数排名 |
| 离群识别 | `POST /api/v1/drg/outlier-detection` | 费用/住院天数异常检测 |

### 核心分析功能（底层）

| 功能 | API接口 | 说明 |
|------|---------|------|
| 维度组合选择 | `POST /api/v1/analysis/dimension-combine` | 任意维度组合分析 |
| 指标切换 | `POST /api/v1/analysis/metric-switch` | 多指标组切换 |
| 逐级下钻 | `POST /api/v1/analysis/drill-down` | 层次化下钻查询 |
| 时间上卷 | `POST /api/v1/analysis/time-rollup` | 时间维度聚合 |
| 交叉透视 | `POST /api/v1/analysis/pivot` | 多维度交叉分析 |

## 技术栈

- **Web框架**: FastAPI
- **数据库**: MySQL 8.0
- **数据处理**: Pandas
- **ORM**: PyMySQL
- **文档**: Swagger UI / ReDoc

## 项目结构

```
data_analysis/
├── config/                    # 配置文件
│   └── database.py           # 数据库配置
│
├── src/                       # 源代码
│   ├── api/routes/            # API路由
│   │   ├── analysis.py       # 核心分析API
│   │   └── drg.py            # DRG分析API
│   ├── services/              # 业务逻辑
│   │   ├── analysis_service.py
│   │   └── drg_service.py
│   ├── query/                 # 查询引擎
│   │   └── sql_builder.py
│   ├── dao/                   # 数据访问
│   │   └── mysql_dao.py
│   └── main.py               # 应用入口
│
├── test/                      # 测试页面
│   ├── dashboard.html        # 核心功能测试
│   └── drg_dashboard.html    # DRG功能测试
│
├── docs/                      # 文档
├── .env                       # 环境变量
├── requirements.txt           # 依赖
└── README.md                  # 项目说明
```

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

### 3. 导入数据

```bash
mysql -u root -p medical_db < star_schema_dump.sql
```

### 4. 启动服务

```bash
python -m src.main
```

服务将在 http://localhost:8000 启动。

### 5. 访问API文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API接口详情

### DRG分析接口

#### 1. DRG费用排名

```http
POST /api/v1/drg/cost-ranking
```

**请求示例：**
```json
{
    "metrics": ["cases", "total_charges", "avg_charges"],
    "limit": 20,
    "sort_order": "desc"
}
```

**响应示例：**
```json
{
    "code": 200,
    "message": "success",
    "data": {
        "title": "DRG费用排名",
        "columns": ["drg_code", "drg_desc", "cases", "total_charges", "avg_charges"],
        "rows": [...],
        "total": 20
    }
}
```

#### 2. 住院天数对比

```http
POST /api/v1/drg/stay-comparison
```

**请求示例：**
```json
{
    "group_by": "drg",
    "metrics": ["avg_stay", "max_stay", "cases"],
    "limit": 20
}
```

**可选分组维度：** `drg`, `diagnosis`, `severity`, `mdc`

#### 3. 死亡风险对比

```http
POST /api/v1/drg/mortality-risk
```

**请求示例：**
```json
{
    "group_by": "risk_mortality",
    "metrics": ["cases", "avg_charges", "avg_stay"]
}
```

**可选分组维度：** `risk_mortality`, `severity`, `mdc`, `drg`

#### 4. CMI排名

```http
POST /api/v1/drg/cmi-ranking
```

**请求示例：**
```json
{
    "group_by": "drg",
    "limit": 20,
    "sort_order": "desc"
}
```

**可选分组维度：** `drg`, `mdc`, `hospital`

#### 5. 离群识别

```http
POST /api/v1/drg/outlier-detection
```

**请求示例：**
```json
{
    "metric": "avg_charges",
    "group_by": "drg",
    "method": "iqr",
    "threshold": 1.5,
    "limit": 50
}
```

**可选参数：**
- `metric`: `avg_charges`, `avg_stay`, `cases`
- `group_by`: `drg`, `diagnosis`, `hospital`
- `method`: `iqr`, `zscore`

#### 6. DRG汇总信息

```http
GET /api/v1/drg/summary
```

#### 7. 健康检查

```http
GET /api/v1/drg/health
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
| mdc_code | MDC编码 |
| mdc_desc | MDC描述 |
| severity_code | 严重程度编码 |
| severity_desc | 严重程度描述 |
| risk_mortality | 死亡风险 |
| medical_surgical | 内外科 |
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
| total_stay | 总住院天数 |
| avg_stay | 平均住院天数 |
| max_stay | 最大住院天数 |
| min_stay | 最小住院天数 |
| cost_ratio | 成本收益率 |
| charges_per_day | 日均费用 |

## 响应格式

所有接口返回统一格式：

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "columns": [...],
        "rows": [...],
        "total": 100
    }
}
```

## 开发团队

| 成员 | 职责 |
|------|------|
| 万方 | 框架搭建、数据存储、集成测试 |
| 骆志远 | 数据预处理、后端功能开发 |
| 白子涵 | 数据分析、DRG功能、后端功能开发 |
| 纪志鹏 | 大模型、API调用、后端功能开发 |
| 高清源 | 前端页面设计、接口对接 |

## 开发计划

- [x] 阶段1：数据层建设
- [x] 阶段2：核心分析功能
- [x] 阶段3：DRG分析功能
- [ ] 阶段4：优化与测试

## 许可证

MIT License
