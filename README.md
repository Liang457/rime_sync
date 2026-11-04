# rime-sync 服务器

个人 Rime 输入法分发与同步系统的服务端。核心边界：**只管理文件，不执行任何
代码**。服务器维护一份带 manifest 的统一文件库（词库 / lua / opencc / 方案
配置），向各设备提供差量同步 API 与用户词库快照中转，并带一个 Web 控制台。

```
rime_dict（本地数据工程）──publish──▶ rime_sync 服务器 ◀──同步 API──▶ 小狼毫 / 同文等设备
                                      ├── store/files + manifest.json（统一文件库）
                                      ├── store/base（上游 rime-ice 基座，git 只读克隆）
                                      ├── sync/<设备>/（用户词库快照中转，librime 在客户端合并）
                                      └── Web 控制台（上传词库 / 编辑配置 / 基座 / 设备）
```

本仓库是 v2 全量重构版：v1 的 makedict 脚本执行、remote_sync 编排、行号配置
编辑、22 端点全部移除（旧实现见 git 历史）。`makedict/` 目录保留，是因为
`rime_dict/research/fetch_glossary_wiki.py` 直接引用其中的 Wiki 爬虫——它现在
只作为 rime_dict 的本地爬虫库，服务器运行时完全不碰它。

## 功能

- 统一文件库：所有分发内容都是 `store/files/` 下的文件加一份 `manifest.json`
  （sha3-256 / size / mtime / version / source），客户端只对 manifest 做差量。
- 8 个 API：manifest、单文件/打包下载、publish（sha3 幂等）、用户词库推拉、
  health、status。
- Web 控制台：仪表盘 / 词库文件 / 配置管理（在线编辑）/ 上游基座（git 拉取
  加重建基线）/ 设备。
- 上游基座：rime-ice 只读克隆；重建基线时基座覆盖 base 来源文件，其他来源
  （publish/console/upload/migrate）受保护，可选强制接管。
- 发布流：`POST /api/publish` 供 rime_dict 一条命令发布，控制台上传作备用入口。

## 快速开始

需要 Python 3.12+（tar 解压用 `filter='data'`）和 git（基座功能用）。

```bash
./start.sh          # 首次运行自动建 .venv 装依赖
# 或手动：
pip install -r requirements.txt
python run.py
```

默认监听 `0.0.0.0:10033`（`config/server.json`），控制台在
`http://<主机>:<端口>/`。

注：控制台界面为 MD3 风格，控件使用官方
[@material/web](https://github.com/material-components/material-web) 组件
（锁定 2.2.0，经 esm.run CDN 加载）加主题 token CSS（浅/深跟随系统）。
浏览器需要能访问 esm.run 与 fonts.googleapis.com，否则控件不会升级渲染。
下拉框使用原生 `<select>`（MD3 配色）——`md-select` 在 Firefox 存在
「菜单打开即关闭」的组件 bug。深浅色之外无其他主题档位。

### 管理命令

```bash
python manage.py set-password          # 控制台登录密码（公网暴露前必设）
python manage.py clear-password
python manage.py import-runtime <旧runtime目录>   # v1 runtime/ 数据迁入文件库
python manage.py import-sync <旧sync目录>          # v1 各设备用户词库迁入（含 devices.json 元数据）
```

### 配置（config/server.json，首次运行自动生成）

| 键 | 说明 |
|---|---|
| `server.host` / `server.port` | 监听地址，默认 0.0.0.0:10033 |
| `server.api_token` | 旧版单 token，仍然有效（兼容存量客户端配置） |
| `server.tokens` | API token 列表（`[{token, label, created}]`），在控制台「设备」页签发/吊销 |
| `console.password_hash` | sha3-256；空表示控制台免登录（仅限可信局域网） |
| `base.repo_url` | 上游基座仓库，默认 rime-ice |
| `limits.max_upload_mb` | 上传大小上限 |

认证规则：未配置任何 token 时 API 免认证；配置后除 `/api/health` 外都要带
`X-Api-Token`（命中 `api_token` 或 `tokens` 之一即可）。建议每台设备签发一个
token，泄漏就吊销。

### 词库上传与 rime-ice 联动

- 控制台上传：选目标目录（默认 `cn_dicts`），拖入或点选文件后上传；同名文件
  会列出并询问（可「全部替换」）；不填版本号，按源文件本身识别。
- 自动联动：`cn_dicts/<名>.dict.yaml` 的发布（API）/上传/删除会自动维护
  `rime_ice.dict.yaml` 的 `import_tables`；基座重建后也会重放。联动只增删
  自己纳管的词库名（记录在 `store/imports.json`），基座自带条目（8105 等）
  永不触碰；`rime_ice.dict.yaml` 不存在时（基座未导入）自动跳过。
- 也可在「配置管理」里手动编辑该文件，保存同样走 manifest 差量。

## API 一览（8 个）

| 端点 | 方法 | 用途 |
|---|---|---|
| `/api/manifest` | GET | 全量清单，客户端差量依据 |
| `/api/files/get/<path>` | GET | 单文件下载 |
| `/api/files/get?paths=a,b` / `?all=1` | GET | tar.gz 打包下载（重建/首装） |
| `/api/publish` | POST | 发布文件（multipart file/files 加 path/version/source，sha3 幂等） |
| `/api/userdb/push` | POST | 上传本机用户词库快照（tar.gz 加 device） |
| `/api/userdb/pull?device=<本机>` | GET | 下载其他设备快照合集（tar.gz），librime 在客户端合并 |
| `/api/health` | GET | 健康检查（免认证） |
| `/api/status` | GET | 版本 / 文件数 / 设备数 / 基座状态 |

## 部署（Linux + systemd）

```bash
sudo cp rime-server.service /etc/systemd/system/   # 先改里面的路径
sudo systemctl daemon-reload && sudo systemctl enable --now rime-server
```

## 从 v1 迁移

1. 备份旧 `runtime/`、`sync/`、`config/devices.json`。
2. 新版启动后 `python manage.py import-runtime <旧runtime>`：全部文件以
   `source=migrate` 入库（受基座重建保护）。
3. `python manage.py import-sync <旧sync目录>`：各设备快照迁入 `sync/<设备>/`。
4. 设备端换用 v2 协议客户端（CLI 同步版 / 内置同步的输入法 fork）。

## 开发

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt
.venv/Scripts/python -m pytest tests -q
```

开发规约与各模块注意事项见 `AGENTS.md`。

## 相关项目

- [rime_dict](../rime_dict)——词库生成（数据工程），`pipeline/publish.py`
  一条命令发布到本服务器。
- [rime_sync_cli](https://github.com/Liang457/rime_sync_cli)——同步专用 CLI
  客户端（v2 协议）。
- 上游：[rime-ice](https://github.com/iDvel/rime-ice)（基座，只读）。
