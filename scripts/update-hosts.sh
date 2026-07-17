#!/bin/bash
# ============================================================================ #
# update-hosts.sh — 定时更新 /etc/hosts 中的 GitHub 相关域名解析
#
# 用途: 解决 github.com 等站点 DNS 污染 / 访问不稳定问题
# 数据源: https://gitlab.com/ineo6/hosts (社区维护的 GitHub hosts 列表)
# 推荐部署: 放在 /etc/cron.d/ 下每 6 小时执行一次
#
# 安装方式:
#   1. chmod +x scripts/update-hosts.sh
#   2. sudo ./scripts/update-hosts.sh          # 手动执行一次
#   3. 定时执行（已配置 cron 则跳过）:
#      echo "0 */6 * * * root $(pwd)/scripts/update-hosts.sh" \
#        > /etc/cron.d/update-github-hosts
#
# 日志: /var/log/update-hosts.log
# ============================================================================ #

HOSTS_SOURCE="https://gitlab.com/ineo6/hosts/-/raw/master/next-hosts"
HOSTS_FILE="/etc/hosts"
MARKER_BEGIN="# GitHub Host Start"
MARKER_END="# GitHub Host End"

# 1. 下载最新 hosts
TEMP_FILE=$(mktemp)
if ! curl -sS --connect-timeout 10 "$HOSTS_SOURCE" -o "$TEMP_FILE"; then
    echo "[$(date)] 下载失败" >> /var/log/update-hosts.log
    rm -f "$TEMP_FILE"
    exit 1
fi

# 2. 检查是否获取到内容
if ! grep -q "$MARKER_BEGIN" "$TEMP_FILE"; then
    echo "[$(date)] 内容格式异常" >> /var/log/update-hosts.log
    rm -f "$TEMP_FILE"
    exit 1
fi

# 3. 备份当前 hosts
cp "$HOSTS_FILE" "$HOSTS_FILE.bak"

# 4. 移除旧的 GitHub hosts 段落（如果存在）
if grep -q "$MARKER_BEGIN" "$HOSTS_FILE"; then
    sed -i "/$MARKER_BEGIN/,/$MARKER_END/d" "$HOSTS_FILE"
fi

# 5. 追加新的 GitHub hosts 段落
echo "" >> "$HOSTS_FILE"
cat "$TEMP_FILE" >> "$HOSTS_FILE"
echo "" >> "$HOSTS_FILE"

# 6. 清理
rm -f "$TEMP_FILE"
echo "[$(date)] hosts 更新成功" >> /var/log/update-hosts.log
