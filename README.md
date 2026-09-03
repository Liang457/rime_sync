# rime-sync 服务器

rime-sync 的服务器端（`rime-server`）。负责维护 [rime-ice](https://github.com/iDvel/rime-ice) 仓库、给各设备分发词库、同步用户输入词库，并提供 HTTP API 给 CLI 和 Android 客户端调用。

```
客户端 (CLI / Android) ──HTTP API──▶ rime-server (Flask + Waitress)
                                    ├── 配置管理 (*.custom.yaml)
                                    ├── 词库同步 (cn_dicts/, en_dicts/)
                                    ├── 用户输入词库同步 (sync/)
                                    └── 自定义词库生成 (makedict/)
```

## 功能

- **rime-ice 管理**：维护上游 rime-ice 仓库，按需更新，仅在新 commit 时重建 runtime
- **词库同步**：中文/英文词库打包下发，客户端按类别增量同步
- **用户输入词库同步**：以 `installation_id` 区分设备，上传/下载 tar 包或单文件
- **自定义词库生成**：`makedict/` 下的脚本框架，传版本号生成 `.dict.yaml`，按内容去重后插入词库
- **配置文件编辑**：远程行级修改 `*.custom.yaml` 等配置
- **完整配置同步**：整体下载/上传配置包，用于设备初始化
- **设备管理**：列出已注册设备及同步状态

## 快速开始

需要 Python 3.12+（tar 解压用到 `filter='data'`）。

```bash
pip install -r requirements.txt
# 按需改 config/server.json 里的 host/port
python server.py
```

默认监听 `0.0.0.0:10032`。

生产环境用 systemd 守护：

```bash
sudo cp rime-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rime-server
sudo systemctl status rime-server
```

`rime-server.service` 里的路径要按实际环境改。日志用 RotatingFileHandler 轮转（默认 10MB × 5 份），旧日志归档到 `logs/archive/`，保留 90 天。

## 配置

配置都在 `config/*.json`，启动时加载，缺项自动补默认值并写回：

| 文件 | 作用 |
|------|------|
| `server.json` | 监听地址、端口、日志、上传大小限制、`api_token` |
| `sync.json` | 用户词库同步限制、`_manifest.json` |
| `dict.json` | 词库路径与允许的后缀 |
| `script.json` | 脚本执行超时、`trusted_users` |
| `devices.json` | 已注册设备 |

### API 认证

`server.api_token` 为空（默认）时不认证；非空时所有 `/api/*` 请求必须带 `X-Api-Token` 头，否则返回 401。Token 明文传输，只适合可信局域网或 TLS 终止代理后面。

## 目录结构

```
rime_sync/
├── server.py              # 入口，Flask + Waitress，22 个 /api/* 路由
├── rime-server.service    # systemd 服务模板
├── start_server.sh        # 启动脚本
├── DEPLOYMENT.md          # 部署与 API 端点说明
├── config/                # JSON 配置
├── custom_files/          # custom_map.json 覆盖映射
├── makedict/              # 自定义词库脚本 make_ba/sr/yh/ys/zzz
├── utils/                 # 工具模块
├── rime_ice_original/     # 上游 rime-ice 克隆（运行时生成）
├── runtime/               # 提供给客户端的文件（运行时生成）
├── sync/                  # 各设备用户输入词库（运行时生成）
└── backups/               # 定期备份（运行时生成）
```

`rime_ice_original/` 是上游仓库，别直接改；修改都发生在 `runtime/`。更新 rime-ice 时先按 `custom_map.json` 覆盖，再从备份回填生成的词库，保证脚本输出不丢。

## API 文档

启动后访问 `http://<服务器>:10032/` 可看基本信息。端点清单见 `DEPLOYMENT.md`，覆盖 health/status、rime_ice 更新、remote_sync、makedict、file 编辑、config/sync/dict/full_sync 上传下载、device 列表等。

## 相关项目

- [rime-sync CLI 客户端](https://github.com/Liang457/rime_sync_cli)
- [rime-sync Android 客户端](https://github.com/Liang457/rime_sync_android)