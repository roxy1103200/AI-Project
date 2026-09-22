#!/usr/bin/env bash
# 验证「退票时中文 reason 导致 500」到底是谁的问题。
#
# 背景：Git Bash 把参数交给原生 Windows 程序（curl.exe）时，会按系统 ANSI 代码页
# 把 UTF-8 转成 GBK。所以 `curl -d '{"reason":"中文"}'` 发出去的其实是 GBK 字节。
# 三种发法对照：
#   A 用文件（-d @file）：字节原样，从不经过 argv 转换
#   B 用 \uXXXX 转义：argv 里全是 ASCII，服务端自己解码成中文
#   C 直接在 argv 里写中文：会被转成 GBK，复现 500
#
# 场景用 screening 3（hall 2），避免动到之前 screening 1 上已售的座位。
set -u

API=http://localhost:8080
J='Content-Type: application/json'

# bash 内建 printf，不经过 argv 转换，写出的是 UTF-8 字节
printf '%s' '{"reason":"临时有事看不了"}' > /tmp/refund-zh.json

login() {
  local resp
  resp=$(curl -s --max-time 15 -X POST "$API/api/auth/login" -H "$J" \
    -d '{"username":"tester01","password":"test1234"}')
  TOKEN=$(printf '%s' "$resp" | sed -E 's/.*"token":"([^"]*)".*/\1/')
  if [ -z "$TOKEN" ] || [ "$TOKEN" = "$resp" ]; then
    echo "登录失败，原始响应: $resp" >&2
    return 1
  fi
  echo "TOKEN=${TOKEN:0:16}..."
}

# run_case <名字> <座位1> <座位2> <退票请求体的 curl 参数...>
run_case() {
  local name=$1 s1=$2 s2=$3
  shift 3
  local order no pay_no res

  echo
  echo "########## $name ##########"

  curl -s --max-time 15 -X POST "$API/api/orders/lock-seats" -H "$J" -H "X-Auth-Token: $TOKEN" \
    -d "{\"screeningId\":3,\"seatIds\":[$s1,$s2]}" > /dev/null

  order=$(curl -s --max-time 15 -X POST "$API/api/orders" -H "$J" -H "X-Auth-Token: $TOKEN" \
    -d "{\"screeningId\":3,\"seatIds\":[$s1,$s2],\"requestId\":\"zh-$name-$(date +%s)\"}")
  no=$(printf '%s' "$order" | sed -E 's/.*"orderNo":"([^"]*)".*/\1/')
  echo "订单号: $no"
  if [ "$no" = "$order" ]; then echo "下单失败: $order"; return 1; fi

  pay_no="PAY-$(date +%s)"
  curl -s --max-time 15 -X POST "$API/api/orders/$no/pay" -H "$J" -H "X-Auth-Token: $TOKEN" \
    -d "{\"paymentNo\":\"$pay_no\"}" > /dev/null

  echo "退票请求参数: $*"
  res=$(curl -s --max-time 15 -X POST "$API/api/orders/$no/refund" -H "$J" -H "X-Auth-Token: $TOKEN" "$@")
  echo "退票响应: $res"
  echo "$no" >> /tmp/zh-order-nos.txt
}

: > /tmp/zh-order-nos.txt
login || exit 1

echo "请求体文件字节: $(od -An -tx1 /tmp/refund-zh.json | tr -d '\n' | cut -c1-48)"

run_case "A-file-utf8"       323 329 -d @/tmp/refund-zh.json
run_case "B-unicode-escape"  335 341 -d '{"reason":"\\u4e34\\u65f6\\u6709\\u4e8b\\u770b\\u4e0d\\u4e86"}'
run_case "C-argv-gbk"        347 353 -d '{"reason":"临时有事看不了"}'

echo
echo "生成的订单号: $(tr '\n' ' ' < /tmp/zh-order-nos.txt)"
