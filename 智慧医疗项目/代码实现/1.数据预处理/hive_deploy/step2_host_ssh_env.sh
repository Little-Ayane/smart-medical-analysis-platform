#!/usr/bin/env bash
# 环境准备: hostname / hosts / wsl.conf / 全局变量 / SSH免密 / sshd启动
# 在WSL root下执行
set -e

echo "==== 1. 配置 wsl.conf (hostname持久化+sshd开机启动) ===="
cat > /etc/wsl.conf << 'EOF'
[network]
hostname = hadoop-master
generateHosts = false
[boot]
command = "service ssh start"
[user]
default = luo
EOF
cat > /etc/hosts << 'EOF'
127.0.0.1   localhost
127.0.1.1   hadoop-master
::1         localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
EOF
hostname hadoop-master 2>/dev/null || true
echo "  hostname = $(hostname)"

echo ""
echo "==== 2. 写全局环境变量 /etc/profile.d/hadoop-env.sh ===="
cat > /etc/profile.d/hadoop-env.sh << 'ENVVAR'
export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
export JRE_HOME=${JAVA_HOME}/jre
export CLASSPATH=.:${JAVA_HOME}/lib:${JRE_HOME}/lib
export HADOOP_HOME=/opt/hadoop
export HADOOP_CONF_DIR=${HADOOP_HOME}/etc/hadoop
export HIVE_HOME=/opt/hive
export PATH=${PATH}:${JAVA_HOME}/bin:${HADOOP_HOME}/bin:${HADOOP_HOME}/sbin:${HIVE_HOME}/bin
export HADOOP_MAPRED_HOME=${HADOOP_HOME}
export HADOOP_COMMON_HOME=${HADOOP_HOME}
export HADOOP_HDFS_HOME=${HADOOP_HOME}
export YARN_HOME=${HADOOP_HOME}
export HADOOP_OPTS="-Djava.library.path=${HADOOP_HOME}/lib/native"
ENVVAR
chmod +x /etc/profile.d/hadoop-env.sh
# 对当前用户(以及~/.bashrc用户)持久生效
for RC in /root/.bashrc /home/luo/.bashrc; do
    if [ -f "$RC" ] && ! grep -q 'profile.d/hadoop-env.sh' "$RC"; then
        echo 'source /etc/profile.d/hadoop-env.sh' >> "$RC"
    fi
done
source /etc/profile.d/hadoop-env.sh
echo "  JAVA_HOME=$JAVA_HOME"
echo "  HADOOP_HOME=$HADOOP_HOME"
echo "  HIVE_HOME=$HIVE_HOME"

echo ""
echo "==== 3. 配置root/luo 用户 SSH 免密 localhost/hadoop-master ===="
setup_ssh() {
    local user=$1
    if [ "$user" = "root" ]; then
        local hd=/root
    else
        local hd="/home/$user"
    fi
    [ -d "$hd" ] || return 0
    mkdir -p "$hd/.ssh"
    chmod 700 "$hd/.ssh"
    if [ ! -f "$hd/.ssh/id_rsa" ]; then
        ssh-keygen -t rsa -b 4096 -f "$hd/.ssh/id_rsa" -N "" -C "hadoop" -q
        echo "  $user: 新密钥生成"
    fi
    cat "$hd/.ssh/id_rsa.pub" >> "$hd/.ssh/authorized_keys"
    chmod 600 "$hd/.ssh/authorized_keys"
    # 预填known_hosts, 避免首次连接交互
    (ssh-keyscan -t rsa,ecdsa,ed25519 hadoop-master localhost 127.0.0.1 2>/dev/null | sort -u >> "$hd/.ssh/known_hosts") || true
    chmod 644 "$hd/.ssh/known_hosts"
    chown -R "$user:$(id -gn "$user")" "$hd/.ssh"
}
setup_ssh root
setup_ssh luo

echo ""
echo "==== 4. 启动 sshd ===="
service ssh start || true
sleep 1
service ssh status | head -1

echo ""
echo "==== 5. 测试免密SSH ===="
for u in root luo; do
    r=$(ssh -o StrictHostKeyChecking=no "$u@localhost" "echo ok" 2>&1 | tail -1)
    echo "  $u@localhost  -> $r"
done

echo ""
echo "[DONE] step2 完成"
