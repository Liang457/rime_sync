# rime-server

Rime 输入法多设备配置同步服务器。管理 [rime-ice](https://github.com/iDvel/rime-ice) 词库、设备间用户输入词库同步、自定义词库生成，并提供 HTTP API 供各类客户端（CLI / Android）调用。

## 架构

```
客户端 (CLI / Android) ──HTTP API──▶ rime-server (Flask + Waitress)
                                      ├── 配置管理 (*.custom.yaml)
                                      ├── 词库同步 (cn_dicts/, en_dicts/)
                                      ├── 用户输入词库同步 (sync/)
                                      └── 自定义词库生成 (makedict/)
```

## 功能

- **rime-ice 管理** — 维护 rime-ice git 仓库，支持按需更新、版本追踪
- **词库同步** — 中文/英文词库的打包下载，客户端按需同步
- **用户输入词库同步** — 多设备间同步用户词库（上传/下载 tar 包或单文件），基于 `installation_id` 自动识别设备
- **自定义词库生成** — 可扩展脚本框架，接收版本参数生成 `.dict.yaml`
- **配置文件编辑** — 远程行级编辑 `*.custom.yaml` 等配置文件
- **完整配置同步** — 一键下载/上传完整 Rime 配置包，方便设备初始化
- **设备管理** — 列出已注册设备，查看各设备同步状态

## 快速开始

```bash
pip install -r requirements.txt
# 编辑 config/server.json，配置主机、端口和线程数
python server.py
```

生产环境建议使用 systemd 守护运行，并配置日志轮转：

```bash
# 1. 复制服务文件（根据实际路径修改）
sudo cp rime-server.service /etc/systemd/system/
sudo systemctl daemon-reload

# 2. 启用并启动服务
sudo systemctl enable rime-server
sudo systemctl start rime-server

# 3. 查看状态
sudo systemctl status rime-server
```

## 目录结构

```
rime-server/
├── server.py             # 主程序 (Flask + Waitress)
├── rime-server.service   # systemd 服务文件
├── start_server.sh       # 启动脚本
├── DEPLOYMENT.md         # 部署指南 + API 文档
├── config/               # JSON 配置文件
│   ├── server.json       #   服务器基本配置（host/port/token 等）
│   ├── sync.json         #   用户词库同步配置
│   ├── dict.json         #   词库管理配置
│   ├── script.json       #   脚本执行配置（trusted_users）
│   └── devices.json      #   设备信息配置
├── custom_files/         # 自定义文件映射
├── makedict/             # 自定义词库生成脚本 (make_ba/sr/yh/ys/zzz)
├── utils/                # 工具模块
│   ├── config_loader.py  #   配置加载与热重载（失败自动回滚）
│   ├── sync_manager.py   #   用户输入词库同步
│   ├── full_sync_manager.py  # 完整配置包同步
│   ├── dict_manager.py   #   词库管理
│   ├── rime_ice_manager.py  # rime-ice git 管理（带超时保护）
│   ├── script_runner.py  #   自定义词库脚本执行（进程组管理）
│   ├── config_uploader.py   # 配置文件上传
│   ├── file_editor.py    #   行级文件编辑
│   └── error_handler.py  #   统一错误处理
├── rime_ice_original/    # 上游 rime-ice (git clone，运行时生成)
├── runtime/              # 提供给客户端的运行时文件（运行时生成）
├── sync/                 # 各设备用户输入词库（运行时生成）
└── backups/              # 定期备份（运行时生成）
```

## 部署环境

- 树莓派 5 / Linux 服务器，Python 3.12+
- WSGI: Waitress（生产级多线程）
- 进程守护: systemd（自动重启、崩溃恢复）
- 日志: RotatingFileHandler（自动轮转，默认 10MB × 5 份）
- 监听: `0.0.0.0:10032`（`config/server.json`）

## API 认证（api_token）

`config/server.json` 中的 `server.api_token` 控制 API 访问认证：

- 为空（默认）：不启用认证，所有请求放行
- 非空：所有 `/api/*` 请求必须携带请求头 `X-Api-Token: <token>`，否则返回 401

Token 以明文 HTTP 传输——仅在可信局域网或 TLS 终止代理后使用。

## API 文档

启动后访问 `http://<服务器IP>:10032/` 查看 API 基本信息。主要端点见 `DEPLOYMENT.md`，包括：health、status、rime_ice 更新、remote_sync、file 编辑、makedict 脚本执行、config/sync/dict/full_sync 上传下载、device 列表等。

## 相关仓库

- **客户端 CLI**: [rime_sync_cli](https://github.com/Liang457/rime_sync_cli)
- **安卓客户端**: [rime_sync_android](https://github.com/Liang457/rime_sync_android)