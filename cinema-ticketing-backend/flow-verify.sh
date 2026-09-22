#!/usr/bin/env bash
# 修复后重跑正向链路：锁座 → 下单 → 幂等 → 支付 → 退票（中文 reason）
#
# 关键点：中文请求体一律从文件读（printf 重定向写出 UTF-8 字节 + curl -d @file），
# 绝不把中文放在命令行参数里 —— Git Bash 传给原生 curl.exe 时会转成 GBK，
# 服务端按 UTF-8 解析就会 400。详见同目录 zh-refund-test.sh 的说明。
set -u

API=http://localhost:8080
J='Content-Type: application/json'
S1=${1:-198}
S2=${2:-206}

printf '%s' '{"reason":"临时有事看不了"}' > /tmp/refund-zh.json

step() { echo; echo "===== $* ====="; }

step "1. 登录"
TOKEN=$(curl -s --max-time 15 -X POST "$API/api/auth/login" -H "$J" \
  -d '{"username":"tester01","password":"test1234"}' | sed -E 's/.*"token":"([^"]*)".*/\1/')
echo "TOKEN=${TOKEN:0:16}..."

step "2. 锁座 $S1 / $S2"
curl -s --max-time 15 -X POST "$API/api/orders/lock-seats" -H "$J" -H "X-Auth-Token: $TOKEN" \
  -d "{\"screeningId\":1,\"seatIds\":[$S1,$S2]}"
echo

step "3. 下单"
REQID="verify-$(date +%s%N)"
ORDER=$(curl -s --max-time 15 -X POST "$API/api/orders" -H "$J" -H "X-Auth-Token: $TOKEN" \
  -d "{\"screeningId\":1,\"seatIds\":[$S1,$S2],\"requestId\":\"$REQID\"}")
NO=$(printf '%s' "$ORDER" | sed -E 's/.*"orderNo":"([^"]*)".*/\1/')
printf '%s' "$ORDER" | grep -oE '"(orderNo|status|totalAmount|expireAt|createdAt)":"?[^,"]*' | head -6
echo "订单号: $NO"

step "4. 幂等（同 requestId 再下一次）"
NO2=$(curl -s --max-time 15 -X POST "$API/api/orders" -H "$J" -H "X-Auth-Token: $TOKEN" \
  -d "{\"screeningId\":1,\"seatIds\":[$S1,$S2],\"requestId\":\"$REQID\"}" \
  | sed -E 's/.*"orderNo":"([^"]*)".*/\1/')
[ "$NO" = "$NO2" ] && echo "✅ 同一订单号，幂等生效" || echo "❌ 订单号不同: $NO vs $NO2"

step "5. 支付（流水号带纳秒，避免撞唯一键）"
curl -s --max-time 15 -X POST "$API/api/orders/$NO/pay" -H "$J" -H "X-Auth-Token: $TOKEN" \
  -d "{\"paymentNo\":\"PAY-$(date +%s%N)\"}" \
  | grep -oE '"(status|paidAt|ticket_status)":"[^"]*"'

step "6. 退票（中文 reason，从文件读，UTF-8 字节原样）"
curl -s --max-time 15 -X POST "$API/api/orders/$NO/refund" -H "$J" -H "X-Auth-Token: $TOKEN" \
  -d @/tmp/refund-zh.json | grep -oE '"(status|ticket_status)":"[^"]*"'

echo
echo "订单号: $NO"
echo "$NO" > /tmp/verify-order.txt
