#!/usr/bin/env bash
# Step5: MySQL Metastore + Hive配置/初始化/依赖版本对齐/启动
# 在root下执行
set -e
source /etc/profile.d/hadoop-env.sh 2>/dev/null

HIVE_VER="3.1.3"
HADOOP_VER="3.3.6"
MYSQL_ROOT_PWD="Hive@2026Meta"
HIVE_MYSQL_PWD="HiveUser2026"

echo "==== 1. 安装 MySQL Server 8.0 (Ubuntu24.04=mysql-server-8.0) ===="
# 更新包索引 (之前apt upgrade可能没包含mysql-server)
apt-get update -qq 2>&1 | tail -2
# Ubuntu24: mysql-server=虚包, 实际装 mysql-server-8.0 + mysql-client-8.0
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mysql-server-8.0 mysql-client-8.0 default-mysql-client 2>&1 | tail -8
# 启动mysql (Ubuntu mysql.service 名有时是 mysqld 或 mysql; 都尝试)
(service mysql start 2>&1 || service mysqld start 2>&1 || /etc/init.d/mysql start 2>&1) | tail -2
sleep 3
# 确认mysql进程
pgrep -xa mysqld | head -1


# 初始化root密码 + 创建hive元数据库和用户
echo "  MySQL启动完成，初始化root/hive用户..."
mysql -uroot -e "
ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '${MYSQL_ROOT_PWD}';
FLUSH PRIVILEGES;
CREATE DATABASE IF NOT EXISTS hive_metastore DEFAULT CHARACTER SET latin1;
CREATE USER IF NOT EXISTS 'hive'@'%' IDENTIFIED BY '${HIVE_MYSQL_PWD}';
GRANT ALL PRIVILEGES ON hive_metastore.* TO 'hive'@'%';
CREATE USER IF NOT EXISTS 'hive'@'localhost' IDENTIFIED BY '${HIVE_MYSQL_PWD}';
GRANT ALL PRIVILEGES ON hive_metastore.* TO 'hive'@'localhost';
FLUSH PRIVILEGES;
" 2>/dev/null || true   # 如果密码已设置，ALTER会失败；后续都用新密码
# 验证
mysql -uroot -p"${MYSQL_ROOT_PWD}" -e "SHOW DATABASES LIKE 'hive_metastore'; SELECT user,host FROM mysql.user WHERE user='hive';" 2>&1 | tail -5

echo ""
echo "==== 2. 下载 MySQL Connector/J 8.0 到 HIVE_HOME/lib ===="
# Ubuntu apt装的 libmysql-java 路径是 /usr/share/java/mysql-connector-java*.jar
CP_JAR=$(ls /usr/share/java/mysql-connector-j*.jar 2>/dev/null | head -1)
if [ -z "$CP_JAR" ]; then
    # 如果apt包没装，手动下
    CP_URL="https://repo1.maven.org/maven2/com/mysql/mysql-connector-j/8.0.33/mysql-connector-j-8.0.33.jar"
    echo "  下载 Connector/J 8.0.33..."
    curl -fsSL -o "$HIVE_HOME/lib/mysql-connector-j-8.0.33.jar" "$CP_URL" && echo "  下载OK"
else
    cp "$CP_JAR" "$HIVE_HOME/lib/" 2>/dev/null
    echo "  已从apt包复制 Connector/J: $(basename "$CP_JAR")"
fi
ls -lh "$HIVE_HOME/lib" | grep mysql

echo ""
echo "==== 3. 依赖版本对齐：Hive<->Hadoop 公共依赖 guava 版本冲突修复 ===="
# Hive 3.1.3带 guava-19.0.jar  太老, Hadoop 3.3.6需要 guava-27.0-jre 或更高
# 删Hive里的老guava, 复制Hadoop的新guava (ExperienceID 1161505的关键经验)
HADOOP_GUAVA=$(ls "$HADOOP_HOME/share/hadoop/common/lib/guava-"*.jar 2>/dev/null | head -1)
HIVE_GUAVAS=$(ls "$HIVE_HOME/lib/guava-"*.jar 2>/dev/null)
if [ -n "$HADOOP_GUAVA" ]; then
    echo "  Hadoop guava: $(basename "$HADOOP_GUAVA")"
fi
if [ -n "$HIVE_GUAVAS" ]; then
    for g in $HIVE_GUAVAS; do
        echo "  删除Hive旧guava: $(basename "$g")"
        rm -f "$g"
    done
fi
# 复制Hadoop的guava, stax2-api, woodstox-core (Hadoop common/lib中常见的与Hive冲突的)
for jar in guava-*.jar slf4j-api-*.jar slf4j-reload4j-*.jar stax2-api-*.jar woodstox-core-*.jar commons-lang3-*.jar jackson-core-*.jar jackson-databind-*.jar jackson-annotations-*.jar; do
    src=$(find "$HADOOP_HOME/share/hadoop/common/lib" -name "$jar" 2>/dev/null | head -1)
    if [ -f "$src" ]; then
        # 删掉Hive里旧的同名
        rm -f "$HIVE_HOME/lib/$(echo "$jar" | sed 's/-[^-]*\.jar$/-*.jar/')" 2>/dev/null
        oldfiles=$(ls "$HIVE_HOME/lib/$(echo "$jar" | sed 's/\(-[^-]*\)\{2\}\.jar$/-*.jar/')" 2>/dev/null)
        [ -n "$oldfiles" ] && rm -f $oldfiles 2>/dev/null
        name="$(basename "$src")"
        if [ ! -f "$HIVE_HOME/lib/$name" ]; then
            cp "$src" "$HIVE_HOME/lib/"
            echo "  对齐依赖: $name"
        fi
    fi
done

echo ""
echo "==== 4. 配置 hive-site.xml ===="
mkdir -p /data/hive/{tmp,warehouse,logs}
chown -R luo:luo /data/hive "$HIVE_HOME"

cat > "$HIVE_HOME/conf/hive-site.xml" << 'HXML'
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<?xml-stylesheet type="text/xsl" href="configuration.xsl"?>
<configuration>
  <!-- ====== Metastore: MySQL ====== -->
  <property>
    <name>javax.jdo.option.ConnectionURL</name>
    <value>jdbc:mysql://localhost:3306/hive_metastore?createDatabaseIfNotExist=true&amp;useSSL=false&amp;allowPublicKeyRetrieval=true&amp;useUnicode=true&amp;characterEncoding=UTF-8</value>
  </property>
  <property>
    <name>javax.jdo.option.ConnectionDriverName</name>
    <value>com.mysql.cj.jdbc.Driver</value>
  </property>
  <property>
    <name>javax.jdo.option.ConnectionUserName</name>
    <value>hive</value>
  </property>
  <property>
    <name>javax.jdo.option.ConnectionPassword</name>
    <value>HiveUser2026</value>
  </property>

  <!-- ====== HDFS Warehouse / Exec: Tez fallback MR ====== -->
  <property>
    <name>hive.metastore.warehouse.dir</name>
    <value>/warehouse</value>
  </property>
  <property>
    <name>hive.exec.scratchdir</name>
    <value>/tmp/hive</value>
  </property>
  <property>
    <name>hive.exec.local.scratchdir</name>
    <value>/data/hive/tmp</value>
  </property>
  <property>
    <name>hive.downloaded.resources.dir</name>
    <value>/data/hive/tmp/resources</value>
  </property>
  <property>
    <name>hive.querylog.location</name>
    <value>/data/hive/logs</value>
  </property>
  <property>
    <name>hive.exec.dynamic.partition</name>
    <value>true</value>
  </property>
  <property>
    <name>hive.exec.dynamic.partition.mode</name>
    <value>nonstrict</value>
  </property>
  <property>
    <name>hive.exec.max.dynamic.partitions</name>
    <value>1000</value>
  </property>
  <property>
    <name>hive.exec.max.dynamic.partitions.pernode</name>
    <value>500</value>
  </property>

  <!-- ====== Metastore ====== -->
  <property>
    <name>hive.metastore.event.db.notification.api.auth</name>
    <value>false</value>
  </property>
  <property>
    <name>hive.metastore.schema.verification</name>
    <value>false</value>
  </property>
  <property>
    <name>hive.metastore.schema.verification.record.version</name>
    <value>false</value>
  </property>
  <property>
    <name>datanucleus.schema.autoCreateAll</name>
    <value>true</value>
  </property>
  <property>
    <name>hive.metastore.uris</name>
    <value>thrift://hadoop-master:9083</value>
  </property>

  <!-- ====== HiveServer2 ====== -->
  <property>
    <name>hive.server2.thrift.bind.host</name>
    <value>0.0.0.0</value>
  </property>
  <property>
    <name>hive.server2.thrift.port</name>
    <value>10000</value>
  </property>
  <property>
    <name>hive.server2.enable.doAs</name>
    <value>false</value>
  </property>
  <property>
    <name>hive.server2.authentication</name>
    <value>NOSASL</value>
  </property>
  <property>
    <name>hive.server2.session.hook</name>
    <value></value>
  </property>
  <!-- Web UI port: 10002 -->
  <property>
    <name>hive.server2.webui.host</name>
    <value>0.0.0.0</value>
  </property>
  <property>
    <name>hive.server2.webui.port</name>
    <value>10002</value>
  </property>

  <!-- Exec Engine: 先用MR避免Tez安装 -->
  <property>
    <name>hive.execution.engine</name>
    <value>mr</value>
  </property>

  <!-- Compression & performance -->
  <property>
    <name>hive.exec.compress.output</name>
    <value>false</value>
  </property>
  <property>
    <name>mapreduce.output.fileoutputformat.compress</name>
    <value>false</value>
  </property>
</configuration>
HXML
chown luo:luo "$HIVE_HOME/conf/hive-site.xml"
echo "  hive-site.xml 写入"

echo ""
echo "==== 5. schematool 初始化 MySQL Metastore Schema ===="
# 确保HDFS/tmp目录存在且有权限
chmod -R 777 /data/hive /tmp
su - luo -c "source /etc/profile.d/hadoop-env.sh; hdfs dfs -mkdir -p /tmp/hive /warehouse /user/luo /user/hive 2>/dev/null; hdfs dfs -chmod -R 777 /tmp /warehouse /user 2>/dev/null; true"
# schematool 初始化 (必须是mysql模式)
SCHEMA_LOG="/tmp/schematool.log"
su - luo -c "
source /etc/profile.d/hadoop-env.sh
cd \$HIVE_HOME
bin/schematool -dbType mysql -initSchema 2>&1 | tee '$SCHEMA_LOG'
" | tail -15
echo ""
if grep -q "schemaTool completed" "$SCHEMA_LOG" 2>/dev/null; then
    echo "  [OK] Metastore Schema 初始化成功!"
else
    echo "  [WARN] 可能未完全成功, 查看MySQL中已创建的表:"
    mysql -uhive -p"${HIVE_MYSQL_PWD}" -e "USE hive_metastore; SHOW TABLES;" 2>/dev/null | wc -l | xargs -I{} echo "  Metastore 表数量: {}"
fi

echo ""
echo "==== 6. 启动 Metastore (9083) 和 HiveServer2 (10000) ===="
mkdir -p /data/hive/logs /tmp/hive
chmod -R 777 /tmp/hive /data/hive /opt/hive
chown -R luo:luo /data/hive /opt/hive
su - luo -c "source /etc/profile.d/hadoop-env.sh
export HADOOP_HOME=/opt/hadoop
export HIVE_HOME=/opt/hive
cd \$HIVE_HOME
# 启动 Metastore (后台)
nohup bin/hive --service metastore > /data/hive/logs/metastore.log 2>&1 &
sleep 20
# 启动 HiveServer2 (后台)
nohup bin/hive --service hiveserver2 > /data/hive/logs/hiveserver2.log 2>&1 &
sleep 5
echo '启动命令已执行'
"

echo "  给服务20秒启动..."
sleep 22

echo ""
echo "==== 7. 服务 & 端口检查 ===="
ps -ef | grep -E 'HiveMetaStore|HiveServer2' | grep -v grep | awk '{print "  PID:"$2, $8}'
for port in 3306 9083 10000 10002; do
    if (echo > /dev/tcp/127.0.0.1/$port) 2>/dev/null; then
        echo "  Port $port :  LISTEN OK"
    else
        echo "  Port $port :  NOT LISTENING (log tail:)"
    fi
done

echo ""
echo "==== 8. HiveCLI 冒烟测试 (建库+建表+插入+查询) ===="
su - luo -c "source /etc/profile.d/hadoop-env.sh
cd \$HIVE_HOME
bin/hive -e \"
CREATE DATABASE IF NOT EXISTS smoke_test;
USE smoke_test;
DROP TABLE IF EXISTS hello;
CREATE TABLE hello (id INT, name STRING) ROW FORMAT DELIMITED FIELDS TERMINATED BY ',' STORED AS TEXTFILE;
INSERT INTO TABLE hello VALUES (1,'Alice'),(2,'Bob'),(3,'Charlie');
SELECT COUNT(*) AS hello_cnt FROM hello;
SELECT * FROM hello;
\" 2>&1 | tail -20
"
echo ""
echo "[DONE] Step5 完成"
