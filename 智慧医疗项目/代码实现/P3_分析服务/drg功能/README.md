# DRG分析功能

智慧医疗数据分析平台 - DRG分析模块

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
| DRG费用排名 | `POST /api/v1/drg/cost-ranking` | 按DRG分组统计费用排名 |
| 住院天数对比 | `POST /api/v1/drg/stay-comparison` | 按DRG/诊断/严重程度对比 |
| 死亡风险对比 | `POST /api/v1/drg/mortality-risk` | 按风险等级统计分析 |
| CMI排名 | `POST /api/v1/drg/cmi-ranking` | 病例组合指数排名 |
| 离群识别 | `POST /api/v1/drg/outlier-detection` | 费用/住院天数异常检测 |
| DRG汇总 | `GET /api/v1/drg/summary` | DRG汇总统计信息 |
| 健康检查 | `GET /api/v1/drg/health` | 服务状态检查 |

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

服务将在 http://localhost:8001 启动

### 4. 访问API文档

- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

## API接口详情

### DRG费用排名

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
    "data": {
        "title": "DRG费用排名",
        "rows": [
            {
                "drg_code": 640,
                "drg_desc": "NEONATE BIRTH WEIGHT > 2499 GRAMS",
                "cases": 139203,
                "avg_charges": "13654.21"
            }
        ]
    }
}
```

### 住院天数对比

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

### 死亡风险对比

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

### CMI排名

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

**CMI说明：** 病例组合指数(Case Mix Index)，值越高表示病例复杂度越高

### 离群识别

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

**参数说明：**
- `metric`: 检测指标 (`avg_charges`, `avg_stay`, `cases`)
- `group_by`: 分组维度 (`drg`, `diagnosis`, `hospital`)
- `method`: 检测方法 (`iqr`四分位距, `zscore`Z分数)

## 数据说明

### DRG分组

DRG(Diagnosis Related Groups)是诊断相关分组，将相似的病例归为一组：

| 字段 | 说明 | 示例 |
|------|------|------|
| drg_code | DRG编码 | 560 |
| drg_desc | DRG描述 | VAGINAL DELIVERY |
| mdc_code | MDC大类编码 | 14 |
| mdc_desc | MDC大类描述 | PREGNANCY, CHILDBIRTH... |
| severity_desc | 严重程度 | Minor/Moderate/Major/Extreme |
| risk_mortality | 死亡风险 | Minor/Moderate/Major/Extreme |

### 数据库表结构

- `fact_discharge` - 事实表（210万条记录）
- `dim_drg` - DRG维度表（1285条记录）
- `dim_hospital` - 医院维度表
- `dim_patient` - 患者维度表
- `dim_diagnosis` - 诊断维度表

## 文件结构

```
drg功能/
├── main.py              # 独立入口
├── drg.py               # API路由
├── drg_service.py       # 业务逻辑
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
- Pandas (数据处理)

## 测试页面

使用 `test/drg_dashboard.html` 进行可视化测试

## 相关链接

- [核心分析功能](../核心功能/README.md)
