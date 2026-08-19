# 智慧医疗数据分析平台 - 实施计划

> 创建时间：2026-08-15
> 数据规模：210万+条记录
> 目标：实现维度组合选择、指标切换、逐级下钻、时间上卷、交叉透视五大功能

---

## 一、总体目标

基于星型模型架构，构建高性能的医疗数据分析后端，支持：
1. 维度组合选择 - 任意维度组合分析
2. 指标切换 - 多指标组快速切换
3. 逐级下钻 - 层次化数据探索
4. 时间上卷 - 时间维度聚合
5. 交叉透视 - 透视表生成

---

## 二、实施阶段

### 阶段1：数据层建设（预计2-3天）

#### 1.1 数据库设计
- [ ] 设计维度表DDL（8张）
- [ ] 设计事实表DDL（1张）
- [ ] 创建索引和分区策略
- [ ] 编写数据库初始化脚本

#### 1.2 ETL开发
- [ ] 数据清洗脚本（处理BOM、货币列、缺失值）
- [ ] 维度表构建脚本
- [ ] 事实表构建脚本
- [ ] 数据质量校验

#### 1.3 数据导入
- [ ] MySQL数据库创建
- [ ] 维度表数据导入
- [ ] 事实表数据导入（210万+）
- [ ] 数据完整性验证

**产出物：**
- `scripts/init_db.sql` - 数据库DDL
- `scripts/load_data.py` - 数据导入脚本
- `scripts/data_quality_check.py` - 数据质量检查
- `docs/database.md` - 数据库文档

---

### 阶段2：查询引擎建设（预计2天）

#### 2.1 SQL构建器
- [ ] 动态SQL生成器（支持任意维度组合）
- [ ] 参数化查询构建
- [ ] SQL注入防护
- [ ] 查询优化器

#### 2.2 数据访问层
- [ ] MySQL连接池管理
- [ ] 查询执行器
- [ ] 结果集转换器
- [ ] 异常处理

#### 2.3 缓存层
- [ ] Redis连接管理
- [ ] 查询结果缓存
- [ ] 缓存失效策略
- [ ] 缓存预热

**产出物：**
- `src/query/sql_builder.py` - SQL构建器
- `src/dao/mysql_dao.py` - MySQL数据访问
- `src/query/cache_manager.py` - 缓存管理

---

### 阶段3：API接口开发（预计3-4天）

#### 3.1 基础框架
- [ ] FastAPI应用框架搭建
- [ ] 路由注册
- [ ] 中间件配置
- [ ] 统一响应格式

#### 3.2 核心接口开发
- [ ] 维度组合选择接口
- [ ] 指标切换接口
- [ ] 逐级下钻接口
- [ ] 时间上卷接口
- [ ] 交叉透视接口

#### 3.3 辅助接口
- [ ] 健康检查接口
- [ ] 元数据接口（维度列表、指标列表）
- [ ] 缓存管理接口

**产出物：**
- `src/api/routes/dimension.py` - 维度组合接口
- `src/api/routes/metric.py` - 指标切换接口
- `src/api/routes/drill.py` - 逐级下钻接口
- `src/api/routes/time.py` - 时间上卷接口
- `src/api/routes/pivot.py` - 交叉透视接口

---

### 阶段4：业务逻辑层（预计2天）

#### 4.1 服务层开发
- [ ] 维度组合服务
- [ ] 指标切换服务
- [ ] 逐级下钻服务
- [ ] 时间上卷服务
- [ ] 交叉透视服务

#### 4.2 结果格式化
- [ ] ECharts配置生成
- [ ] 统计指标计算
- [ ] 数据聚合处理
- [ ] 分页处理

**产出物：**
- `src/services/dimension_service.py`
- `src/services/metric_service.py`
- `src/services/drill_service.py`
- `src/services/time_service.py`
- `src/services/pivot_service.py`

---

### 阶段5：优化与测试（预计2天）

#### 5.1 性能优化
- [ ] 数据库索引优化
- [ ] 查询性能调优
- [ ] 缓存策略优化
- [ ] 连接池调优

#### 5.2 单元测试
- [ ] 维度组合测试
- [ ] 指标切换测试
- [ ] 逐级下钻测试
- [ ] 时间上卷测试
- [ ] 交叉透视测试

#### 5.3 集成测试
- [ ] API接口测试
- [ ] 性能压力测试
- [ ] 数据准确性测试

**产出物：**
- `tests/` - 测试用例
- `docs/performance.md` - 性能报告
- `docs/api.md` - API文档

---

## 三、技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| 后端框架 | FastAPI | 异步、高性能、自动文档 |
| 数据库 | MySQL 8.0 | 主存储 |
| 缓存 | Redis | 查询结果缓存 |
| ORM | SQLAlchemy | 数据库访问 |
| 数据处理 | Pandas | 数据清洗 |
| 测试 | Pytest | 单元测试 |

---

## 四、数据库设计

### 4.1 维度表（8张）

```sql
-- 1. 医院维度
CREATE TABLE dim_hospital (
    hospital_id INT PRIMARY KEY AUTO_INCREMENT,
    facility_name VARCHAR(200),
    county VARCHAR(100),
    service_area VARCHAR(100),
    operating_cert_number VARCHAR(50),
    permanent_facility_id VARCHAR(50)
);

-- 2. 诊断维度
CREATE TABLE dim_diagnosis (
    diagnosis_id INT PRIMARY KEY AUTO_INCREMENT,
    ccsr_code VARCHAR(20),
    description VARCHAR(500)
);

-- 3. 手术维度
CREATE TABLE dim_procedure (
    procedure_id INT PRIMARY KEY AUTO_INCREMENT,
    ccsr_code VARCHAR(20),
    description VARCHAR(500)
);

-- 4. DRG维度
CREATE TABLE dim_drg (
    drg_id INT PRIMARY KEY AUTO_INCREMENT,
    drg_code INT,
    drg_desc VARCHAR(500),
    mdc_code INT,
    mdc_desc VARCHAR(500)
);

-- 5. 患者维度
CREATE TABLE dim_patient (
    patient_id INT PRIMARY KEY AUTO_INCREMENT,
    age_group VARCHAR(50),
    gender VARCHAR(10),
    race VARCHAR(50),
    ethnicity VARCHAR(50)
);

-- 6. 时间维度
CREATE TABLE dim_time (
    time_id INT PRIMARY KEY AUTO_INCREMENT,
    year INT,
    quarter INT,
    month INT,
    year_month VARCHAR(10)
);

-- 7. 支付方式维度
CREATE TABLE dim_payment (
    payment_id INT PRIMARY KEY AUTO_INCREMENT,
    payment_type VARCHAR(100)
);

-- 8. 严重程度维度
CREATE TABLE dim_severity (
    severity_id INT PRIMARY KEY AUTO_INCREMENT,
    severity_code INT,
    severity_desc VARCHAR(100),
    risk_mortality VARCHAR(50)
);
```

### 4.2 事实表（1张）

```sql
CREATE TABLE fact_inpatient_discharge (
    discharge_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    
    -- 外键
    hospital_id INT,
    diagnosis_id INT,
    procedure_id INT,
    drg_id INT,
    patient_id INT,
    time_id INT,
    payment_id INT,
    severity_id INT,
    
    -- 度量值
    total_charges DECIMAL(15,2),
    total_costs DECIMAL(15,2),
    length_of_stay INT,
    birth_weight INT,
    
    -- 其他属性
    zip_code VARCHAR(10),
    admission_type VARCHAR(50),
    patient_disposition VARCHAR(100),
    ed_indicator CHAR(1),
    medical_surgical VARCHAR(20),
    
    -- 外键约束
    FOREIGN KEY (hospital_id) REFERENCES dim_hospital(hospital_id),
    FOREIGN KEY (diagnosis_id) REFERENCES dim_diagnosis(diagnosis_id),
    FOREIGN KEY (procedure_id) REFERENCES dim_procedure(procedure_id),
    FOREIGN KEY (drg_id) REFERENCES dim_drg(drg_id),
    FOREIGN KEY (patient_id) REFERENCES dim_patient(patient_id),
    FOREIGN KEY (time_id) REFERENCES dim_time(time_id),
    FOREIGN KEY (payment_id) REFERENCES dim_payment(payment_id),
    FOREIGN KEY (severity_id) REFERENCES dim_severity(severity_id)
);
```

---

## 五、API接口设计

### 5.1 维度组合选择

```http
POST /api/v1/analysis/dimension-combine
```

**请求：**
```json
{
    "dimensions": ["hospital", "age_group", "gender"],
    "metrics": ["cases", "total_charges", "avg_charges"],
    "filters": {
        "year": 2021,
        "region": "New York City"
    },
    "sort": {"field": "total_charges", "order": "desc"},
    "limit": 100
}
```

**响应：**
```json
{
    "code": 200,
    "data": {
        "columns": ["hospital", "age_group", "gender", "cases", "total_charges", "avg_charges"],
        "rows": [
            ["Montefiore", "70 or Older", "M", 1234, 9876543, 7998.5]
        ],
        "echarts": { ... }
    }
}
```

### 5.2 指标切换

```http
POST /api/v1/analysis/metric-switch
```

**请求：**
```json
{
    "dimensions": ["hospital"],
    "metric_groups": {
        "financial": ["total_charges", "total_costs", "cost_ratio"],
        "operational": ["cases", "avg_stay"],
        "quality": ["mortality_rate"]
    },
    "filters": {"year": 2021}
}
```

### 5.3 逐级下钻

```http
POST /api/v1/analysis/drill-down
```

**请求：**
```json
{
    "current_level": "region",
    "current_value": "New York City",
    "drill_to": "county",
    "metrics": ["cases", "total_charges"],
    "filters": {"year": 2021}
}
```

**响应：**
```json
{
    "code": 200,
    "data": {
        "breadcrumb": ["New York City"],
        "current_level": "county",
        "rows": [
            {"county": "Bronx", "cases": 12345, "total_charges": 987654321},
            {"county": "Kings", "cases": 23456, "total_charges": 1234567890}
        ],
        "next_level": "hospital"
    }
}
```

### 5.4 时间上卷

```http
POST /api/v1/analysis/time-rollup
```

**请求：**
```json
{
    "time_level": "month",
    "metrics": ["cases", "total_charges"],
    "filters": {
        "year_start": 2020,
        "year_end": 2021
    },
    "compare_previous": true
}
```

### 5.5 交叉透视

```http
POST /api/v1/analysis/pivot
```

**请求：**
```json
{
    "row_dimension": "age_group",
    "col_dimension": "gender",
    "metric": "avg_charges",
    "filters": {"year": 2021}
}
```

---

## 六、目录结构

```
smart-medical-analysis-platform/
│
├── config/
│   ├── __init__.py
│   ├── config.py
│   └── database.py
│
├── src/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── dimension.py
│   │   │   ├── metric.py
│   │   │   ├── drill.py
│   │   │   ├── time.py
│   │   │   └── pivot.py
│   │   └── middleware/
│   │       ├── __init__.py
│   │       ├── error_handler.py
│   │       └── validator.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── dimension_service.py
│   │   ├── metric_service.py
│   │   ├── drill_service.py
│   │   ├── time_service.py
│   │   └── pivot_service.py
│   │
│   ├── query/
│   │   ├── __init__.py
│   │   ├── sql_builder.py
│   │   └── cache_manager.py
│   │
│   ├── dao/
│   │   ├── __init__.py
│   │   └── mysql_dao.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── response.py
│       └── decorators.py
│
├── etl/
│   ├── __init__.py
│   ├── data_cleaner.py
│   ├── dimension_builder.py
│   └── fact_builder.py
│
├── scripts/
│   ├── init_db.sql
│   ├── load_data.py
│   └── data_quality_check.py
│
├── tests/
│   ├── __init__.py
│   ├── test_dimension.py
│   ├── test_metric.py
│   ├── test_drill.py
│   ├── test_time.py
│   └── test_pivot.py
│
├── docs/
│   ├── api.md
│   ├── database.md
│   └── performance.md
│
├── requirements.txt
├── .env
├── .gitignore
└── README.md
```

---

## 七、执行顺序

### Day 1-2：数据层
1. 创建数据库和表结构
2. 开发ETL脚本
3. 导入数据
4. 验证数据质量

### Day 3-4：查询引擎
1. 开发SQL构建器
2. 实现数据访问层
3. 配置缓存

### Day 5-6：API接口
1. 搭建FastAPI框架
2. 实现5个核心接口
3. 实现辅助接口

### Day 7-8：业务逻辑
1. 实现5个服务层
2. 结果格式化
3. ECharts配置生成

### Day 9-10：优化测试
1. 性能优化
2. 单元测试
3. 集成测试
4. 文档编写

---

## 八、风险与应对

| 风险 | 应对措施 |
|------|----------|
| 数据导入慢 | 分批导入、并行处理 |
| 查询性能差 | 索引优化、物化视图 |
| 内存不足 | 分页查询、流式处理 |
| 缓存失效 | 多级缓存、预热策略 |

---

## 九、验收标准

1. **功能完整性**：5个核心接口全部实现
2. **性能指标**：简单查询<1秒，复杂查询<3秒
3. **数据准确性**：与原始数据一致
4. **代码质量**：单元测试覆盖率>80%
5. **文档完整性**：API文档、数据库文档齐全

---

## 十、下一步行动

**立即开始阶段1：数据层建设**

1. 创建数据库表结构
2. 开发数据清洗脚本
3. 构建维度表
4. 导入事实表数据

准备好了吗？我将从创建数据库表结构开始。
