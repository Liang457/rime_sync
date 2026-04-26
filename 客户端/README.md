# rime_client.py

`rime_client.py` 是 [rime-server](https://github.com/i23386/rime_server) 的 Windows 客户端同步脚本，用于与 rime-server 交互，实现 Rime 输入法配置的同步与管理。

---

## 功能特性

- **交互式 CLI**：无参数运行时提供菜单驱动的交互界面，操作简单直观
- **命令行模式**：支持丰富的子命令，适合脚本化、定时任务等场景
- **rime-ice 仓库更新**：请求服务器拉取最新的 rime-ice 源码
- **自定义词库脚本**：远程触发服务器上的词库生成脚本
- **普通词库同步**：下载/同步 `cn_dicts/`、`en_dicts/` 等词库文件
- **用户输入词库同步**：
  - 自动读取 `installation.yaml` 获取设备标识
  - 打包上传本机 `sync/<device_name>/` 目录
  - 下载其他设备的用户词库到本地对应目录
- **完整同步**：下载服务器完整配置包，或上传本地配置初始化服务器
- **配置文件编辑**：支持远程编辑服务器上的配置文件
- **自动配置迁移**：支持旧版配置格式平滑迁移到新版

---

## 安装要求

- Python 3.9+
- 依赖库：`requests`、`pyyaml`

安装依赖：

```bash
pip install requests pyyaml
```

---

## 快速开始

1. 将 `rime_client.py` 放到你的 Rime 配置目录（如 `%APPDATA%\Rime`）
2. 首次运行时会自动创建 `client_config.json`：

```bash
python rime_client.py
```

3. 编辑 `client_config.json`，填写正确的服务器地址和本地 Rime 配置目录
4. 再次运行即可开始使用

---

## 配置文件

`client_config.json` 示例：

```json
{
  "server": {
    "url": "http://192.168.1.100:10032",
    "timeout": 30,
    "retry_count": 3,
    "verify_ssl": false
  },
  "rime": {
    "config_dir": "C:\\Users\\Username\\AppData\\Roaming\\Rime",
    "platform": "windows",
    "android_trime_config": ""
  },
  "sync": {
    "device_name": "",
    "auto_sync_on_start": false,
    "exclude_patterns": [
      "*.userdb.txt.backup",
      "*.log",
      "temp/*",
      "installation.yaml",
      ".github/*",
      "build/*",
      "rime_ice.userdb"
    ],
    "conflict_resolution": "latest"
  },
  "logging": {
    "level": "INFO",
    "file": "rime_client.log",
    "max_size_mb": 10
  }
}
```

> **提示**：`device_name` 留空时会自动从 `installation.yaml` 中读取 `installation_id`。

---

## 使用方式

### 交互式菜单（推荐新手使用）

直接运行脚本，不带任何参数：

```bash
python rime_client.py
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
 1. 请求服务器更新 rime-ice 仓库
 2. 执行自定义词库脚本
 3. 同步用户输入词库
 4. 同步普通词库 (cn_dicts/en_dicts)
 5. 编辑配置文件
 6. 完整同步 (下载/上传)
 7. 查看同步状态
 8. 获取设备列表
 9. 健康检查
 10. 修改配置
 11. 退出

选择 [1-11]:
```

### 命令行模式（适合自动化）

```bash
# 通用选项
python rime_client.py --help
python rime_client.py --config ./custom_config.json
python rime_client.py -v

# 服务器状态
python rime_client.py status

# 更新 rime-ice（可加 --force 强制更新）
python rime_client.py update-rime-ice

# 运行自定义词库脚本
python rime_client.py run-script yuanshen 6.5.1

# 同步用户输入词库
python rime_client.py sync-userdb --action upload          # 上传本机词库
python rime_client.py sync-userdb --action download        # 下载其他设备词库

# 同步普通词库
python rime_client.py sync-dict                # 同步全部
python rime_client.py sync-dict --category cn  # 仅同步中文词库

# 完整同步
python rime_client.py full-sync-download       # 从服务器下载完整配置
python rime_client.py full-sync-upload backup.zip --overwrite  # 上传配置初始化服务器

# 查看设备列表和同步信息
python rime_client.py device-list
python rime_client.py sync-info

# 健康检查
python rime_client.py health

# 强制进入交互式菜单
python rime_client.py interactive
```

---

## 完整命令列表

| 命令 | 说明 |
|------|------|
| `status` | 获取服务器状态 |
| `update-rime-ice` | 请求更新 rime-ice 仓库 |
| `run-script <name> <version>` | 执行自定义词库生成脚本 |
| `edit-file <path> <line> <content>` | 编辑服务器上的配置文件 |
| `upload-config <file>` | 上传 `*.custom.yaml` 配置文件 |
| `sync-userdb` | 同步用户输入词库（上传/下载） |
| `sync-upload-zip` | 上传用户词库 ZIP 包 |
| `sync-upload-file <file>` | 上传单个用户词库文件 |
| `sync-info` | 查看用户词库同步信息 |
| `sync-download-zip` | 下载用户词库 ZIP 包 |
| `sync-download-file <filename>` | 下载单个用户词库文件 |
| `sync-dict` | 同步普通词库 |
| `dict-info` | 查看词库信息 |
| `dict-download-zip` | 下载词库 ZIP 包 |
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
rime_server/
├── rime_client.py          # 主程序（本文件）
├── client_config.json      # 客户端配置文件（自动创建）
├── rime_client.log         # 运行日志
├── run_win.ps1             # Windows 快速启动脚本
├── doc/                    # 设计文档
│   ├── 客户端设计.md
│   ├── 服务端设计.md
│   ├── 系统设计.md
│   ├── 项目大纲.md
│   └── 客户端规划.md
└── venv/                   # Python 虚拟环境
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
