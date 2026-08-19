# 智慧医疗大数据分析平台 - 模块二：分析服务开发 代码架构设计

> 负责人：大数据分析工程师
> 技术栈：Hadoop 3.3.4 / Spark 3.5.4 / Hive 3.1.3 / Flask 3.0.3 / Redis 7.0.15 / Python 3.11

---

## 一、项目总目录结构

```
data-analysis/
│
├── ARCHITECTURE.md                  # 本文档 - 代码架构设计
├── README.md                        # 项目说明
├── requirements.txt                 # Python 依赖
├── config.py                        # 全局配置文件
├── .env                             # 环境变量（不提交Git）
├── .gitignore
│
├── app.py                           # Flask 应用入口
├── wsgi.py                          # WSGI 生产入口（Gunicorn）
│
├── api/                             # ===== API 接口层 =====
│   ├── __init__.py
│   ├── routes/                      # 路由蓝图
│   │   ├── __init__.py
│   │   ├── expense_routes.py        # 医疗费用分析 API
│   │   ├── disease_routes.py        # 疾病分布分析 API
│   │   ├── department_routes.py     # 科室绩效分析 API
│   │   ├── trend_routes.py          # 时间趋势分析 API
│   │   ├── region_routes.py         # 区域分析 API
│   │   ├── overview_routes.py       # 总览概览 API
│   │   ├── algorithm_routes.py      # 算法分析 API
│   │   └── health_routes.py         # 健康检查 API
│   ├── middleware/                   # 中间件
│   │   ├── __init__.py
│   │   ├── auth.py                  # 认证中间件
│   │   ├── rate_limiter.py          # 限流中间件
│   │   └── error_handler.py         # 全局异常处理
│   ├── schemas/                     # 请求/响应数据模型
│   │   ├── __init__.py
│   │   ├── request_schemas.py       # 请求参数校验
│   │   └── response_schemas.py      # 响应格式定义
│   └── validators/                  # 参数校验器
│       ├── __init__.py
│       └── param_validators.py
│
├── services/                        # ===== 业务逻辑层 =====
│   ├── __init__.py
│   ├── expense_service.py           # 医疗费用分析服务
│   ├── disease_service.py           # 疾病分布分析服务
│   ├── department_service.py        # 科室绩效分析服务
│   ├── trend_service.py             # 时间趋势分析服务
│   ├── region_service.py            # 区域分析服务
│   ├── overview_service.py          # 总览数据服务
│   └── algorithm_service.py         # 算法分析服务
│
├── analytics/                       # ===== 分析引擎层 =====
│   ├── __init__.py
│   ├── engine.py                    # Spark 分析引擎（SparkSession 管理）
│   ├── queries/                     # Spark SQL 查询集合
│   │   ├── __init__.py
│   │   ├── expense_queries.py       # 费用相关 SQL
│   │   ├── disease_queries.py       # 疾病相关 SQL
│   │   ├── department_queries.py    # 科室相关 SQL
│   │   ├── trend_queries.py         # 趋势相关 SQL
│   │   └── region_queries.py        # 区域相关 SQL
│   └── transformers/                # 结果转换器
│       ├── __init__.py
│       ├── echarts_transformer.py   # 转换为 ECharts 格式
│       └── stats_transformer.py     # 统计指标计算（同比/环比/占比）
│
├── algorithms/                      # ===== 算法库 =====
│   ├── __init__.py
│   ├── descriptive_stats.py         # 描述性统计
│   ├── correlation.py               # 相关性分析
│   ├── trend_prediction.py          # 趋势预测
│   ├── anomaly_detection.py         # 异常检测
│   ├── clustering.py                # 聚类分析
│   └── docs/                        # 算法使用文档
│       └── algorithm_guide.md       # 算法库使用说明
│
├── cache/                           # ===== 缓存层 =====
│   ├── __init__.py
│   ├── redis_client.py              # Redis 连接管理
│   ├── cache_manager.py             # 缓存策略管理
│   └── cache_keys.py                # 缓存键常量定义
│
├── models/                          # ===== 数据模型层 =====
│   ├── __init__.py
│   ├── patient.py                   # 患者数据模型
│   ├── diagnosis.py                 # 诊断数据模型
│   ├── expense.py                   # 费用数据模型
│   └── hospital.py                  # 医院数据模型
│
├── dao/                             # ===== 数据访问层 =====
│   ├── __init__.py
│   ├── mysql_dao.py                 # MySQL 数据访问
│   ├── hive_dao.py                  # Hive 数据访问
│   └── spark_dao.py                 # Spark DataFrame 数据访问
│
├── etl/                             # ===== 数据预处理模块 =====
│   ├── __init__.py
│   ├── data_loader.py               # CSV 数据加载
│   ├── data_cleaner.py              # 数据清洗
│   ├── data_transformer.py          # 数据转换/标准化
│   ├── schema_definer.py            # 字段 Schema 定义
│   └── data_validator.py            # 数据质量校验
│
├── utils/                           # ===== 工具函数 =====
│   ├── __init__.py
│   ├── logger.py                    # 日志工具
│   ├── response.py                  # 统一响应封装
│   ├── decorators.py                # 通用装饰器（缓存、计时、重试）
│   └── constants.py                 # 常量定义
│
├── tests/                           # ===== 测试 =====
│   ├── __init__.py
│   ├── conftest.py                  # 测试配置（pytest fixtures）
│   ├── test_expense_api.py          # 费用 API 测试
│   ├── test_disease_api.py          # 疾病 API 测试
│   ├── test_department_api.py       # 科室 API 测试
│   ├── test_trend_api.py            # 趋势 API 测试
│   ├── test_region_api.py           # 区域 API 测试
│   ├── test_algorithms.py           # 算法库测试
│   └── test_cache.py                # 缓存测试
│
├── scripts/                         # ===== 脚本 =====
│   ├── init_db.py                   # 数据库初始化
│   ├── load_data.py                 # 数据导入脚本
│   ├── benchmark.py                 # 性能基准测试
│   └── generate_docs.py             # 文档生成
│
├── data/                            # ===== 数据文件 =====
│   ├── raw/                         # 原始数据
│   │   └── Hospital_Inpatient_Discharges__SPARCS_De-Identified___2021_20231012.csv
│   ├── processed/                   # 清洗后数据
│   └── sample/                      # 测试用样本数据
│
├── logs/                            # ===== 日志 =====
│   └── app.log
│
└── docs/                            # ===== 文档 =====
    ├── api_documentation.md         # API 接口文档
    ├── data_access_guide.md         # 前端数据接入指南
    ├── performance_report.md        # 性能优化报告
    └── deployment_guide.md          # 部署指南
```

---

## 二、分层架构详解

### 架构分层图

```
┌─────────────────────────────────────────────────────────────────┐
│                     展示层 (Vue / ECharts)                       │
│                    前端工程师负责，不在本模块范围                    │
├─────────────────────────────────────────────────────────────────┤
│                      API 接口层 (api/)                           │
│   Flask Blueprint 路由 → 参数校验 → 调用 Service → 返回 JSON     │
├─────────────────────────────────────────────────────────────────┤
│                     业务逻辑层 (services/)                       │
│   组合多个 Analytics 查询 → 统计指标计算 → 结果格式化              │
├─────────────────────────────────────────────────────────────────┤
│                     分析引擎层 (analytics/)                      │
│   SparkSession 管理 → Spark SQL 查询 → 结果转换为 ECharts 格式   │
├─────────────────────────────────────────────────────────────────┤
│                       算法库 (algorithms/)                       │
│   独立算法模块 → 参数化调用 → 标准化结果输出                       │
├─────────────────────────────────────────────────────────────────┤
│                       缓存层 (cache/)                            │
│   Redis 连接池 → 缓存策略 → 热点查询缓存                          │
├─────────────────────────────────────────────────────────────────┤
│                     数据访问层 (dao/ + etl/)                      │
│   MySQL / Hive / Spark DataFrame → 数据读写                      │
├─────────────────────────────────────────────────────────────────┤
│                       数据源层 (data/)                           │
│   CSV 原始数据 → 清洗后数据 → MySQL / Hive 存储                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、核心文件详细设计

### 3.1 Flask 应用入口 `app.py`

```python
"""
Flask 应用入口
职责：初始化 Flask 应用、注册蓝图、配置扩展、启动服务
"""
from flask import Flask
from flask_cors import CORS

def create_app(config_name='development'):
    """应用工厂函数"""
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # 1. 初始化扩展
    CORS(app)                           # 跨域支持
    init_redis(app)                     # Redis 连接
    init_logger(app)                    # 日志系统
    init_error_handlers(app)            # 全局异常处理

    # 2. 注册蓝图（API 路由）
    from api.routes import (
        expense_bp, disease_bp, department_bp,
        trend_bp, region_bp, overview_bp,
        algorithm_bp, health_bp
    )
    app.register_blueprint(expense_bp,      url_prefix='/api/v1/expense')
    app.register_blueprint(disease_bp,      url_prefix='/api/v1/disease')
    app.register_blueprint(department_bp,   url_prefix='/api/v1/department')
    app.register_blueprint(trend_bp,        url_prefix='/api/v1/trend')
    app.register_blueprint(region_bp,       url_prefix='/api/v1/region')
    app.register_blueprint(overview_bp,     url_prefix='/api/v1/overview')
    app.register_blueprint(algorithm_bp,    url_prefix='/api/v1/algorithm')
    app.register_blueprint(health_bp,       url_prefix='/api/v1/health')

    # 3. 初始化 Spark 引擎
    from analytics.engine import SparkEngine
    app.spark_engine = SparkEngine.get_instance()

    return app
```

### 3.2 全局配置 `config.py`

```python
"""
全局配置
"""
import os

class Config:
    """基础配置"""
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    JSON_AS_ASCII = False               # 支持中文返回

    # Redis
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)
    CACHE_DEFAULT_TIMEOUT = 300         # 默认缓存 5 分钟

    # MySQL
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
    MYSQL_USER = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
    MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'medical_analysis')

    # Spark
    SPARK_APP_NAME = 'MedicalAnalysisEngine'
    SPARK_MASTER = os.getenv('SPARK_MASTER', 'local[*]')
    SPARK_DRIVER_MEMORY = '2g'
    SPARK_EXECUTOR_MEMORY = '4g'
    SPARK_SQL_SHUFFLE_PARTITIONS = 8
    SPARK_SQL_AUTO_BROADCASTJOIN_THRESHOLD = 10 * 1024 * 1024  # 10MB

    # Hive
    HIVE_METASTORE_URI = os.getenv('HIVE_METASTORE_URI', 'thrift://localhost:9083')
    HIVE_WAREHOUSE_DIR = '/user/hive/warehouse'

    # 数据文件
    DATA_RAW_PATH = 'data/raw/Hospital_Inpatient_Discharges__SPARCS_De-Identified___2021_20231012.csv'
    DATA_PROCESSED_PATH = 'data/processed/'

    # API 限流
    RATE_LIMIT_DEFAULT = '100/minute'

class DevelopmentConfig(Config):
    DEBUG = True
    SPARK_MASTER = 'local[2]'

class ProductionConfig(Config):
    DEBUG = False
    SPARK_MASTER = 'yarn'

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
}
```

### 3.3 Spark 分析引擎 `analytics/engine.py`

```python
"""
Spark 分析引擎 - 核心单件
职责：管理 SparkSession 生命周期、提供 Spark SQL 执行能力
"""
from pyspark.sql import SparkSession
import atexit

class SparkEngine:
    """Spark 分析引擎单例"""
    _instance = None

    @classmethod
    def get_instance(cls, config=None):
        if cls._instance is None:
            cls._instance = cls._create(config)
        return cls._instance

    @classmethod
    def _create(cls, config):
        """创建 SparkSession"""
        builder = SparkSession.builder \
            .appName(config.SPARK_APP_NAME if config else 'MedicalAnalysis') \
            .config('spark.driver.memory', '2g') \
            .config('spark.executor.memory', '4g') \
            .config('spark.sql.shuffle.partitions', 8) \
            .config('spark.sql.autoBroadcastJoinThreshold', 10 * 1024 * 1024) \
            .config('spark.sql.adaptive.enabled', 'true') \
            .config('spark.sql.adaptive.coalescePartitions.enabled', 'true')

        if config and hasattr(config, 'HIVE_METASTORE_URI'):
            builder = builder \
                .config('hive.metastore.uris', config.HIVE_METASTORE_URI) \
                .enableHiveSupport()

        spark = builder.getOrCreate()
        spark.sparkContext.setLogLevel('WARN')

        # 注册退出清理
        atexit.register(lambda: spark.stop())

        return spark

    def execute_sql(self, sql, params=None):
        """执行 Spark SQL 并返回结果"""
        spark = self._instance
        if params:
            sql = sql.format(**params)
        return spark.sql(sql)

    def read_table(self, table_name):
        """读取表数据为 DataFrame"""
        return self._instance.table(table_name)

    def register_temp_view(self, df, view_name):
        """注册临时视图"""
        df.createOrReplaceTempView(view_name)
```

### 3.4 API 路由示例 `api/routes/expense_routes.py`

```python
"""
医疗费用分析 API 路由
接口数量：5 个
"""
from flask import Blueprint, request, current_app
from services.expense_service import ExpenseService
from utils.response import success, error
from utils.decorators import cache_result, log_execution_time

expense_bp = Blueprint('expense', __name__)
expense_service = ExpenseService()

@expense_bp.route('/summary', methods=['GET'])
@cache_result(timeout=300)
@log_execution_time
def get_expense_summary():
    """
    GET /api/v1/expense/summary
    费用总览：总费用、平均费用、中位数、费用分布
    参数：
      - year: 出院年份（可选）
      - region: 医院区域（可选）
      - department: 科室/MDC（可选）
      - age_group: 年龄段（可选）
    """
    filters = {
        'year': request.args.get('year'),
        'region': request.args.get('region'),
        'department': request.args.get('department'),
        'age_group': request.args.get('age_group'),
    }
    # 过滤 None 值
    filters = {k: v for k, v in filters.items() if v is not None}
    result = expense_service.get_summary(filters)
    return success(data=result)

@expense_bp.route('/by-insurance', methods=['GET'])
@cache_result(timeout=300)
@log_execution_time
def get_expense_by_insurance():
    """
    GET /api/v1/expense/by-insurance
    按支付方式分析：各保险类型的费用统计、占比、排名
    参数：
      - year, region, department（筛选条件）
    """
    filters = _extract_filters(request)
    result = expense_service.get_by_insurance(filters)
    return success(data=result)

@expense_bp.route('/by-age-gender', methods=['GET'])
@cache_result(timeout=300)
@log_execution_time
def get_expense_by_age_gender():
    """
    GET /api/v1/expense/by-age-gender
    按年龄+性别分析：各组合的平均费用、总费用
    """
    filters = _extract_filters(request)
    result = expense_service.get_by_age_gender(filters)
    return success(data=result)

@expense_bp.route('/cost-ratio', methods=['GET'])
@cache_result(timeout=300)
@log_execution_time
def get_cost_ratio():
    """
    GET /api/v1/expense/cost-ratio
    费用-成本比率分析：各科室/疾病的成本收益率
    """
    filters = _extract_filters(request)
    result = expense_service.get_cost_ratio(filters)
    return success(data=result)

@expense_bp.route('/ranking', methods=['GET'])
@cache_result(timeout=300)
@log_execution_time
def get_expense_ranking():
    """
    GET /api/v1/expense/ranking
    费用排名：按医院/科室/疾病维度的费用 Top N
    参数：
      - dimension: hospital|department|disease（默认 hospital）
      - top_n: 返回数量（默认 10）
      - metric: total|avg|median（默认 total）
    """
    filters = _extract_filters(request)
    dimension = request.args.get('dimension', 'hospital')
    top_n = int(request.args.get('top_n', 10))
    metric = request.args.get('metric', 'total')
    result = expense_service.get_ranking(filters, dimension, top_n, metric)
    return success(data=result)


def _extract_filters(req):
    """提取通用筛选参数"""
    return {k: v for k, v in {
        'year': req.args.get('year'),
        'region': req.args.get('region'),
        'department': req.args.get('department'),
        'age_group': req.args.get('age_group'),
        'disease': req.args.get('disease'),
        'severity': req.args.get('severity'),
    }.items() if v is not None}
```

### 3.5 业务逻辑层 `services/expense_service.py`

```python
"""
医疗费用分析服务
职责：组合多个查询、计算统计指标、格式化返回结果
"""
from analytics.queries.expense_queries import ExpenseQueries
from analytics.transformers.stats_transformer import StatsTransformer
from analytics.transformers.echarts_transformer import EChartsTransformer
from cache.cache_manager import CacheManager

class ExpenseService:
    def __init__(self):
        self.queries = ExpenseQueries()
        self.stats = StatsTransformer()
        self.echarts = EChartsTransformer()
        self.cache = CacheManager()

    def get_summary(self, filters=None):
        """
        费用总览分析
        返回：{
            "summary": { "total_charges": ..., "avg_charges": ..., "median_charges": ..., "total_records": ... },
            "distribution": { ... },   # 费用分布直方图数据
            "echarts": { ... }         # ECharts 图表配置
        }
        """
        # 1. 查询原始数据
        df = self.queries.get_charges_summary(filters)

        # 2. 计算统计指标
        summary = {
            'total_charges': df.agg({'Total_Charges': 'sum'}).collect()[0][0],
            'avg_charges': df.agg({'Total_Charges': 'avg'}).collect()[0][0],
            'median_charges': self.stats.calc_median(df, 'Total_Charges'),
            'total_records': df.count(),
        }

        # 3. 费用分布（直方图）
        distribution = self.stats.calc_distribution(df, 'Total_Charges', bins=20)

        # 4. 转换为 ECharts 格式
        echarts_config = self.echarts.to_bar_chart(
            x_data=distribution['labels'],
            y_data=distribution['counts'],
            title='住院费用分布',
            x_label='费用区间（美元）',
            y_label='患者数量'
        )

        return {
            'summary': summary,
            'distribution': distribution,
            'echarts': echarts_config,
        }

    def get_by_insurance(self, filters=None):
        """按保险类型分析费用"""
        df = self.queries.get_charges_by_insurance(filters)

        # 计算占比和排名
        result = self.stats.calc_percentage(df, 'Payment_Typology_1', 'total_charges')
        result = self.stats.add_ranking(result, 'total_charges')

        # ECharts 饼图
        echarts_config = self.echarts.to_pie_chart(
            names=[r['Payment_Typology_1'] for r in result],
            values=[r['total_charges'] for r in result],
            title='各支付方式费用占比'
        )

        return {'data': result, 'echarts': echarts_config}

    def get_by_age_gender(self, filters=None):
        """按年龄+性别分析"""
        df = self.queries.get_charges_by_age_gender(filters)
        result = self.stats.calc_group_stats(df, ['Age_Group', 'Gender'], 'Total_Charges')
        echarts_config = self.echarts.to_grouped_bar(
            data=result,
            group_field='Age_Group',
            series_field='Gender',
            value_field='avg_charges',
            title='各年龄段男女平均住院费用'
        )
        return {'data': result, 'echarts': echarts_config}

    def get_cost_ratio(self, filters=None):
        """费用-成本比率分析"""
        df = self.queries.get_cost_ratio(filters)
        result = self.stats.calc_ratio(df, 'Total_Charges', 'Total_Costs', 'cost_ratio')
        echarts_config = self.echarts.to_scatter_chart(
            data=result,
            x_field='Total_Charges',
            y_field='Total_Costs',
            title='费用 vs 成本散点图'
        )
        return {'data': result, 'echarts': echarts_config}

    def get_ranking(self, filters, dimension, top_n, metric):
        """费用排名"""
        df = self.queries.get_ranking_data(filters, dimension, metric)
        result = self.stats.calc_top_n(df, top_n, metric)
        echarts_config = self.echarts.to_bar_chart(
            x_data=[r[dimension] for r in result],
            y_data=[r[metric] for r in result],
            title=f'{dimension} 费用排名 Top {top_n}'
        )
        return {'data': result, 'echarts': echarts_config}
```

### 3.6 Spark SQL 查询 `analytics/queries/expense_queries.py`

```python
"""
医疗费用相关 Spark SQL 查询
"""
from analytics.engine import SparkEngine

class ExpenseQueries:
    def __init__(self):
        self.engine = SparkEngine.get_instance()

    def get_charges_summary(self, filters=None):
        """费用总览查询"""
        sql = """
        SELECT
            SUM(CAST(REPLACE(Total_Charges, ',', '') AS DOUBLE)) as total_charges,
            AVG(CAST(REPLACE(Total_Charges, ',', '') AS DOUBLE)) as avg_charges,
            COUNT(*) as total_records
        FROM medical_data
        WHERE 1=1
        """
        sql = self._apply_filters(sql, filters)
        return self.engine.execute_sql(sql)

    def get_charges_by_insurance(self, filters=None):
        """按保险类型统计费用"""
        sql = """
        SELECT
            `Payment_Typology 1` as Payment_Typology_1,
            COUNT(*) as patient_count,
            SUM(CAST(REPLACE(Total_Charges, ',', '') AS DOUBLE)) as total_charges,
            AVG(CAST(REPLACE(Total_Charges, ',', '') AS DOUBLE)) as avg_charges
        FROM medical_data
        WHERE `Payment_Typology 1` IS NOT NULL AND `Payment_Typology 1` != ''
        """
        sql = self._apply_filters(sql, filters)
        sql += " GROUP BY `Payment_Typology 1` ORDER BY total_charges DESC"
        return self.engine.execute_sql(sql)

    def get_charges_by_age_gender(self, filters=None):
        """按年龄+性别统计"""
        sql = """
        SELECT
            `Age_Group`,
            Gender,
            COUNT(*) as patient_count,
            SUM(CAST(REPLACE(Total_Charges, ',', '') AS DOUBLE)) as total_charges,
            AVG(CAST(REPLACE(Total_Charges, ',', '') AS DOUBLE)) as avg_charges
        FROM medical_data
        WHERE `Age_Group` IS NOT NULL AND Gender IS NOT NULL
        """
        sql = self._apply_filters(sql, filters)
        sql += " GROUP BY `Age_Group`, Gender ORDER BY `Age_Group`, Gender"
        return self.engine.execute_sql(sql)

    def get_cost_ratio(self, filters=None):
        """费用-成本比率"""
        sql = """
        SELECT
            `APR MDC Description` as department,
            COUNT(*) as cases,
            SUM(CAST(REPLACE(Total_Charges, ',', '') AS DOUBLE)) as total_charges,
            SUM(CAST(REPLACE(Total_Costs, ',', '') AS DOUBLE)) as total_costs
        FROM medical_data
        WHERE Total_Charges IS NOT NULL AND Total_Costs IS NOT NULL
        """
        sql = self._apply_filters(sql, filters)
        sql += " GROUP BY `APR MDC Description` ORDER BY total_charges DESC"
        return self.engine.execute_sql(sql)

    def get_ranking_data(self, filters, dimension, metric):
        """排名数据"""
        dimension_map = {
            'hospital': '`Facility Name`',
            'department': '`APR MDC Description`',
            'disease': '`CCSR Diagnosis Description`',
        }
        col = dimension_map.get(dimension, '`Facility Name`')
        metric_col = 'Total_Charges' if metric == 'total' else 'Total_Charges'

        sql = f"""
        SELECT
            {col} as dimension_key,
            COUNT(*) as cases,
            SUM(CAST(REPLACE({metric_col}, ',', '') AS DOUBLE)) as total,
            AVG(CAST(REPLACE({metric_col}, ',', '') AS DOUBLE)) as avg_val
        FROM medical_data
        WHERE {col} IS NOT NULL
        """
        sql = self._apply_filters(sql, filters)
        sql += f" GROUP BY {col} ORDER BY total DESC"
        return self.engine.execute_sql(sql)

    def _apply_filters(self, sql, filters):
        """动态拼接筛选条件"""
        if not filters:
            return sql
        filter_map = {
            'year': ("`Discharge Year` = {year}", lambda v: v),
            'region': ("`Hospital Service Area` = '{region}'", lambda v: v),
            'department': ("`APR MDC Description` LIKE '%{department}%'", lambda v: v),
            'age_group': ("`Age_Group` = '{age_group}'", lambda v: v),
            'disease': ("`CCSR Diagnosis Description` LIKE '%{disease}%'", lambda v: v),
            'severity': ("`APR Severity of Illness Description` = '{severity}'", lambda v: v),
        }
        for key, value in filters.items():
            if key in filter_map and value:
                template, _ = filter_map[key]
                sql += f" AND {template.format(**{key: value})}"
        return sql
```

### 3.7 ECharts 转换器 `analytics/transformers/echarts_transformer.py`

```python
"""
ECharts 图表配置转换器
职责：将分析结果转换为前端可直接渲染的 ECharts option 配置
"""
class EChartsTransformer:
    """将数据转换为标准 ECharts 配置"""

    def to_bar_chart(self, x_data, y_data, title='', x_label='', y_label=''):
        """柱状图配置"""
        return {
            'type': 'bar',
            'title': {'text': title, 'left': 'center'},
            'tooltip': {'trigger': 'axis'},
            'xAxis': {
                'type': 'category',
                'data': x_data,
                'name': x_label,
                'axisLabel': {'rotate': 30 if len(x_data) > 6 else 0}
            },
            'yAxis': {'type': 'value', 'name': y_label},
            'series': [{'data': y_data, 'type': 'bar', 'itemStyle': {'borderRadius': [4, 4, 0, 0]}}]
        }

    def to_line_chart(self, x_data, series_list, title=''):
        """
        折线图配置（支持多系列）
        series_list: [{'name': '系列1', 'data': [...]}, ...]
        """
        return {
            'type': 'line',
            'title': {'text': title, 'left': 'center'},
            'tooltip': {'trigger': 'axis'},
            'legend': {'data': [s['name'] for s in series_list], 'bottom': 0},
            'xAxis': {'type': 'category', 'data': x_data},
            'yAxis': {'type': 'value'},
            'series': [{'name': s['name'], 'type': 'line', 'data': s['data'], 'smooth': True}
                       for s in series_list]
        }

    def to_pie_chart(self, names, values, title=''):
        """饼图配置"""
        data = [{'name': n, 'value': v} for n, v in zip(names, values)]
        return {
            'type': 'pie',
            'title': {'text': title, 'left': 'center'},
            'tooltip': {'trigger': 'item', 'formatter': '{b}: {c} ({d}%)'},
            'legend': {'orient': 'vertical', 'left': 'left'},
            'series': [{
                'type': 'pie',
                'radius': '55%',
                'data': data,
                'emphasis': {'itemStyle': {'shadowBlur': 10, 'shadowOffsetX': 0, 'shadowColor': 'rgba(0, 0, 0, 0.5)'}}
            }]
        }

    def to_grouped_bar(self, data, group_field, series_field, value_field, title=''):
        """分组柱状图"""
        groups = list(set(d[group_field] for d in data))
        series_names = list(set(d[series_field] for d in data))
        series = []
        for sn in series_names:
            series_data = [next((d[value_field] for d in data if d[group_field] == g and d[series_field] == sn), 0)
                          for g in groups]
            series.append({'name': sn, 'type': 'bar', 'data': series_data})
        return {
            'type': 'grouped_bar',
            'title': {'text': title, 'left': 'center'},
            'xAxis': {'type': 'category', 'data': groups},
            'yAxis': {'type': 'value'},
            'legend': {'data': series_names},
            'series': series
        }

    def to_scatter_chart(self, data, x_field, y_field, title=''):
        """散点图配置"""
        points = [[d[x_field], d[y_field]] for d in data]
        return {
            'type': 'scatter',
            'title': {'text': title, 'left': 'center'},
            'xAxis': {'type': 'value', 'name': x_field},
            'yAxis': {'type': 'value', 'name': y_field},
            'series': [{'type': 'scatter', 'data': points}]
        }

    def to_heatmap(self, x_labels, y_labels, values, title=''):
        """热力图配置（用于疾病×区域等交叉分析）"""
        return {
            'type': 'heatmap',
            'title': {'text': title, 'left': 'center'},
            'xAxis': {'type': 'category', 'data': x_labels},
            'yAxis': {'type': 'category', 'data': y_labels},
            'visualMap': {'min': 0, 'max': max(v[2] for v in values) if values else 100, 'calculable': True},
            'series': [{'type': 'heatmap', 'data': values}]
        }
```

### 3.8 统计转换器 `analytics/transformers/stats_transformer.py`

```python
"""
统计指标计算转换器
职责：计算同比、环比、占比、排名等统计指标
"""
from pyspark.sql import functions as F
from pyspark.sql.window import Window
import numpy as np

class StatsTransformer:
    """统计指标计算器"""

    def calc_median(self, df, column):
        """计算中位数（近似）"""
        approx_median = df.approxQuantile(column, [0.5], 0.01)
        return approx_median[0] if approx_median else 0

    def calc_distribution(self, df, column, bins=20):
        """计算频率分布（直方图数据）"""
        values = df.select(column).rdd.flatMap(lambda x: x).collect()
        counts, bin_edges = np.histogram(values, bins=bins)
        labels = [f'{int(bin_edges[i])}-{int(bin_edges[i+1])}' for i in range(len(counts))]
        return {'labels': labels, 'counts': counts.tolist(), 'bin_edges': bin_edges.tolist()}

    def calc_percentage(self, df, group_col, value_col):
        """计算各组占比"""
        total = df.agg({value_col: 'sum'}).collect()[0][0]
        result = df.withColumn('percentage',
            F.round(F.col(value_col) / F.lit(total) * 100, 2))
        return [row.asDict() for row in result.collect()]

    def calc_group_stats(self, df, group_cols, value_col):
        """分组统计：计数、求和、均值、最大、最小"""
        result = df.groupBy(*group_cols).agg(
            F.count('*').alias('count'),
            F.sum(value_col).alias('total'),
            F.avg(value_col).alias('avg'),
            F.max(value_col).alias('max'),
            F.min(value_col).alias('min'),
        )
        return [row.asDict() for row in result.collect()]

    def calc_yoy(self, df, time_col, value_col):
        """
        同比计算（Year over Year）
        假设 time_col 为年份
        """
        window = Window.orderBy(time_col)
        result = df.withColumn('prev_value', F.lag(value_col).over(window))
        result = result.withColumn('yoy_rate',
            F.round((F.col(value_col) - F.col('prev_value')) / F.col('prev_value') * 100, 2))
        return [row.asDict() for row in result.collect()]

    def calc_mom(self, df, time_col, value_col):
        """
        环比计算（Month over Month）
        需要 time_col 包含年月信息
        """
        window = Window.orderBy(time_col)
        result = df.withColumn('prev_value', F.lag(value_col).over(window))
        result = result.withColumn('mom_rate',
            F.round((F.col(value_col) - F.col('prev_value')) / F.col('prev_value') * 100, 2))
        return [row.asDict() for row in result.collect()]

    def calc_ratio(self, df, numerator_col, denominator_col, result_col):
        """计算比率"""
        result = df.withColumn(result_col,
            F.round(F.col(numerator_col) / F.col(denominator_col), 4))
        return [row.asDict() for row in result.collect()]

    def add_ranking(self, data_list, sort_key, reverse=True):
        """添加排名"""
        sorted_data = sorted(data_list, key=lambda x: x.get(sort_key, 0), reverse=reverse)
        for i, item in enumerate(sorted_data):
            item['rank'] = i + 1
        return sorted_data

    def calc_top_n(self, df, n, metric):
        """取 Top N"""
        result = df.limit(n)
        return [row.asDict() for row in result.collect()]
```

### 3.9 Redis 缓存管理 `cache/cache_manager.py`

```python
"""
缓存管理器
职责：Redis 缓存策略实现，支持 TTL、自动失效、缓存预热
"""
import json
import hashlib
import redis
from functools import wraps
from flask import request

class CacheManager:
    """Redis 缓存管理"""

    def __init__(self, app=None):
        self.redis_client = None
        self.default_timeout = 300  # 5 分钟
        if app:
            self.init_app(app)

    def init_app(self, app):
        """初始化 Redis 连接"""
        self.redis_client = redis.Redis(
            host=app.config.get('REDIS_HOST', 'localhost'),
            port=app.config.get('REDIS_PORT', 6379),
            db=app.config.get('REDIS_DB', 0),
            password=app.config.get('REDIS_PASSWORD'),
            decode_responses=True,
            max_connections=20,
        )
        self.default_timeout = app.config.get('CACHE_DEFAULT_TIMEOUT', 300)

    def generate_key(self, prefix, **kwargs):
        """生成缓存键"""
        sorted_params = sorted(kwargs.items())
        param_str = json.dumps(sorted_params, sort_keys=True)
        hash_val = hashlib.md5(param_str.encode()).hexdigest()[:12]
        return f"medical:{prefix}:{hash_val}"

    def get(self, key):
        """获取缓存"""
        try:
            data = self.redis_client.get(key)
            return json.loads(data) if data else None
        except Exception:
            return None

    def set(self, key, value, timeout=None):
        """设置缓存"""
        try:
            timeout = timeout or self.default_timeout
            self.redis_client.setex(key, timeout, json.dumps(value, ensure_ascii=False))
        except Exception:
            pass  # 缓存写入失败不影响主逻辑

    def delete(self, pattern):
        """删除匹配的缓存"""
        try:
            keys = self.redis_client.keys(f"medical:{pattern}:*")
            if keys:
                self.redis_client.delete(*keys)
        except Exception:
            pass

    def clear_all(self):
        """清空所有缓存"""
        try:
            keys = self.redis_client.keys("medical:*")
            if keys:
                self.redis_client.delete(*keys)
        except Exception:
            pass

    def get_stats(self):
        """获取缓存统计"""
        try:
            info = self.redis_client.info('stats')
            return {
                'hits': info.get('keyspace_hits', 0),
                'misses': info.get('keyspace_misses', 0),
                'hit_rate': round(info.get('keyspace_hits', 0) /
                    max(info.get('keyspace_hits', 0) + info.get('keyspace_misses', 0), 1) * 100, 2),
                'keys': self.redis_client.dbsize(),
            }
        except Exception:
            return {}
```

### 3.10 缓存装饰器 `utils/decorators.py`

```python
"""
通用装饰器
"""
import time
import functools
import json
import hashlib
from flask import request, g
from utils.logger import get_logger

logger = get_logger(__name__)

def cache_result(timeout=300, prefix=None):
    """
    API 结果缓存装饰器
    自动根据请求路径+参数生成缓存键
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            from flask import current_app
            cache_manager = current_app.cache_manager

            # 生成缓存键
            cache_prefix = prefix or request.endpoint
            cache_key = cache_manager.generate_key(
                cache_prefix,
                path=request.path,
                args=dict(request.args)
            )

            # 尝试获取缓存
            cached = cache_manager.get(cache_key)
            if cached:
                logger.debug(f"Cache hit: {cache_key}")
                return cached

            # 执行原函数
            result = f(*args, **kwargs)

            # 写入缓存
            cache_manager.set(cache_key, result, timeout)
            logger.debug(f"Cache set: {cache_key}")
            return result
        return wrapper
    return decorator


def log_execution_time(f):
    """执行时间记录装饰器"""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = f(*args, **kwargs)
        elapsed = round((time.time() - start) * 1000, 2)
        logger.info(f"[{request.endpoint}] {elapsed}ms")
        # 在响应头中附加耗时
        if hasattr(result, 'headers'):
            result.headers['X-Response-Time'] = f'{elapsed}ms'
        return result
    return wrapper


def retry(max_retries=3, delay=1):
    """重试装饰器"""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return f(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"Retry {attempt + 1}/{max_retries}: {e}")
                    time.sleep(delay * (attempt + 1))
        return wrapper
    return decorator
```

### 3.11 统一响应封装 `utils/response.py`

```python
"""
统一 API 响应格式
"""
from flask import jsonify

def success(data=None, message='success', code=200):
    """成功响应"""
    response = {
        'code': code,
        'message': message,
        'data': data,
    }
    return jsonify(response), code

def error(message='error', code=400, errors=None):
    """错误响应"""
    response = {
        'code': code,
        'message': message,
        'data': None,
    }
    if errors:
        response['errors'] = errors
    return jsonify(response), code

def paginated(data, total, page, page_size):
    """分页响应"""
    return jsonify({
        'code': 200,
        'message': 'success',
        'data': data,
        'pagination': {
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size,
        }
    })
```

---

## 四、API 接口清单（10+ 个）

### 4.1 医疗费用分析（5 个接口）

| # | 接口路径 | 方法 | 功能 | 关键参数 |
|---|---------|------|------|---------|
| 1 | `/api/v1/expense/summary` | GET | 费用总览（总费用、平均、中位数、分布） | year, region, department |
| 2 | `/api/v1/expense/by-insurance` | GET | 按支付方式分析费用 | year, region |
| 3 | `/api/v1/expense/by-age-gender` | GET | 按年龄+性别分析费用 | year, region |
| 4 | `/api/v1/expense/cost-ratio` | GET | 费用-成本比率分析 | year, department |
| 5 | `/api/v1/expense/ranking` | GET | 费用排名 Top N | dimension, top_n, metric |

### 4.2 疾病分布分析（3 个接口）

| # | 接口路径 | 方法 | 功能 | 关键参数 |
|---|---------|------|------|---------|
| 6 | `/api/v1/disease/top` | GET | 高频疾病排名 | year, region, top_n |
| 7 | `/api/v1/disease/by-severity` | GET | 按严重程度分布 | year, disease |
| 8 | `/api/v1/disease/by-region` | GET | 疾病×区域交叉分析 | disease, year |

### 4.3 科室绩效分析（2 个接口）

| # | 接口路径 | 方法 | 功能 | 关键参数 |
|---|---------|------|------|---------|
| 9 | `/api/v1/department/performance` | GET | 科室绩效（病例数、费用、住院天数） | year, department |
| 10 | `/api/v1/department/ranking` | GET | 科室综合排名 | year, metric |

### 4.4 时间趋势分析（2 个接口）

| # | 接口路径 | 方法 | 功能 | 关键参数 |
|---|---------|------|------|---------|
| 11 | `/api/v1/trend/monthly` | GET | 月度趋势（病例数、费用趋势） | year, metric |
| 12 | `/api/v1/trend/yearly-compare` | GET | 年度同比分析 | metric |

### 4.5 区域分析（2 个接口）

| # | 接口路径 | 方法 | 功能 | 关键参数 |
|---|---------|------|------|---------|
| 13 | `/api/v1/region/overview` | GET | 区域费用/病例分布 | year, metric |
| 14 | `/api/v1/region/compare` | GET | 区域对比分析 | region1, region2, metric |

### 4.6 算法分析（3 个接口）

| # | 接口路径 | 方法 | 功能 | 关键参数 |
|---|---------|------|------|---------|
| 15 | `/api/v1/algorithm/anomaly` | GET | 异常检测 | column, threshold |
| 16 | `/api/v1/algorithm/correlation` | GET | 相关性分析 | columns[] |
| 17 | `/api/v1/algorithm/cluster` | GET | 聚类分析 | n_clusters, features[] |

### 4.7 系统接口（2 个接口）

| # | 接口路径 | 方法 | 功能 |
|---|---------|------|------|
| 18 | `/api/v1/health` | GET | 健康检查 |
| 19 | `/api/v1/cache/stats` | GET | 缓存统计 |

---

## 五、算法库设计（5 个模块）

### 5.1 描述性统计 `algorithms/descriptive_stats.py`

```python
"""
描述性统计分析模块
功能：均值、中位数、标准差、分位数、偏度、峰度等
"""
class DescriptiveStats:
    @staticmethod
    def summary(df, column):
        """单列描述性统计摘要"""
        # 返回: count, mean, std, min, 25%, 50%, 75%, max, skewness, kurtosis
        pass

    @staticmethod
    def group_summary(df, group_cols, value_col):
        """分组描述性统计"""
        pass

    @staticmethod
    def frequency_table(df, column, top_n=None):
        """频率分布表"""
        pass
```

### 5.2 相关性分析 `algorithms/correlation.py`

```python
"""
相关性分析模块
功能：Pearson、Spearman 相关系数，相关矩阵
"""
class CorrelationAnalysis:
    @staticmethod
    def pearson_correlation(df, col1, col2):
        """两列 Pearson 相关系数"""
        pass

    @staticmethod
    def correlation_matrix(df, columns):
        """多列相关矩阵"""
        pass

    @staticmethod
    def top_correlations(df, target_col, n=10):
        """与目标列最相关的 Top N 列"""
        pass
```

### 5.3 趋势预测 `algorithms/trend_prediction.py`

```python
"""
趋势预测模块
功能：线性回归、移动平均、指数平滑
"""
class TrendPrediction:
    @staticmethod
    def linear_regression(df, x_col, y_col):
        """线性回归预测"""
        # 返回: slope, intercept, r_squared, predictions
        pass

    @staticmethod
    def moving_average(values, window=3):
        """移动平均"""
        pass

    @staticmethod
    def exponential_smoothing(values, alpha=0.3):
        """指数平滑"""
        pass
```

### 5.4 异常检测 `algorithms/anomaly_detection.py`

```python
"""
异常检测模块
功能：Z-Score、IQR、Isolation Forest
"""
class AnomalyDetection:
    @staticmethod
    def zscore_detection(df, column, threshold=3.0):
        """Z-Score 异常检测"""
        pass

    @staticmethod
    def iqr_detection(df, column, multiplier=1.5):
        """IQR 异常检测"""
        pass

    @staticmethod
    def detect_and_report(df, column, method='zscore'):
        """检测并生成报告"""
        pass
```

### 5.5 聚类分析 `algorithms/clustering.py`

```python
"""
聚类分析模块
功能：K-Means、层次聚类、聚类评估
"""
class ClusteringAnalysis:
    @staticmethod
    def kmeans_clustering(df, features, n_clusters=3):
        """K-Means 聚类"""
        pass

    @staticmethod
    def elbow_method(df, features, max_k=10):
        """肘部法则确定最优 K"""
        pass

    @staticmethod
    def cluster_profile(df, cluster_col, feature_cols):
        """聚类画像：每个簇的特征统计"""
        pass
```

---

## 六、数据 ETL 流程

### 6.1 数据加载 `etl/data_loader.py`

```python
"""
数据加载器
职责：读取 CSV 文件，处理编码、分隔符、引号等问题
"""
class DataLoader:
    @staticmethod
    def load_csv(file_path, spark_session):
        """加载 CSV 为 Spark DataFrame"""
        return spark_session.read \
            .option('header', 'true') \
            .option('inferSchema', 'true') \
            .option('encoding', 'UTF-8') \
            .option('quote', '"') \
            .option('escape', '"') \
            .csv(file_path)
```

### 6.2 数据清洗 `etl/data_cleaner.py`

```python
"""
数据清洗器
职责：去重、缺失值处理、异常值处理、格式标准化
"""
class DataCleaner:
    @staticmethod
    def clean(df):
        """完整清洗流程"""
        df = DataCleaner.remove_duplicates(df)
        df = DataCleaner.handle_missing_values(df)
        df = DataCleaner.standardize_columns(df)
        df = DataCleaner.clean_currency_columns(df)
        return df

    @staticmethod
    def remove_duplicates(df):
        """去重"""
        return df.dropDuplicates()

    @staticmethod
    def handle_missing_values(df):
        """缺失值处理"""
        # 数值列：填充 0 或中位数
        # 分类列：填充 'Unknown'
        pass

    @staticmethod
    def standardize_columns(df):
        """列名标准化：空格→下划线，统一大小写"""
        for col_name in df.columns:
            new_name = col_name.replace(' ', '_').replace('-', '_')
            df = df.withColumnRenamed(col_name, new_name)
        return df

    @staticmethod
    def clean_currency_columns(df):
        """清洗货币列：去除逗号和美元符号"""
        from pyspark.sql import functions as F
        for col_name in ['Total_Charges', 'Total_Costs']:
            if col_name in df.columns:
                df = df.withColumn(col_name,
                    F.regexp_replace(F.col(col_name), '[,$]', '').cast('double'))
        return df
```

---

## 七、统一响应格式规范（对接前端 ECharts）

### 7.1 标准响应结构

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "summary": { ... },
        "table": [ ... ],
        "echarts": {
            "type": "bar|line|pie|scatter|heatmap",
            "title": { "text": "图表标题", "left": "center" },
            "tooltip": { ... },
            "xAxis": { ... },
            "yAxis": { ... },
            "series": [ ... ]
        },
        "statistics": {
            "total": 123456,
            "avg": 45678.90,
            "median": 34567.00,
            "yoy_rate": 5.2,
            "mom_rate": -1.3
        }
    },
    "pagination": {
        "total": 1000,
        "page": 1,
        "page_size": 20,
        "total_pages": 50
    }
}
```

### 7.2 ECharts 对接方式

前端只需两步即可渲染：

```javascript
// 1. 调用 API
const res = await fetch('/api/v1/expense/summary?year=2021');
const { data } = await res.json();

// 2. 渲染 ECharts
const chart = echarts.init(document.getElementById('chart'));
chart.setOption(data.echarts);
```

---

## 八、性能优化策略

### 8.1 Spark 优化

| 优化项 | 配置 | 预期效果 |
|--------|------|---------|
| AQE 自适应查询 | `spark.sql.adaptive.enabled=true` | 自动优化分区和 Join 策略 |
| 广播小表 | `spark.sql.autoBroadcastJoinThreshold=10MB` | 避免 Shuffle Join |
| 缓存热点表 | `df.cache()` / `df.persist()` | 避免重复计算 |
| 合理分区 | `spark.sql.shuffle.partitions=8` | 避免小文件过多 |
| 列裁剪 | 只 SELECT 需要的列 | 减少 IO |
| 谓词下推 | WHERE 条件尽早过滤 | 减少扫描量 |

### 8.2 缓存策略

| 场景 | 缓存时间 | 失效策略 |
|------|---------|---------|
| 总览/概览数据 | 10 分钟 | 手动清除 |
| 聚合查询结果 | 5 分钟 | TTL 自动过期 |
| 排行榜数据 | 5 分钟 | TTL 自动过期 |
| 算法分析结果 | 30 分钟 | TTL 自动过期 |
| 健康检查 | 不缓存 | - |

### 8.3 API 响应时间目标

| 查询类型 | 目标响应时间 | 优化手段 |
|---------|------------|---------|
| 简单聚合（单表单条件） | < 1 秒 | Spark SQL + Redis 缓存 |
| 多维聚合（多表多条件） | < 3 秒 | 预计算 + 缓存 |
| 算法分析 | < 5 秒 | 异步计算 + 结果缓存 |
| 全表扫描 | < 10 秒 | 分区裁剪 + 列裁剪 |

---

## 九、测试用例设计

### 9.1 API 测试示例

```python
"""
tests/test_expense_api.py
"""
import pytest
import json

class TestExpenseAPI:
    """医疗费用分析 API 测试"""

    def test_summary_success(self, client):
        """测试费用总览 - 正常请求"""
        response = client.get('/api/v1/expense/summary?year=2021')
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data['code'] == 200
        assert 'summary' in data['data']
        assert 'echarts' in data['data']

    def test_summary_with_filters(self, client):
        """测试费用总览 - 带筛选条件"""
        response = client.get('/api/v1/expense/summary?year=2021&region=New York City')
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data['data']['summary']['total_records'] > 0

    def test_summary_no_data(self, client):
        """测试费用总览 - 无数据场景"""
        response = client.get('/api/v1/expense/summary?year=9999')
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data['data']['summary']['total_records'] == 0

    def test_by_insurance(self, client):
        """测试按保险类型分析"""
        response = client.get('/api/v1/expense/by-insurance')
        data = json.loads(response.data)
        assert response.status_code == 200
        assert len(data['data']['data']) > 0

    def test_ranking_with_params(self, client):
        """测试费用排名 - 自定义参数"""
        response = client.get('/api/v1/expense/ranking?dimension=hospital&top_n=5&metric=avg')
        data = json.loads(response.data)
        assert response.status_code == 200
        assert len(data['data']['data']) <= 5

    def test_cache_hit(self, client):
        """测试缓存命中"""
        # 第一次请求
        client.get('/api/v1/expense/summary?year=2021')
        # 第二次请求（应命中缓存）
        response = client.get('/api/v1/expense/summary?year=2021')
        assert response.headers.get('X-Cache') == 'HIT'  # 自定义缓存标识
```

---

## 十、交付件清单

| 交付件 | 文件/目录 | 说明 |
|--------|----------|------|
| 聚合分析 API | `api/routes/` + `services/` | 10+ 个接口，平均响应 < 3 秒 |
| 算法库 | `algorithms/` | 5 个算法模块 + `docs/algorithm_guide.md` |
| API 接口文档 | `docs/api_documentation.md` | 完整接口文档（含请求/响应示例） |
| 性能优化报告 | `docs/performance_report.md` | 优化前后对比数据 |
| 数据接入指南 | `docs/data_access_guide.md` | ECharts 对接指南 |
| 单元测试 | `tests/` | pytest 测试用例 |
| 部署脚本 | `scripts/` | 数据导入、初始化、基准测试 |
| 配置文件 | `config.py` + `.env` | 环境配置 |
