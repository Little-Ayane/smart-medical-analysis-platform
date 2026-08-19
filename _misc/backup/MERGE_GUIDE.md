# 代码合并指南

> 本文档供团队成员了解项目结构、配置和使用方法

---

## 一、项目概述

### 1.1 功能说明

智慧医疗数据分析平台 - 模块二（分析服务开发），提供以下核心功能：

1. **维度组合选择** - 支持任意维度组合分析
2. **指标切换** - 同一维度下快速切换不同指标组
3. **逐级下钻** - 从汇总数据逐层深入到明细
4. **时间上卷** - 按时间维度聚合（月→季→年）
5. **交叉透视** - 多维度交叉分析，生成透视表

### 1.2 技术栈

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.11+ | 运行环境 |
| FastAPI | 0.141.1 | Web框架 |
| MySQL | 8.0+ | 数据库 |
| PyMySQL | 1.1.0 | MySQL驱动 |
| uvicorn | 0.52.3 | ASGI服务器 |

### 1.3 数据规模

- **事实表记录数**：2,100,546 条（210万+）
- **维度表数量**：7 张
- **数据库**：medical_db

---

## 二、文件清单

### 2.1 需要合并的文件

```
data_analysis/
│
├── config/                        # 配置模块
│   ├── __init__.py
│   └── database.py               # 数据库配置
│
├── src/                           # 源代码
│   ├── __init__.py
│   ├── main.py                   # FastAPI应用入口
│   │
│   ├── api/                      # API层
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   └── analysis.py       # 分析接口路由
│   │   └── middleware/
│   │       └── __init__.py
│   │
│   ├── services/                 # 业务逻辑层
│   │   ├── __init__.py
│   │   └── analysis_service.py   # 分析服务
│   │
│   ├── query/                    # 查询引擎层
│   │   ├── __init__.py
│   │   └── sql_builder.py        # SQL构建器
│   │
│   ├── dao/                      # 数据访问层
│   │   ├── __init__.py
│   │   └── mysql_dao.py          # MySQL数据访问
│   │
│   └── utils/                    # 工具模块
│       └── __init__.py
│
├── scripts/                      # 脚本目录
│   └── init_db.sql               # 数据库初始化（待创建）
│
├── tests/                        # 测试目录
│   └── __init__.py
│
├── docs/                         # 文档目录
│
├── requirements.txt              # Python依赖
├── .env.example                  # 环境变量示例
├── .gitignore                    # Git忽略文件
├── README.md                     # 项目说明
├── IMPLEMENTATION_PLAN.md        # 实施计划
└── MERGE_GUIDE.md                # 本文档
```

### 2.2 不需要合并的文件

```
# 以下文件是本地开发环境的，不需要合并
.env                               # 实际环境变量（包含密码）
star_schema_dump.sql               # 数据库备份文件（512KB）
hospital_discharge_data.csv        # 原始数据文件（832MB）
sample_10000_cleaned.csv           # 样本数据
star_schema/                       # 星型模型CSV文件
```

---

## 三、环境配置

### 3.1 环境变量文件

复制 `.env.example` 为 `.env`，并修改以下配置：

```bash
cp .env.example .env
```

**.env.example 内容：**

```env
# ==================== MySQL配置 ====================
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password_here
MYSQL_DATABASE=medical_db

# ==================== 应用配置 ====================
APP_DEBUG=true
APP_HOST=0.0.0.0
APP_PORT=8000
APP_WORKERS=4
LOG_LEVEL=INFO
```

### 3.2 依赖安装

```bash
# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

**requirements.txt 内容：**

```txt
# Web框架
fastapi==0.141.1
uvicorn==0.52.3
pydantic==2.5.3

# 数据库
pymysql==1.1.0
cryptography==41.0.7

# 工具
python-dotenv==1.2.2
python-multipart==0.0.6

# 测试
pytest==7.4.4
httpx==0.26.0
```

---

## 四、数据库配置

### 4.1 数据库要求

| 项目 | 要求 |
|------|------|
| 数据库名 | medical_db |
| 字符集 | utf8mb4 |
| 排序规则 | utf8mb4_unicode_ci |
| MySQL版本 | 8.0+ |

### 4.2 表结构

**维度表（7张）：**

| 表名 | 说明 | 记录数 |
|------|------|--------|
| dim_hospital | 医院维度 | 206 |
| dim_patient | 患者维度 | 5,301 |
| dim_diagnosis | 诊断维度 | 478 |
| dim_procedure | 手术维度 | 320 |
| dim_drg | DRG维度 | 1,318 |
| dim_payment | 支付方式维度 | 428 |
| dim_time | 时间维度 | 1 |

**事实表（1张）：**

| 表名 | 说明 | 记录数 |
|------|------|--------|
| fact_discharge | 出院事实表 | 2,100,546 |

### 4.3 数据导入

```bash
# 方式1：使用SQL备份文件（推荐）
mysql -u root -p medical_db < star_schema_dump.sql

# 方式2：创建数据库后导入
mysql -u root -p -e "CREATE DATABASE medical_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p medical_db < star_schema_dump.sql
```

### 4.4 验证数据

```bash
# 连接数据库
mysql -u root -p medical_db

# 检查表结构
SHOW TABLES;

# 检查数据
SELECT COUNT(*) FROM fact_discharge;
-- 应该返回：2100546
```

---

## 五、启动服务

### 5.1 开发环境启动

```bash
# 方式1：直接运行
python src/main.py

# 方式2：使用uvicorn（支持热重载）
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

# 方式3：后台运行
nohup python src/main.py > app.log 2>&1 &
```

### 5.2 生产环境启动

```bash
# 使用uvicorn多进程模式
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4

# 或者使用systemd服务（推荐）
# 参考 docs/deployment.md
```

### 5.3 访问地址

| 地址 | 说明 |
|------|------|
| http://localhost:8000 | 根路由 |
| http://localhost:8000/docs | Swagger UI文档 |
| http://localhost:8000/redoc | ReDoc文档 |
| http://localhost:8000/api/v1/analysis/health | 健康检查 |

---

## 六、API接口文档

### 6.1 统一响应格式

所有接口返回统一格式：

```json
{
    "code": 200,
    "message": "success",
    "data": { ... }
}
```

### 6.2 核心接口

#### ① 维度组合选择

```http
POST /api/v1/analysis/dimension-combine
Content-Type: application/json
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| dimensions | string[] | 是 | 维度列表 |
| metrics | string[] | 是 | 指标列表 |
| filters | object | 否 | 筛选条件 |
| sort | object | 否 | 排序配置 |
| limit | int | 否 | 返回条数，默认100 |

**请求示例：**

```json
{
    "dimensions": ["hospital_area", "age_group"],
    "metrics": ["cases", "total_charges", "avg_charges"],
    "filters": {
        "year": 2021,
        "hospital_area": "New York City"
    },
    "sort": {"field": "total_charges", "order": "desc"},
    "limit": 100
}
```

**响应示例：**

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "columns": ["hospital_area", "age_group", "cases", "total_charges", "avg_charges"],
        "rows": [
            {
                "hospital_area": "New York City",
                "age_group": "70 or Older",
                "cases": 123456,
                "total_charges": "9876543210.00",
                "avg_charges": "79985.50"
            }
        ],
        "total": 100
    }
}
```

---

#### ② 指标切换

```http
POST /api/v1/analysis/metric-switch
Content-Type: application/json
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| dimensions | string[] | 是 | 维度列表 |
| metric_groups | object | 是 | 指标组 |
| filters | object | 否 | 筛选条件 |

**请求示例：**

```json
{
    "dimensions": ["hospital_area"],
    "metric_groups": {
        "financial": ["total_charges", "total_costs", "cost_ratio"],
        "operational": ["cases", "avg_stay"]
    },
    "filters": {"year": 2021}
}
```

**响应示例：**

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "columns": ["financial", "operational"],
        "rows": [
            {
                "hospital_area": "New York City",
                "financial": {
                    "total_charges": "83500495479.15",
                    "total_costs": "26202157614.97",
                    "cost_ratio": "0.31"
                },
                "operational": {
                    "cases": 937791,
                    "avg_stay": 5.78
                }
            }
        ],
        "total": 5
    }
}
```

---

#### ③ 逐级下钻

```http
POST /api/v1/analysis/drill-down
Content-Type: application/json
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| current_level | string | 是 | 当前层级 |
| current_value | any | 是 | 当前值 |
| drill_to | string | 是 | 下钻目标层级 |
| metrics | string[] | 是 | 指标列表 |
| filters | object | 否 | 筛选条件 |

**请求示例：**

```json
{
    "current_level": "hospital_area",
    "current_value": "New York City",
    "drill_to": "hospital_county",
    "metrics": ["cases", "total_charges"],
    "filters": {"year": 2021}
}
```

**响应示例：**

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "breadcrumb": ["New York City"],
        "current_level": "hospital_area",
        "current_value": "New York City",
        "drill_to": "hospital_county",
        "columns": ["hospital_county", "cases", "total_charges"],
        "rows": [
            {
                "hospital_county": "Manhattan",
                "cases": 364541,
                "total_charges": "42688589123.90"
            },
            {
                "hospital_county": "Kings",
                "cases": 190494,
                "total_charges": "13152309426.52"
            }
        ],
        "total": 5
    }
}
```

---

#### ④ 时间上卷

```http
POST /api/v1/analysis/time-rollup
Content-Type: application/json
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| time_level | string | 否 | 时间层级：year/quarter/month，默认year |
| metrics | string[] | 是 | 指标列表 |
| filters | object | 否 | 筛选条件 |
| compare_previous | bool | 否 | 是否与上期对比，默认false |

**请求示例：**

```json
{
    "time_level": "year",
    "metrics": ["cases", "total_charges"],
    "filters": {
        "year_start": 2019,
        "year_end": 2021
    },
    "compare_previous": true
}
```

---

#### ⑤ 交叉透视

```http
POST /api/v1/analysis/pivot
Content-Type: application/json
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| row_dimension | string | 是 | 行维度 |
| col_dimension | string | 是 | 列维度 |
| metric | string | 是 | 指标 |
| filters | object | 否 | 筛选条件 |

**请求示例：**

```json
{
    "row_dimension": "age_group",
    "col_dimension": "gender",
    "metric": "avg_charges",
    "filters": {"year": 2021}
}
```

**响应示例：**

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "rows": ["0 to 17", "18 to 29", "30 to 49", "50 to 69", "70 or Older"],
        "columns": ["F", "M", "U"],
        "matrix": [
            ["45314.39", "50098.70", "19318.01"],
            ["39799.29", "67772.94", "48994.66"],
            ["50818.94", "73338.04", "60989.45"],
            ["86236.05", "93231.50", "89777.84"],
            ["82449.40", "92588.63", "107017.87"]
        ],
        "row_dimension": "age_group",
        "col_dimension": "gender",
        "metric": "avg_charges"
    }
}
```

---

#### ⑥ 汇总统计

```http
POST /api/v1/analysis/summary
Content-Type: application/json
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| metrics | string[] | 是 | 指标列表 |
| filters | object | 否 | 筛选条件 |

**请求示例：**

```json
{
    "metrics": ["cases", "total_charges", "avg_stay"],
    "filters": {"year": 2021}
}
```

**响应示例：**

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "cases": 2100546,
        "total_charges": "154046656299.88",
        "avg_stay": 5.657
    }
}
```

---

#### ⑦ 获取元数据

```http
GET /api/v1/analysis/metadata
```

**响应示例：**

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "dimensions": {
            "hospital_area": {
                "table": "dim_hospital",
                "column": "hospital_service_area",
                "alias": "hospital_area",
                "sample_values": ["New York City", "Long Island", "Hudson Valley"],
                "count": 5
            }
        },
        "metrics": {
            "cases": {
                "function": "COUNT",
                "column": "*",
                "alias": "cases"
            }
        }
    }
}
```

---

#### ⑧ 健康检查

```http
GET /api/v1/analysis/health
```

**响应示例：**

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "status": "healthy",
        "database": "healthy",
        "timestamp": "2026-08-15T20:49:27.762761"
    }
}
```

---

## 七、可用维度和指标

### 7.1 维度列表

| 维度名称 | 说明 | 所属表 |
|----------|------|--------|
| hospital | 医院ID | dim_hospital |
| hospital_name | 医院名称 | dim_hospital |
| hospital_area | 服务区 | dim_hospital |
| hospital_county | 所在县 | dim_hospital |
| age_group | 年龄段 | dim_patient |
| gender | 性别 | dim_patient |
| race | 种族 | dim_patient |
| ethnicity | 民族 | dim_patient |
| zip_code | 邮编 | dim_patient |
| diagnosis_code | 诊断编码 | dim_diagnosis |
| diagnosis_desc | 诊断描述 | dim_diagnosis |
| procedure_code | 手术编码 | dim_procedure |
| procedure_desc | 手术描述 | dim_procedure |
| drg_code | DRG编码 | dim_drg |
| drg_desc | DRG描述 | dim_drg |
| mdc_code | MDC编码 | dim_drg |
| mdc_desc | MDC描述 | dim_drg |
| severity_code | 严重程度编码 | dim_drg |
| severity_desc | 严重程度描述 | dim_drg |
| risk_mortality | 死亡风险 | dim_drg |
| medical_surgical | 内外科 | dim_drg |
| payment_type | 支付方式 | dim_payment |
| year | 年份 | dim_time |
| admission_type | 入院类型 | fact_discharge |
| disposition | 出院去向 | fact_discharge |
| ed_indicator | 急诊标识 | fact_discharge |

### 7.2 指标列表

| 指标名称 | 说明 | 计算方式 |
|----------|------|----------|
| cases | 病例数 | COUNT(*) |
| total_charges | 总费用 | SUM(total_charges) |
| avg_charges | 平均费用 | AVG(total_charges) |
| total_costs | 总成本 | SUM(total_costs) |
| avg_costs | 平均成本 | AVG(total_costs) |
| total_stay | 总住院天数 | SUM(length_of_stay) |
| avg_stay | 平均住院天数 | AVG(length_of_stay) |
| max_stay | 最大住院天数 | MAX(length_of_stay) |
| min_stay | 最小住院天数 | MIN(length_of_stay) |
| cost_ratio | 成本收益率 | total_costs / total_charges |
| charges_per_day | 日均费用 | total_charges / length_of_stay |

---

## 八、测试验证

### 8.1 健康检查

```bash
curl http://localhost:8000/api/v1/analysis/health
```

### 8.2 测试维度组合

```bash
curl -X POST http://localhost:8000/api/v1/analysis/dimension-combine \
  -H "Content-Type: application/json" \
  -d '{
    "dimensions": ["hospital_area"],
    "metrics": ["cases", "total_charges"],
    "filters": {"year": 2021},
    "limit": 5
  }'
```

### 8.3 测试交叉透视

```bash
curl -X POST http://localhost:8000/api/v1/analysis/pivot \
  -H "Content-Type: application/json" \
  -d '{
    "row_dimension": "age_group",
    "col_dimension": "gender",
    "metric": "avg_charges",
    "filters": {"year": 2021}
  }'
```

---

## 九、常见问题

### 9.1 数据库连接失败

**问题**：`Can't connect to local MySQL server`

**解决**：
1. 检查MySQL服务是否启动
2. 检查.env中的数据库配置是否正确
3. 检查MySQL用户权限

### 9.2 端口被占用

**问题**：`Address already in use`

**解决**：
```bash
# 查找占用端口的进程
lsof -i :8000

# 杀死进程
kill -9 <PID>

# 或者修改端口
# 编辑 .env 文件，修改 APP_PORT=8001
```

### 9.3 模块导入错误

**问题**：`ModuleNotFoundError: No module named 'xxx'`

**解决**：
```bash
# 安装依赖
pip install -r requirements.txt

# 或者使用Python 3.11
/usr/local/bin/python3.11 src/main.py
```

### 9.4 数据查询为空

**问题**：查询返回空结果

**解决**：
1. 检查数据是否导入成功
2. 检查筛选条件是否正确
3. 使用元数据接口查看可用维度值

---

## 十、联系信息

如有问题，请联系：

- **模块负责人**：大数据分析工程师
- **技术栈**：FastAPI + MySQL + PyMySQL
- **数据规模**：210万+条记录

---

## 十一、更新日志

### v1.0.0 (2026-08-15)

- ✅ 实现维度组合选择接口
- ✅ 实现指标切换接口
- ✅ 实现逐级下钻接口
- ✅ 实现时间上卷接口
- ✅ 实现交叉透视接口
- ✅ 实现汇总统计接口
- ✅ 添加健康检查和元数据接口
- ✅ 完善项目文档
