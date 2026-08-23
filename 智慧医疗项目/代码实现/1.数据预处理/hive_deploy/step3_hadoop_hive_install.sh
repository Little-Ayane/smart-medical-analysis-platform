#!/usr/bin/env bash
# Hadoop 3.3.6 伪分布式安装+配置+启动
# 在WSL root下执行
set -e
source /etc/profile.d/hadoop-env.sh 2>/dev/null || true

HADOOP_VER="3.3.6"
HIVE_VER="3.1.3"
MIRROR_HADOOP="https://mirrors.cloud.tencent.com/apache/hadoop/common/hadoop-${HADOOP_VER}/hadoop-${HADOOP_VER}.tar.gz"
MIRROR_HIVE="https://repo.huaweicloud.com/apache/hive/hive-${HIVE_VER}/apache-hive-${HIVE_VER}-bin.tar.gz"
# 备用：不同镜像源兜底
ARCHIVE_HADOOP="https://mirrors.tuna.tsinghua.edu.cn/apache/hadoop/common/hadoop-${HADOOP_VER}/hadoop-${HADOOP_VER}.tar.gz"
ARCHIVE_HIVE="https://mirrors.huaweicloud.com/apache/hive/hive-${HIVE_VER}/apache-hive-${HIVE_VER}-bin.tar.gz"

DL_DIR="/opt/download"
mkdir -p "$DL_DIR" /data/hadoop/{name,data,tmp,tmp-nm,tmp-local} /data/yarn/{logs,local}
chmod -R 777 /data /data/hadoop /data/yarn

download() {
    # 多源下载: url1失败换url2
    local dest=$1 url1=$2 url2=$3 name=$4
    if [ -f "$dest" ] && [ $(stat -c%s "$dest") -gt 1000000 ]; then
        echo "  $name 已存在 ($(du -h "$dest" | cut -f1)), 跳过下载"
        return 0
    fi
    echo "  下载 $name (源1清华)..."
    if curl -fsSL --connect-timeout 10 --max-time 600 -o "$dest" "$url1"; then return 0; fi
    echo "  源1失败, 切换源2(apache归档)..."
    if curl -fsSL --connect-timeout 10 --max-time 900 -o "$dest" "$url2"; then return 0; fi
    echo "[ERROR] 下载失败: $name"; rm -f "$dest"; return 1
}

echo "==== 1. 下载 Hadoop ${HADOOP_VER} + Hive ${HIVE_VER} ===="
download "$DL_DIR/hadoop-${HADOOP_VER}.tar.gz" "$MIRROR_HADOOP" "$ARCHIVE_HADOOP" "Hadoop ${HADOOP_VER}" &
PID1=$!
download "$DL_DIR/apache-hive-${HIVE_VER}-bin.tar.gz" "$MIRROR_HIVE" "$ARCHIVE_HIVE" "Hive ${HIVE_VER}" &
PID2=$!
wait $PID1; wait $PID2
echo "  下载完成!"
ls -lhS "$DL_DIR"/*.tar.gz

echo ""
echo "==== 2. 解压 Hadoop /opt/hadoop ===="
if [ ! -f "$HADOOP_HOME/bin/hadoop" ]; then
    tar -xzf "$DL_DIR/hadoop-${HADOOP_VER}.tar.gz" -C /opt
    ln -sfn "/opt/hadoop-${HADOOP_VER}" "$HADOOP_HOME"
    echo "  解压到 $HADOOP_HOME"
fi

echo ""
echo "==== 3. 解压 Hive /opt/hive ===="
if [ ! -f "$HIVE_HOME/bin/hive" ]; then
    tar -xzf "$DL_DIR/apache-hive-${HIVE_VER}-bin.tar.gz" -C /opt
    ln -sfn "/opt/apache-hive-${HIVE_VER}-bin" "$HIVE_HOME"
    echo "  解压到 $HIVE_HOME"
fi

echo ""
echo "==== 4. hadoop-env.sh 写死 JAVA_HOME (ssh-daemon启动子进程必须继承) ===="
HADOOP_ENV="$HADOOP_HOME/etc/hadoop/hadoop-env.sh"
cp "$HADOOP_ENV" "$HADOOP_ENV.bak" 2>/dev/null || true
cat > "$HADOOP_ENV" << 'ENV'
export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
export HADOOP_HOME=/opt/hadoop
export HADOOP_CONF_DIR=${HADOOP_HOME}/etc/hadoop
export HADOOP_LOG_DIR=/data/hadoop/logs
export HADOOP_PID_DIR=/data/hadoop/pids
export YARN_LOG_DIR=/data/yarn/logs
export YARN_PID_DIR=/data/yarn/pids
export HADOOP_MAPRED_HOME=${HADOOP_HOME}
export HADOOP_COMMON_HOME=${HADOOP_HOME}
export HADOOP_HDFS_HOME=${HADOOP_HOME}
export YARN_HOME=${HADOOP_HOME}
export HADOOP_OPTS="-Djava.library.path=${HADOOP_HOME}/lib/native -Xmx256m"
export HDFS_NAMENODE_OPTS="-Xmx1024m"
export HDFS_DATANODE_OPTS="-Xmx512m"
export HDFS_SECONDARYNAMENODE_OPTS="-Xmx512m"
export YARN_RESOURCEMANAGER_OPTS="-Xmx512m"
export YARN_NODEMANAGER_OPTS="-Xmx512m"
ENV
echo "  $HADOOP_ENV 已写入"
chmod +x "$HADOOP_ENV"

echo ""
echo "==== 5. 写 HDFS/YARN 配置文件 (单节点伪分布式) ===="
HADOOP_CONF="$HADOOP_HOME/etc/hadoop"
# 5a. core-site.xml
cat > "$HADOOP_CONF/core-site.xml" << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <property>
    <name>fs.defaultFS</name>
    <value>hdfs://hadoop-master:9000</value>
  </property>
  <property>
    <name>hadoop.tmp.dir</name>
    <value>/data/hadoop/tmp</value>
  </property>
  <property>
    <name>hadoop.proxyuser.root.hosts</name>
    <value>*</value>
  </property>
  <property>
    <name>hadoop.proxyuser.root.groups</name>
    <value>*</value>
  </property>
  <property>
    <name>hadoop.proxyuser.luo.hosts</name>
    <value>*</value>
  </property>
  <property>
    <name>hadoop.proxyuser.luo.groups</name>
    <value>*</value>
  </property>
  <property>
    <name>hadoop.proxyuser.hive.hosts</name>
    <value>*</value>
  </property>
  <property>
    <name>hadoop.proxyuser.hive.groups</name>
    <value>*</value>
  </property>
  <property>
    <name>io.file.buffer.size</name>
    <value>131072</value>
  </property>
</configuration>
XML

# 5b. hdfs-site.xml
cat > "$HADOOP_CONF/hdfs-site.xml" << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <property>
    <name>dfs.replication</name>
    <value>1</value>
  </property>
  <property>
    <name>dfs.namenode.name.dir</name>
    <value>/data/hadoop/name</value>
  </property>
  <property>
    <name>dfs.datanode.data.dir</name>
    <value>/data/hadoop/data</value>
  </property>
  <property>
    <name>dfs.webhdfs.enabled</name>
    <value>true</value>
  </property>
  <property>
    <name>dfs.permissions.enabled</name>
    <value>false</value>
  </property>
  <property>
    <name>dfs.namenode.datanode.registration.ip-hostname-check</name>
    <value>false</value>
  </property>
</configuration>
XML

# 5c. mapred-site.xml
cat > "$HADOOP_CONF/mapred-site.xml" << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <property>
    <name>mapreduce.framework.name</name>
    <value>yarn</value>
  </property>
  <property>
    <name>mapreduce.application.classpath</name>
    <value>$HADOOP_HOME/share/hadoop/mapreduce/*:$HADOOP_HOME/share/hadoop/mapreduce/lib/*:$HADOOP_HOME/share/hadoop/common/*:$HADOOP_HOME/share/hadoop/common/lib/*:$HADOOP_HOME/share/hadoop/yarn/*:$HADOOP_HOME/share/hadoop/yarn/lib/*:$HADOOP_HOME/share/hadoop/hdfs/*:$HADOOP_HOME/share/hadoop/hdfs/lib/*</value>
  </property>
  <property>
    <name>mapreduce.map.memory.mb</name>
    <value>1024</value>
  </property>
  <property>
    <name>mapreduce.reduce.memory.mb</name>
    <value>1536</value>
  </property>
  <property>
    <name>mapreduce.map.java.opts</name>
    <value>-Xmx768m</value>
  </property>
  <property>
    <name>mapreduce.reduce.java.opts</name>
    <value>-Xmx1024m</value>
  </property>
  <property>
    <name>yarn.app.mapreduce.am.resource.mb</name>
    <value>1024</value>
  </property>
</configuration>
XML

# 5d. yarn-site.xml
cat > "$HADOOP_CONF/yarn-site.xml" << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <property>
    <name>yarn.nodemanager.aux-services</name>
    <value>mapreduce_shuffle</value>
  </property>
  <property>
    <name>yarn.nodemanager.env-whitelist</name>
    <value>JAVA_HOME,HADOOP_COMMON_HOME,HADOOP_HDFS_HOME,HADOOP_CONF_DIR,CLASSPATH_PREPEND_DISTCACHE,HADOOP_YARN_HOME,HADOOP_MAPRED_HOME</value>
  </property>
  <property>
    <name>yarn.resourcemanager.hostname</name>
    <value>hadoop-master</value>
  </property>
  <property>
    <name>yarn.nodemanager.resource.memory-mb</name>
    <value>5120</value>
  </property>
  <property>
    <name>yarn.nodemanager.resource.cpu-vcores</name>
    <value>3</value>
  </property>
  <property>
    <name>yarn.scheduler.minimum-allocation-mb</name>
    <value>512</value>
  </property>
  <property>
    <name>yarn.scheduler.maximum-allocation-mb</name>
    <value>4096</value>
  </property>
  <property>
    <name>yarn.nodemanager.local-dirs</name>
    <value>/data/yarn/local</value>
  </property>
  <property>
    <name>yarn.nodemanager.log-dirs</name>
    <value>/data/yarn/logs</value>
  </property>
  <property>
    <name>yarn.log-aggregation-enable</name>
    <value>true</value>
  </property>
  <property>
    <name>yarn.nodemanager.vmem-check-enabled</name>
    <value>false</value>
  </property>
  <property>
    <name>yarn.nodemanager.pmem-check-enabled</name>
    <value>true</value>
  </property>
</configuration>
XML

# 5e. workers (Hadoop 3.x 用 workers 代替 slaves)
echo "hadoop-master" > "$HADOOP_CONF/workers"
echo "  配置写入完成 (core/hdfs/mapred/yarn/workers)"

echo ""
echo "==== 6. chown 给 luo 用户 ===="
chown -R luo:luo /data "$HADOOP_HOME" "$HIVE_HOME" /opt/hadoop-3.3.6 /opt/apache-hive-3.1.3-bin /opt/download 2>/dev/null || true
chmod -R 755 /opt/hadoop* /opt/hive /opt/apache-hive* 2>/dev/null || true

echo "[DONE] step3 下载解压+配置 Hadoop+Hive 完成"
echo ""
echo "  * 接下来: 格式化HDFS + 启动"
