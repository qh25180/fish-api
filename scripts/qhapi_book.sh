#!/bin/bash
# ============================================================================ #
# qhapi_book.sh — 通过 QHAPI 搜索并下载书籍
#
# 用法:
#   ./scripts/qhapi_book.sh <关键词>                 # 搜索
#   ./scripts/qhapi_book.sh <关键词> --source a    # 指定源搜索
#
# 环境变量:
#   QHAPI_BASE    API 服务地址（默认 http://localhost:8000）
#   QHAPI_TOKEN   访问口令（可选）
# ============================================================================ #

BASE="${QHAPI_BASE:-http://localhost:8000}"
TOKEN="${QHAPI_TOKEN:-}"

# 如果没有设置环境变量，尝试从 .env 读取
if [ -z "$TOKEN" ] && [ -f "$(dirname "$0")/../.env" ]; then
    TOKEN=$(grep "^API_TOKEN=" "$(dirname "$0")/../.env" | cut -d= -f2 | head -1)
fi

usage() {
    echo "用法: $0 <关键词> [--source a|rar|auto]"
    echo "环境变量: QHAPI_BASE, QHAPI_TOKEN"
    exit 1
}

[ $# -lt 1 ] && usage

KEYWORD="$1"
SOURCE="a"
[ "$2" = "--source" ] && [ -n "$3" ] && SOURCE="$3"

# 搜索
echo "🔍 搜索: $KEYWORD (源: $SOURCE)"
TOKEN_ARG=""
[ -n "$TOKEN" ] && TOKEN_ARG="&token=$TOKEN"

SEARCH_URL="${BASE}/api/v1/search?q=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${KEYWORD}'))")&source=${SOURCE}"
RESP=$(curl -s "$SEARCH_URL")

TOTAL=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total',0))" 2>/dev/null)
if [ "$TOTAL" = "0" ] || [ -z "$TOTAL" ]; then
    echo "❌ 未找到匹配结果"
    exit 1
fi

echo "✅ 共 $TOTAL 个结果:"
echo ""

# 显示结果
echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for i, r in enumerate(d['results'][:30], 1):
    size = r.get('size_hint', '')
    print(f'  {i}. [{r[\"source\"]}] {r[\"title\"]} {size}')
" 2>/dev/null

echo ""
echo -n "请输入序号 (1-$TOTAL, q=退出): "
read -r SEL
[ "$SEL" = "q" ] || [ -z "$SEL" ] && echo "已取消" && exit 0

# 获取选中书籍的 ID
BOOK_ID=$(echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
i = int($SEL) - 1
if 0 <= i < len(d['results']):
    print(d['results'][i]['id'])
" 2>/dev/null)

[ -z "$BOOK_ID" ] && echo "❌ 无效选择" && exit 1

echo "⬇️  下载中..."
DOWNLOAD_URL="${BASE}/api/v1/books/download?book_id=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${BOOK_ID}'))")&source=${SOURCE}${TOKEN_ARG}"
DL_RESP=$(curl -s "$DOWNLOAD_URL")

SUCCESS=$(echo "$DL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success',False))" 2>/dev/null)
if [ "$SUCCESS" = "True" ]; then
    FILENAME=$(echo "$DL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('filename',''))" 2>/dev/null)
    echo "✅ 下载成功: $FILENAME"
else
    ERROR=$(echo "$DL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','未知错误'))" 2>/dev/null)
    echo "❌ 下载失败: $ERROR"
fi
