# cli.py

`cli.py` 是 rime-server 的客户端同步工具，用于与 rime-server 交互，实现 Rime 输入法配置的多设备同步与管理。支持 Windows 和 Android (Termux)。

---

## 功能特性

- **交互式 CLI**：无参数运行时提供菜单驱动的交互界面，操作简单直观
- **命令行模式**：支持 23 个子命令，适合脚本化、定时任务等场景
- **远端批量同步**：一键完成「更新 rime-ice + 复制 runtime + 批量运行词库脚本 + 自动插入词库」完整流程
- **rime-ice 仓库更新**：请求服务器拉取最新的 rime-ice 源码
- **自定义词库脚本**：远程触发服务器上的词库生成脚本（单个/批量），自动插入词库到配置
- **配置哈希增量同步**：按类别（cn/en/lua/opencc）通过 SHA3-256 哈希对比实现增量同步
- **用户输入词库哈希增量同步**：
  - 自动读取 `installation.yaml` 获取设备标识
  - 对比本地与远端 SHA3-256 哈希，仅传输变更文件
  - 冲突按 mtime 较新者胜出
- **完整同步**：下载服务器完整配置包，或上传本地配置初始化服务器
- **配置文件编辑**：支持远程编辑服务器上的配置文件
- **自动配置迁移**：支持旧版配置格式平滑迁移到新版

---

## 安装要求

- Python 3.12+（tar 解压依赖 `filter='data'`）
- 依赖库：`requests`、`pyyaml`

安装依赖：

```bash
pip install requests pyyaml
```

---

## 快速开始

1. 将 `cli.py` 和 `core/` 目录放到你的 Rime 配置目录（如 `%APPDATA%\Rime`）
2. 安装依赖：

```bash
pip install requests pyyaml
```

3. 首次运行时会自动创建 `client_config.json`：

```bash
python cli.py
```

4. 编辑 `client_config.json`，填写正确的服务器地址和本地 Rime 配置目录
5. 再次运行即可开始使用

---

## 配置文件

`client_config.json` 示例：

```json
{
  "server": {
    "url": "http://192.168.1.100:10032",
    "timeout": 30,
    "retry_count": 3,
    "verify_ssl": false,
    "api_token": ""
  },
  "rime": {
    "config_dir": "C:\\Users\\Username\\AppData\\Roaming\\Rime",
    "platform": "windows",
    "android_trime_config": ""
  },
  "sync": {
    "device_name": ""
  },
  "logging": {
    "level": "INFO",
    "file": "rime_client.log",
    "max_size_mb": 10
  }
}
```

> **提示**：`device_name` 留空时会自动从 `installation.yaml` 中读取 `installation_id`。
> **API 认证**：若服务器配置了 `api_token`，客户端 `server.api_token` 需填写相同值；旧配置文件缺少该选项时会自动补充 `""` 并保存。

---

## 使用方式

### 交互式菜单（推荐新手使用）

```bash
python cli.py
```

会显示如下菜单：

```
==================================================
Rime 客户端 - 交互式菜单
==================================================
当前设备: Win
服务器: http://192.168.1.100:10032
Rime 配置目录: C:\Users\Username\AppData\Roaming\Rime

✓ 服务器连接正常

请选择操作:
 1. 远端批量同步 (更新rime-ice + 全部词库脚本)
 2. 请求服务器更新 rime-ice 仓库
 3. 执行自定义词库脚本（单个/全部列出/批量执行）
 4. 同步用户输入词库（哈希增量）
 5. 更新词库 (cn/en/lua/opencc/全部)
 6. 编辑配置文件
 7. 完整同步 (下载/上传)
 8. 查看同步状态
 9. 设备列表
 10. 健康检查
 11. 修改配置
 12. 退出

选择 [1-12]:
```

### 命令行模式（适合自动化）

```bash
# 通用选项
python cli.py --help
python cli.py --config ./custom_config.json
python cli.py -v

# 服务器状态
python cli.py status

# 更新 rime-ice（可加 --force 强制更新）
python cli.py update-rime-ice

# 远端批量同步（更新rime-ice + 复制runtime + 全部词库脚本 + 自动插入词库）
python cli.py remote-sync                     # 默认强制更新 rime-ice
python cli.py remote-sync 6.5.1               # 指定版本号
python cli.py remote-sync --no-force          # 不强制更新
python cli.py remote-sync --no-add-to-dict    # 不自动插入 rime_ice.dict.yaml

# 运行自定义词库脚本（version 可选，缺省时由服务器分配时间版本）
python cli.py run-script yuanshen 6.5.1              # 单个（自动添加词库）
python cli.py run-script yuanshen 6.5.1 --no-add-to-dict  # 不自动添加
python cli.py run-script yuanshen                    # 不传版本（服务器分配）
python cli.py run-all-scripts 6.5.1                  # 批量执行
python cli.py run-all-scripts                        # 批量执行（服务器分配版本）
python cli.py list-scripts                           # 列出可用脚本

# 同步用户输入词库（哈希增量对比，仅传输变更文件）
python cli.py sync-userdb --action upload            # 上传本机词库
python cli.py sync-userdb --action download          # 下载其他设备词库

# 更新词库（哈希增量）
python cli.py sync-dict                              # 同步全部 (cn/en/lua/opencc)
python cli.py sync-dict --category cn                # 仅同步中文词库
python cli.py sync-dict --category lua               # 同步 lua 脚本
python cli.py sync-dict --category opencc            # 同步 OpenCC 配置

# 完整同步
python cli.py full-sync-download                     # 从服务器下载完整配置
python cli.py full-sync-upload backup.zip --overwrite # 上传配置初始化服务器

# 查看设备列表和同步信息
python cli.py device-list
python cli.py sync-info

# 健康检查
python cli.py health

# 强制进入交互式菜单
python cli.py interactive
```

---

## 完整命令列表

| 命令 | 说明 |
|------|------|
| `status` | 获取服务器状态 |
| `update-rime-ice` | 请求更新 rime-ice 仓库（`--force` 强制从上游拉取；仅 commit 实际变化时才重建 runtime） |
| `copy-to-runtime` | 强制重建 runtime 目录（生成词库自动从备份回填，保留 mtime） |
| `remote-sync [version]` | 远端批量同步（更新rime-ice + 复制runtime + 全部词库脚本 + 自动插入词库；默认强制更新，可用 `--no-force`/`--no-add-to-dict`/`--dict-line` 调整） |
| `run-script <name> [version]` | 执行单个词库脚本（自动添加到 dict.yaml；version 缺省时由服务器分配） |
| `run-all-scripts [version]` | 批量执行全部词库脚本 |
| `list-scripts` | 列出服务器可用脚本 |
| `edit-file <path> <line> <content>` | 编辑服务器上的配置文件 |
| `upload-config <file>` | 上传 `*.custom.yaml` 配置文件 |
| `sync-userdb` | 同步用户输入词库（哈希增量上传/下载） |
| `sync-upload-tar` | 上传用户词库 tar 包 |
| `sync-upload-file <file>` | 上传单个用户词库文件 |
| `sync-info` | 查看用户词库同步信息 |
| `sync-download-tar` | 下载用户词库 tar 包 |
| `sync-download-file <filename>` | 下载单个用户词库文件 |
| `sync-dict` | 更新词库（cn/en/lua/opencc，哈希增量） |
| `dict-info` | 查看词库信息 |
| `dict-download-tar` | 下载词库 tar 包 |
| `dict-download-file <filename>` | 下载单个词库文件 |
| `full-sync-info` | 查看完整配置包信息 |
| `full-sync-download` | 下载完整配置包 |
| `full-sync-upload <file>` | 上传完整配置包 |
| `device-list` | 列出已注册设备 |
| `health` | 健康检查 |
| `interactive` | 启动交互式菜单 |

---

## 项目文件结构

```
客户端/
├── cli.py                   # CLI 入口（23子命令 + 交互菜单）
├── core/                    # 核心逻辑模块库
│   ├── __init__.py
│   ├── config.py            # 配置管理器
│   ├── api.py               # HTTP API 客户端
│   ├── sync.py              # 用户词库哈希增量同步
│   ├── dicts.py             # 配置增量同步 (SyncState)
│   ├── hash_utils.py        # SHA3-256 哈希计算
│   ├── fullsync.py          # 完整配置同步
│   ├── tar_utils.py         # tar 安全解压
│   ├── platform.py          # 平台相关（Weasel 启停）
│   ├── logs.py              # 日志归档/压缩/清理
│   └── errors.py            # 异常类
├── client_config.json       # 客户端配置文件（自动创建）
├── run_win.ps1              # Windows 快速启动脚本
├── 快速同步.ps1              # 快速同步脚本
└── venv/                    # Python 虚拟环境
```

---

## 注意事项

- 请确保服务器地址和本地 Rime 配置目录正确填写
- `installation.yaml` 是设备标识的重要依据，请勿随意修改
- 上传完整配置包会覆盖服务器现有配置，请谨慎操作
- 建议在可信网络环境下使用，或配置 HTTPS
- 定期备份 `sync/` 目录和重要的自定义配置文件

---

## 设计文档

更多架构和实现细节请参考 `doc/` 目录下的设计文档：

- [`doc/客户端设计.md`](doc/客户端设计.md) — 客户端详细设计
- [`doc/客户端规划.md`](doc/客户端规划.md) — 功能规划概要
- [`doc/项目大纲.md`](doc/项目大纲.md) — 项目整体大纲
- [`doc/服务端设计.md`](doc/服务端设计.md) — 服务端设计
- [`doc/系统设计.md`](doc/系统设计.md) — 系统架构设计

---

*本客户端为 rime-server 项目配套工具，旨在简化 Rime 输入法的多设备同步流程。*
