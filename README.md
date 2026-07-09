# rime-sync

Rime 输入法多设备配置同步系统。服务端管理 [rime-ice](https://github.com/iDvel/rime-ice) 词库、设备间用户输入词库同步、自定义词库生成；客户端（Python CLI）用于与服务器交互，支持 Windows 和 Android (Termux)。

## 架构

```
客户端 (Python CLI) ──HTTP API──▶ 服务器 (Flask + Waitress)
                                  ├── 配置管理 (*.custom.yaml)
                                  ├── 词库同步 (cn_dicts/, en_dicts/)
                                  ├── 用户输入词库同步 (sync/)
                                  └── 自定义词库生成 (makedict/)
```

## 功能

- **rime-ice 管理** — 服务器维护 rime-ice git 仓库，支持按需更新、版本追踪
- **词库同步** — 中文/英文词库的打包下载，客户端按需同步
- **用户输入词库同步** — 多设备间同步用户词库（上传/下载 tar 包或单文件），基于 `installation_id` 自动识别设备
- **自定义词库生成** — 服务器端可扩展脚本框架，接收版本参数生成 `.dict.yaml`
- **配置文件编辑** — 远程行级编辑 `*.custom.yaml` 等配置文件
- **完整配置同步** — 一键下载/上传完整 Rime 配置包，方便设备初始化
- **设备管理** — 列出已注册设备，查看各设备同步状态

## 快速开始

### 服务端

```bash
cd 服务器
pip install -r requirements.txt
# 编辑 config/server.json，配置主机、端口和线程数
python server.py
```

生产环境建议使用 systemd 守护运行，并配置日志轮转：

```bash
# 1. 复制服务文件（根据实际路径修改）
sudo cp 服务器/rime-server.service /etc/systemd/system/
sudo systemctl daemon-reload

# 2. 启用并启动服务
sudo systemctl enable rime-server
sudo systemctl start rime-server

# 3. 查看状态
sudo systemctl status rime-server
```

### 客户端

```bash
cd 客户端
pip install requests pyyaml
# 首次运行自动创建 client_config.json
python cli.py
# 编辑 client_config.json 填入服务器地址和 Rime 配置目录
```

客户端支持交互式菜单（无参数运行）和命令行模式：

```bash
python cli.py status                              # 服务器状态
python cli.py sync-userdb --action upload         # 上传用户词库（哈希增量）
python cli.py sync-userdb --action download       # 下载用户词库（哈希增量）
python cli.py sync-dict --category cn             # 同步中文词库
python cli.py sync-dict --category lua            # 同步 lua 脚本
python cli.py update-rime-ice                     # 更新 rime-ice
python cli.py run-script <name> <version>         # 单个脚本（自动添加词库）
python cli.py run-all-scripts <version>           # 批量脚本
python cli.py health                              # 健康检查
```

## 目录结构

```
rime-sync/
├── 服务器/                    # 服务端 (Flask + Waitress)
│   ├── server.py             # 主程序
│   ├── rime-server.service   # systemd 服务文件
│   ├── config/               # JSON 配置文件
│   ├── utils/                # 工具模块
│   │   ├── config_loader.py  # 配置加载与热重载（失败自动回滚）
│   │   ├── sync_manager.py   # 用户输入词库同步
│   │   ├── full_sync_manager.py  # 完整配置包同步
│   │   ├── dict_manager.py   # 词库管理
│   │   ├── rime_ice_manager.py   # rime-ice git 管理（带超时保护）
│   │   ├── script_runner.py  # 自定义词库脚本执行（进程组管理）
│   │   ├── config_uploader.py    # 配置文件上传
│   │   ├── file_editor.py    # 行级文件编辑
│   │   └── error_handler.py  # 统一错误处理
│   ├── makedict/             # 自定义词库生成脚本
│   ├── rime_ice_original/    # 上游 rime-ice (git clone)
│   ├── runtime/              # 提供给客户端的运行时文件
│   ├── sync/                 # 各设备用户输入词库
│   └── backups/              # 定期备份
├── 客户端/                    # Python CLI 客户端
│   ├── cli.py                # CLI 入口（22子命令 + 交互菜单）
│   ├── core/                 # 核心逻辑模块
│   │   ├── config.py         # 配置管理器
│   │   ├── api.py            # HTTP API 客户端
│   │   ├── sync.py           # 用户词库哈希增量同步
│   │   ├── dicts.py          # 配置增量同步 (SyncState)
│   │   ├── hash_utils.py     # SHA3-256 哈希计算
│   │   ├── fullsync.py       # 完整配置同步
│   │   ├── tar_utils.py      # tar 安全解压
│   │   ├── platform.py       # 平台相关（Weasel 启停）
│   │   ├── logs.py           # 日志归档/压缩/清理
│   │   └── errors.py         # 异常类
│   └── client_config.json    # 客户端配置
└── doc/                      # 设计文档
```

## 部署环境

- **服务端**: 树莓派 5 / Linux 服务器，Python 3.9+
  - WSGI: Waitress（生产级多线程）
  - 进程守护: systemd（自动重启、崩溃恢复）
  - 日志: RotatingFileHandler（自动轮转，默认 10MB × 5 份）
- **客户端**: Windows / Android (Termux)，Python 3.9+
- **同步方式**: HTTP API，tar 批量传输，SHA3-256 哈希校验
- **设备标识**: 从 Rime 的 `installation.yaml` 读取 `installation_id`

## 最近更新

- **客户端模块化重构**: 拆分单体脚本为 `core/` 模块库 + `cli.py` 薄 CLI 层
- **哈希增量同步**: 用户词库按 SHA3-256 diff 仅传输变更文件；配置通过 SyncState + since 参数实现增量下载
- **新增命令**: `run-all-scripts`（批量脚本执行）、`list-scripts`（列出可用脚本）
- **`run-script` 增强**: 自动将生成词库插入 `rime_ice.dict.yaml`（可通过 `--no-add-to-dict` 禁用）
- 使用 **Waitress** 替代 Flask 开发服务器，提升生产环境稳定性
- 修复 `send_file` 流式传输与临时文件删除的竞态条件
- 日志系统升级为 **RotatingFileHandler**，防止磁盘占满
- Git 操作（clone/fetch/pull）添加 **120 秒超时保护**
- `copy_to_runtime` 增加**备份-复制-恢复**机制，防止更新失败导致服务中断
