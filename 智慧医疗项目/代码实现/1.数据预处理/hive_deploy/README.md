# Hive数仓一键部署文档

> 适用平台：Windows 10/11 + WSL2 Ubuntu + Hadoop 3.3.6 + Hive 3.1.3
> 数据规模：1,037 万条住院记录（2020–2024，纽约州 SPARCS 公开数据）

---

## 一、环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| WSL2 Ubuntu | 22.04+ | 建议部署在 D 盘（C盘空间有限） |
| JDK | 1.8 (OpenJDK 8) | Hadoop/Hive 依赖 |
| Hadoop | 3.3.6 | 单节点（NameNode+DataNode+SecondaryNameNode+RM+NM） |
| Hive | 3.1.3 | Metastore + HiveServer2 |
| MySQL | 8.0 | 作为 Hive Metastore 存储 |
| 内存建议 | 8GB | WSL2 `.wslconfig` 中配置 |

---

## 二、一键部署脚本清单

以下脚本均位于 `scripts/wsl/` 目录，按顺序执行：

| 脚本 | 作用 | 预计耗时 |
|------|------|---------|
| `step2_host_ssh_env.sh` | 主机名/SSH/JDK8/清华源配置 | 10分钟 |
| `step3_hadoop_hive_install.sh` | 下载解压 Hadoop+Hive 并配置 | 15分钟 |
| `step4_format_start_hadoop.sh` | 格式化 HDFS + 启动5进程 + 读写测试 | 5分钟 |
| `step5_mysql_hive_setup.sh` | MySQL 8 + Hive Metastore + HS2 配置 | 15分钟 |
| `step6_export_load_hive.sh` | Windows MySQL → Hive ODS 数据迁移 | 30分钟 |
| `hive_warehouse_pipeline.sh` | 数仓分层 ODS→DWD→DWS→ADS 构建 | 20分钟 |
| `start_all.sh` | 一键启动全部服务 | 2分钟 |
| `boot_services.sh` | WSL 开机自启（写入 `/etc/wsl.conf`） | 自动 |

---

## 三、快速开始（队友拿到新机器）

### 1. 迁移 WSL 到 D 盘（可选，C盘空间紧张时必做）

```powershell
# 先导出
wsl --export Ubuntu D:\wsl-ubuntu-backup.tar
# 注销再导入到D盘
wsl --unregister Ubuntu
wsl --import Ubuntu D:\WSL\Ubuntu D:\wsl-ubuntu-backup.tar
# 设置默认用户
ubuntu config --default-user luo
```

### 2. 配置 `.wslconfig`（限制内存防爆盘）

在 `C:\Users\<用户名>\.wslconfig` 写入：

```ini
[wsl2]
memory=8GB
processors=4
swap=2GB
localhostForwarding=true
vmIdleTimeout=-1
```

### 3. 配置 hosts（WSL 内，IPv4 优先）

```bash
sudo bash -c "echo '127.0.0.1 localhost hadoop-master' > /etc/hosts"
```

### 4. 按顺序执行部署脚本

```bash
# 1) 基础环境
bash /mnt/d/smart-medical-analysis-platform/scripts/wsl/step2_host_ssh_env.sh
# 2) Hadoop+Hive
bash /mnt/d/smart-medical-analysis-platform/scripts/wsl/step3_hadoop_hive_install.sh
# 3) 启动HDFS
bash /mnt/d/smart-medical-analysis-platform/scripts/wsl/step4_format_start_hadoop.sh
# 4) MySQL+Metastore+HS2
bash /mnt/d/smart-medical-analysis-platform/scripts/wsl/step5_mysql_hive_setup.sh
# 5) 迁移数据到ODS
bash /mnt/d/smart-medical-analysis-platform/scripts/wsl/step6_export_load_hive.sh
# 6) 构建数仓分层
bash /mnt/d/smart-medical-analysis-platform/scripts/wsl/hive_warehouse_pipeline.sh
```

### 5. 配置开机自启

```bash
sudo bash /mnt/d/smart-medical-analysis-platform/scripts/wsl/boot_services.sh
# 写入 /etc/wsl.conf [boot] command
```

---

## 四、数仓分层架构

```
┌─────────────────────────────────────────────────┐
│  ADS 应用层   (ads库, 4张报表表)                 │
│  ads_yearly_overview      年度总览+环比          │
│  ads_hospital_area_stats  医院服务区成本占比      │
│  ads_diagnosis_analysis   疾病分类TOP分析        │
│  ads_patient_profile      患者特征画像           │
├─────────────────────────────────────────────────┤
│  DWS 汇总层   (dws库, 2张汇总表)                │
│  dws_discharge_summary    多维聚合(33,445行)    │
│  dws_yearly_stats         年度统计(5行)          │
├─────────────────────────────────────────────────┤
│  DWD 明细层   (dwd库, 1张明细表)                │
│  dwd_discharge_detail     清洗+派生字段(1,037万行)│
├─────────────────────────────────────────────────┤
│  ODS 原始层   (ods库, 1张宽表)                  │
│  ods_medical_data         原始34列(1,037万行)   │
└─────────────────────────────────────────────────┘
```

---

## 五、常见故障排查

### 5.1 ResourceManager 反复崩溃（SIGHUP）
- **现象**：YARN RM 进程频繁消失，日志出现 `RECEIVED SIGNAL 1: SIGHUP`
- **原因**：WSL 会话结束向进程组发送挂断信号
- **解决**：用 `setsid` 隔离启动：
  ```bash
  setsid bash -c "/opt/hadoop/sbin/start-yarn.sh" < /dev/null > /tmp/yarn.log 2>&1 &
  ```

### 5.2 MRAppMaster 找不到
- **现象**：`Could not find or load main class org.apache.hadoop.mapreduce.v2.app.MRAppMaster`
- **解决**：在 `mapred-site.xml` 设置环境变量：
  ```xml
  <property>
    <name>yarn.app.mapreduce.am.env</name>
    <value>HADOOP_MAPRED_HOME=/opt/hadoop-3.3.6</value>
  </property>
  ```
  并重启 HiveServer2（HS2 需继承该环境变量）。

### 5.3 beeline 查询返回 NULL
- **原因**：TSV 文件为 UTF-16 编码，Hive 期望 UTF-8
- **解决**：`iconv -f UTF-16 -t UTF-8` 转换后再上传 HDFS

### 5.4 修改 XML 配置后服务不生效
- **注意**：修改 `yarn-site.xml` / `mapred-site.xml` 后必须**重启 YARN 和 HS2**
- 用 `sed` 批量修改 XML 易破坏结构，建议直接重写完整文件并 `python3 -c "import xml.dom.minidom; xml.dom.minidom.parse(...)"` 验证

---

## 六、验证命令

```bash
# 服务状态
jps                              # 应看到 NameNode/DataNode/RM/NM/HS2/Metastore
for port in 9000 9870 8088 9083 10000; do
  (echo > /dev/tcp/127.0.0.1/$port) 2>/dev/null && echo "Port $port OK" || echo "Port $port DOWN"
done

# 数据验证
/opt/hive/bin/beeline -u "jdbc:hive2://localhost:10000/default" -n luo \
  -e "SELECT 'ods' tbl, COUNT(*) FROM ods.ods_medical_data
      UNION ALL SELECT 'dwd', COUNT(*) FROM dwd.dwd_discharge_detail;"
```

---

## 七、磁盘空间注意事项

- WSL 虚拟磁盘 `ext4.vhdx` 会随写入增长（含删除文件前的旧数据），可用 `wsl --shutdown` 后 `diskpart compact` 压缩
- HDFS 数据默认存 `/warehouse`（WSL 磁盘内），注意预留空间
- 建议 `.wslconfig` 限制内存 8GB，避免 C 盘 swap 膨胀
