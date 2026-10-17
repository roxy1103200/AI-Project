# 支付宝沙箱代码接入说明

更新：2026-10-17。实现方案参见 [支付宝沙箱接入方案](alipay-sandbox-integration-plan.md)。

## 1. 本次实现范围

- 电脑网站支付：服务端生成支付宝官方 SDK 签名表单，金额、商户支付单号和支付截止时间均由数据库生成。
- 登录用户发起支付后获得一次性收银台入口，有效期 60 秒，数据库只保存入口令牌的 SHA256 摘要；在当前标签页跳转，保留原标签页登录会话。
- 支付异步通知：RSA2 验签并校验应用、卖家、支付单和金额；确认收款与出票在一个本地事务中完成。重复通知不会重复记账或出票。
- 浏览器回跳：只根据订单号向后端查询，忽略支付宝回跳中的交易状态与金额；不会根据 URL 判定付款成功。
- 超时和主动取消：先核对支付宝交易并关单，再取消本地订单。渠道结果未知时保留 UNPAID 占位，支付单标为 CLOSING，阻止再次打开收银台。
- 主动查询与后台补偿：支付记录每 15 秒具备重查资格，单笔查询至少间隔 3 秒，多实例通过 45 秒数据库租约协调。实际扫描间隔还受批量处理耗时影响。
- 全额退票：先持久化退款流水与规则版本，再调用原路退款。订单进入 REFUNDING，保留座位占用且禁止验票，渠道确认后才成为 REFUNDED。
- 退款超时：保留 UNKNOWN 并用同一个退款流水号查询/重试；每次核对后至少等待 30 秒，最多自动尝试 8 次。重启后继续处理。
- 迟到付款：订单已经取消、支付时间超过截止或场次不可履约时，保留收款事实并创建 LATE_PAYMENT 补偿退款，不重新抢占座位。
- 管理后台：`/admin/payments` 展示待确认退款和支付对账错误；自动尝试耗尽后可重新核对原退款单，操作写入 `payment_operation_log`。
- 模拟支付：默认关闭；历史模拟流水仍标记 MOCK，不改成支付宝流水。经营汇总标为非生产数据，CSV 明细展示渠道和环境。

当前仅允许 SANDBOX 和官方沙箱网关。生产网关、真实支付、部分退款、分账、外部控制台退款自动对账不在本次范围。

## 2. 需要填写的参数

模板：`cinema-ticketing-backend/.env.alipay-sandbox.example`。

### 本机配置按这几个步骤准备

#### 第一步：查沙箱卖家 UID

打开支付宝沙箱账号页：<https://open.alipay.com/develop/sandbox/account>，登录开放平台后查看商家/卖家账号信息，复制“商户 UID”（部分页面标为 PID）。它是以 `2088` 开头的数字串。`ALIPAY_SELLER_ID` 填这串数字，不填沙箱账号邮箱、不填 APPID，也不填买家 UID。

#### 第二步：保存三种密钥，明确每一种的用途

本机目录为 `E:/development/AI-Project/cinema-ticketing-backend/secrets/`，该目录已经被 Git 忽略。

- `alipay-app-private.pem`：应用私钥，后端用它签名。2026-10-17 已将原先误填在模板中的私钥正文保存到此处。
- `alipay-app-public.pem`：与上面私钥匹配的应用公钥，供核对或在沙箱应用中设置应用公钥。它不能用于后端验证支付宝签名。
- `alipay-public.pem`：需要从支付宝沙箱应用页面复制“支付宝公钥”后粘贴到此文件。当前已创建空文件，等待填写。

沙箱应用页：<https://open.alipay.com/develop/sandbox/app>。在“接口加签方式/密钥设置”的公钥模式中查看密钥。要找明确写着“支付宝公钥”的内容；如果更换应用密钥对，必须确保上传的应用公钥与本地应用私钥匹配。

文件是普通 UTF-8 文本文件，保存完整的 Base64 密钥正文即可。当前 Java 私钥要求 PKCS8。可用记事本编辑已有 `.pem` 文件，避免另存成 `.pem.txt`。`ALIPAY_PRIVATE_KEY_FILE` 和 `ALIPAY_PUBLIC_KEY_FILE` 填绝对路径，不能再直接填密钥正文。

如果启动提示“应用私钥文件内容不正确”，请检查 `alipay-app-private.pem`，它必须保存“应用私钥”，不能与 `alipay-public.pem` 内容相同；不要把“支付宝公钥：”等说明文字一同复制。私钥不能从公钥反向生成，需要回到沙箱应用的密钥页面取得原应用私钥；若原私钥已无法获取，应重新配置一对应用密钥，并同步更新平台上的应用公钥。读取器兼容 UTF-8 BOM、空白及 PEM 头尾。

#### 第三步：没有公网域名，使用临时 HTTPS 隧道

不需要购买域名。当前电脑已安装 `cloudflared`，在 PowerShell 中手动运行：

```powershell
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:8080
```

该命令运行期间会将本机 Java 服务映射到临时公网地址；本次未代为启动隧道。控制台出现 `https://某个随机名称.trycloudflare.com` 后，复制实际分配的 HTTPS 地址，再拼接 `/api/payments/alipay/notify`，填入 `ALIPAY_NOTIFY_URL`。随机名称只是示意，不能照抄。

这里转发的是后端 `8080`。`https://localhost:5173/...` 无法让支付宝服务器访问你的电脑，也不是当前 Vite 提供的 HTTP 地址。`ALIPAY_RETURN_URL` 是当前浏览器返回前端页面的地址，仍可保持 `http://localhost:5173/payment/result`。

保持隧道窗口运行；测试结束按 Ctrl+C 关闭。重新开启可能分配新的临时域名，需要修改 `ALIPAY_NOTIFY_URL` 并重启后端。临时隧道是开发联调方式。

官方说明：<https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/>。

#### 第四步：只编辑实际本地配置文件，让 IDEA 读取它

本机实际配置已保存为 `E:/development/AI-Project/cinema-ticketing-backend/.env.alipay-sandbox`。之前填写的 APPID 和卖家 UID 已保留在此文件中；UID 仍需对照平台的卖家信息确认。共享 `.example` 模板已恢复为不含密钥的示例。

在 IDEA 的“运行 → 编辑配置”中选择 Spring Boot 后端启动项，通过“修改选项”显示“程序实参 / Program arguments”，添加下面这一整行（不要填到 VM options 中）：

```text
--spring.config.import=file:E:/development/AI-Project/cinema-ticketing-backend/.env.alipay-sandbox[.properties]
```

这让 Spring 将本地文件按 properties 读取。依据 Spring Boot 官方说明：<https://docs.spring.io/spring-boot/3.4/reference/features/external-config.html#importing-extensionless-files>。如果 IDE 环境变量中此前填过同名 `ALIPAY_*` 或 `PAYMENT_*`，先移除重复值，避免环境变量覆盖本地文件。

填好支付宝公钥、确认卖家 UID、填写实际隧道回调地址后，再将本地文件中的 `PAYMENT_ENABLED` 改为 `true`，保持 `PAYMENT_MOCK_ENABLED=false`，重启后端。当前仍保留关闭状态，没有替你开启支付或发起交易。

如果收银台报错 URL 中出现 `app_id=%09+...`，其中 `%09` 是制表符，`+` 在此表示空格，说明 APPID 被复制进了隐藏字符。请检查 IDEA 运行配置里的同名环境变量，它会覆盖 `.env.alipay-sandbox`。代码会清理首尾空白并校验数字格式；改完配置或代码后需重启后端，重新点击支付生成新的签名表单，不能手动修改旧地址中的 `app_id` 后重放。当前沙箱网关使用 HTTPS。

### 所有参数的含义

1. `ALIPAY_APP_ID`：沙箱应用 APPID。
2. `ALIPAY_SELLER_ID`：沙箱卖家账户 UID，不能填买家 UID。
3. `ALIPAY_PRIVATE_KEY_FILE`：应用 RSA2 私钥文件的绝对路径，PKCS8 格式。应用公钥上传到同一个沙箱应用。
4. `ALIPAY_PUBLIC_KEY_FILE`：支付宝沙箱公钥文件的绝对路径；不是应用公钥。
5. `ALIPAY_NOTIFY_URL`：公网 HTTPS 回调，例如 `https://你的回调域名/api/payments/alipay/notify`，公网代理必须将这个 POST 请求转发到当前 Java 服务，保持表单参数原样。
6. `ALIPAY_RETURN_URL`：前端回跳页，必须是 `/payment/result`，不得带自定义 query/fragment。本地默认 `http://localhost:5173/payment/result`；部署后使用前端 HTTPS 域名。
7. `PAYMENT_ENABLED`：填写完成后改为 `true`；`PAYMENT_MOCK_ENABLED` 保持 `false`。

密钥文件可以包含 PEM 头尾或仅包含 Base64 内容。两份文件均不进入 Git；应用不会向前端返回密钥或把原始回调表单写入日志。启用支付时会检查密钥文件是否可读、RSA 格式、回调地址及沙箱网关。参数为空且支付关闭时可以正常构建应用。

## 3. 本机启动方式

Spring Boot 不会自动读取 `.env.alipay-sandbox.example`。将参数填入 IDE 的运行环境变量，或在启动 Java 的同一个 PowerShell 窗口设置。不要把密钥正文放进环境变量。

```powershell
$env:PAYMENT_ENABLED = 'true'
$env:PAYMENT_MOCK_ENABLED = 'false'
$env:ALIPAY_APP_ID = '填写沙箱应用APPID'
$env:ALIPAY_SELLER_ID = '填写沙箱卖家UID'
$env:ALIPAY_PRIVATE_KEY_FILE = 'E:/private/cinema/alipay-app-private.pem'
$env:ALIPAY_PUBLIC_KEY_FILE = 'E:/private/cinema/alipay-public.pem'
$env:ALIPAY_NOTIFY_URL = 'https://你的回调域名/api/payments/alipay/notify'
$env:ALIPAY_RETURN_URL = 'http://localhost:5173/payment/result'
```

随后按项目现有方式启动后端和前端。回跳到本机只对当前浏览器所在机器有效；公网回调仍必须能访问后端。使用沙箱买家身份完成付款，不能用真实支付宝资金验证。

`PAYMENT_ENABLED=false` 只禁止创建新收银台，已有支付和退款仍会继续对账；处理中记录不能通过关掉开关来当作已取消。

## 4. Compose 方式

另存参数为后端目录下的 `.env.alipay-sandbox`，补齐 `ALIPAY_PRIVATE_KEY_SOURCE` 和 `ALIPAY_PUBLIC_KEY_SOURCE`，两项均为宿主机实际存在的文件路径。Compose 将它们以只读 secrets 挂载到 `/run/secrets/`。

```powershell
docker compose --env-file .env.alipay-sandbox -f docker-compose.yml -f docker-compose.alipay-sandbox.yml --profile app up -d --build cinema-api nginx
```

镜像使用构建产物，启动前需先完成后端打包和前端构建。公网 HTTPS 终止和域名证书由现有部署入口提供，当前仓库 Nginx 仍监听 80。需要回调路径可达 Java，而不是被前端页面或登录跳转接管。Nginx 访问日志已去除 query 和 Referer，并遮蔽一次性收银台令牌。

## 5. 数据库升级

推荐保留 `PAYMENT_INITIALIZE_SCHEMA=true`，应用启动时由 `PaymentSchemaInitializer` 在数据库升级锁下补齐表、列和索引，不重放业务种子数据。需要应用账户具备 CREATE/ALTER/INDEX 权限。

- 新库：`src/main/resources/schema.sql` 已包含支付表与扩展列。
- 旧库：启动升级器增量添加 `payment_order`、`payment_notify_event`、`payment_operation_log`，以及收款/退款字段。
- 已由 DBA 执行升级的环境：可设置 `PAYMENT_INITIALIZE_SCHEMA=false`。
- 手动一次性升级脚本：`migrations/20261017-alipay-sandbox.sql`。只用于尚未升级的旧库，不能与启动升级重复执行；执行前备份。
- 旧报表迁移只回填状态为 REFUNDED 的退款时间，避免把待退款记录误记为已到账。

业务状态仍使用原有 `ticket_order`、`order_item`。支付渠道单、收款流水、退款单分别存储；渠道调用均在数据库事务外，网络失败不会把持久化的补偿任务一起回滚。

## 6. 接口

- `GET /api/payments/config`：开关及环境，不返回凭据。
- `POST /api/orders/{orderNo}/payment`：登录且校验订单归属，返回 `paymentNo` 和一次性 `cashierUrl`。
- `GET /api/payments/checkout/{ticket}`：消费一次性令牌，返回支付宝签名 HTML。
- `GET /api/orders/{orderNo}/payment`：登录且校验归属，读取本地结果。
- `POST /api/orders/{orderNo}/payment/sync`：校验归属后触发限频渠道核对，再返回本地结果。
- `POST /api/payments/alipay/notify`：支付宝表单回调，无用户登录要求；验签和业务校验通过、持久化成功后返回纯文本 `success`，失败返回非成功响应和 `failure`。
- `POST /api/orders/{orderNo}/cancel`：已有订单接口，根据支付来源处理关单。
- `POST /api/orders/{orderNo}/refund`：已有订单接口，根据支付来源处理退款。
- `GET /api/admin/payments/exceptions`：管理员查看待核对退款与支付错误。
- `POST /api/admin/refunds/{id}/retry`：管理员重新核对已耗尽自动尝试的 UNKNOWN 退款；原流水号不变，不直接宣告退款成功。

旧 `/orders/{orderNo}/pay` 只允许显式启用的 MOCK，不能给支付宝订单模拟支付。即使有人绕过前端调用接口，也不能把渠道订单直接改成已支付或已退票。

## 7. 参数准备后的联调顺序

1. 核对配置读取、密钥对应应用及公网 POST 回调地址。
2. 用一张新订单走收银台，检查真实沙箱交易号、SUCCESS 收款记录、ISSUED 订单和电影票。
3. 刷新回跳页、重复通知，确认只有一笔收款、没有重复出票。
4. 关闭回跳页，确认异步通知或后台查询仍能更新订单。
5. 取消待付订单、超时关单，确认渠道未明确关闭时座位仍被占用。
6. 申请未验票且符合政策的退票，检查 REFUNDING 到 REFUNDED，并在沙箱买家核对原路退款。
7. 模拟回调断开/查询超时/退款响应丢失，检查后台继续核对，原支付与退款流水号保持不变。
8. 用另一个账号访问订单/支付查询和重试接口，确认归属与管理员限制。

这份清单尚未执行。退款长期未确认时先检查应用与密钥是否改变、卖家身份和渠道原交易，不应人工把 UNKNOWN 直接改成 REFUNDED。外部支付宝控制台操作需人工核对账实。修改密钥文件或应用配置后需要重启服务；有在途支付/退款时应先核清原应用交易。

## 8. 本次交付检查记录

- 后端：Java 21 / Maven 编译打包通过，使用 `-Dmaven.test.skip=true`。
- 前端：TypeScript 编译与 Vite 生产构建通过。
- 代码差异空白检查通过。
- 未执行自动化测试、数据库迁移、应用部署和支付宝沙箱交易；后续需在配置准备好后执行上述联调清单。
