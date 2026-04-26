# rime-sync

Rime 输入法多设备配置同步系统。服务端管理 [rime-ice](https://github.com/iDvel/rime-ice) 词库、设备间用户输入词库同步、自定义词库生成；客户端（Python CLI）用于与服务器交互，支持 Windows 和 Android (Termux)。

## 架构

```
客户端 (Python CLI) ──HTTP API──▶ 服务器 (Flask)
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
# 编辑 config/server.json，配置主机和端口
python server.py
```

### 客户端

```bash
cd 客户端
pip install requests pyyaml
# 首次运行自动创建 client_config.json
python rime_client.py
# 编辑 client_config.json 填入服务器地址和 Rime 配置目录
```

客户端支持交互式菜单（无参数运行）和命令行模式：

```bash
python rime_client.py status                    # 服务器状态
python rime_client.py sync-userdb --action upload   # 上传用户词库
python rime_client.py sync-userdb --action download # 下载用户词库
python rime_client.py sync-dict --category cn       # 同步中文词库
python rime_client.py update-rime-ice               # 更新 rime-ice
python rime_client.py health                        # 健康检查
```

## 目录结构

```
rime-sync/
├── 服务器/                    # Flask 服务端
│   ├── server.py             # 主程序
│   ├── config/               # JSON 配置文件
│   ├── utils/                # 工具模块
│   │   ├── config_loader.py  # 配置加载与热重载
│   │   ├── sync_manager.py   # 用户输入词库同步
│   │   ├── full_sync_manager.py  # 完整配置包同步
│   │   ├── dict_manager.py   # 词库管理
│   │   ├── rime_ice_manager.py   # rime-ice git 管理
│   │   ├── script_runner.py  # 自定义词库脚本执行
│   │   ├── config_uploader.py    # 配置文件上传
│   │   ├── file_editor.py    # 行级文件编辑
│   │   └── error_handler.py  # 统一错误处理
│   ├── makedict/             # 自定义词库生成脚本
│   ├── rime_ice_original/    # 上游 rime-ice (git clone)
│   ├── runtime/              # 提供给客户端的运行时文件
│   ├── sync/                 # 各设备用户输入词库
│   └── backups/              # 定期备份
├── 客户端/                    # Python CLI 客户端
│   ├── rime_client.py        # 主程序
│   └── client_config.json    # 客户端配置
└── doc/                      # 设计文档
```

## 部署环境

- **服务端**: 树莓派 5，Python 3.9+，Flask
- **客户端**: Windows / Android (Termux)，Python 3.9+
- **同步方式**: HTTP API，tar 批量传输，SHA3-256 哈希校验
- **设备标识**: 从 Rime 的 `installation.yaml` 读取 `installation_id`

## 许可证

MIT
