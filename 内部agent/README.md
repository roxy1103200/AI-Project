# 内部 Agent 实时源码副本

自 2026-10-13 起，本目录从静态快照改为自动同步副本。`源文件/` 保留项目相对路径和源文件原始字节；文件说明放在本目录，避免修改副本内容。服务仍从原后端目录运行。

同步程序在后台每秒发起一次检查，通常在保存后 1～3 秒内完成复制。新增文件、修改、重命名和删除都会更新到副本；同步成功后自动更新 [文件清单.csv](文件清单.csv) 的路径、大小及 SHA-256。

## 同步范围

- `源文件/cinema-ticketing-backend/cinema-ai/`：内部 Agent、MCP Server/Client、模型配置、版本、提示词、知识文档、长期记忆、rerank、评测源码、测试及依赖定义。
- `源文件/cinema-ticketing-backend/cinema-ai-gateway/`：Dify/Agent 两个独立会话通道、身份检查、SSE、反馈、测试和依赖定义。
- Java `Ai*.java`、`InternalAi*.java`、AI 数据库定义及原备份中的共享集成文件；新增匹配文件也会同步。
- 原备份的前端聊天、认证、AI 反馈界面、启动和部署配置，以及当前 Agent/MCP/记忆/rerank 文档。

完整范围见 [sync-config.json](同步工具/sync-config.json)。只有列入范围的文件会进入副本。`.env.example` 会复制；实际 `.env`、密钥目录、虚拟环境、模型、向量库、日志、缓存、构建产物和业务数据排除。Nginx 配置属于源码中的可选部署模板，不表示当前服务器部署了 Nginx。

## 自动运行与操作

当前电脑配置为登录 Windows 后自动启动；同步进程独立于 Agent/网关，关闭启动窗口或停止 AI 服务不影响同步。运行后端的 `start-ai-local.ps1` 也会尝试启动同步；已有进程时不会重复启动。

在项目根目录执行：

```powershell
# 查看进程是否运行、最后同步时间、文件数和错误状态
.\内部agent\同步工具\sync-agent.cmd --status

# 启动后台同步
.\内部agent\同步工具\sync-agent.cmd --start

# 停止后台同步；下次登录或启动 AI 服务会再次启动
.\内部agent\同步工具\sync-agent.cmd --stop

# 同步一次；后台已运行时由现有进程继续同步
.\内部agent\同步工具\sync-agent.cmd

# 项目路径或 Python 安装位置更换后，重新设置登录自动启动
.\内部agent\同步工具\sync-agent.cmd --install-autostart

# 取消登录自动启动，当前进程需要另用 --stop 停止
.\内部agent\同步工具\sync-agent.cmd --remove-autostart
```

工具只依赖 Python 3.10+ 的标准库，不依赖 AI 虚拟环境或模型 API。Windows 命令入口使用 PATH 中的 `python.exe` 及同目录的 `pythonw.exe`，隐藏运行，不需要调整 PowerShell 的脚本执行策略。登录启动快捷方式名为 `AI-Project-InternalAgent-Sync.lnk`，位于当前用户的 Windows 启动目录。

状态和滚动日志位于 `.sync/status.json`、`.sync/sync.log`，均不提交到 Git。状态中的时间使用北京时间。修改同步配置后，先 `--stop`，等待状态显示停止，再重新启动。

## 同步规则

这是从原项目到 `源文件/` 的单向同步。请在原后端修改代码；直接修改已管理副本会被下一轮同步覆盖。删除原文件会删除对应副本，因此本目录用于保留最新源码，不提供历史版本留存；历史恢复使用 Git。

同步只删除上次清单中登记、且本次源列表已经消失的副本文件；未登记的个人文件不会删除。源文件读取失败、Agent/网关根目录临时缺失时保留副本并记录错误，下轮自动重试。写入采用临时文件后替换，拒绝路径越界、符号链接和 Windows junction，避免误写原项目或其他目录。

本目录是相关源码副本，Java/前端部分仍依赖完整项目。它不保存 MySQL/Redis/Chroma 数据，也不替代数据库备份。运行链路和文件职责见 [注释说明.md](注释说明.md)。
