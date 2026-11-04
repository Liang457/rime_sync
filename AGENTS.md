# AGENTS.md — rime_sync

## 项目概述

rime-sync v2 是个人 Rime 输入法生态的分发服务器，技术栈为 Flask + Waitress +
Jinja2 + htmx（单文件 vendored）。核心边界只有一条：**只管理文件，不执行任何
代码**——v1 的脚本执行、remote_sync 编排已全部裁剪，不要以任何形式加回。

统一文件模型是整个设计的核心：一切分发内容都是 `store/files/` 下的文件加一份
`store/manifest.json`（path/sha3-256/size/mtime/version/source），客户端只对
manifest 做差量。不要再引入 dict/full_sync/config 之类按内容类型划分的多套
同步端点。

`source` 字段即 overlay 归属：`base` 为上游基座，`publish` 来自 rime_dict，
`console`/`upload` 来自控制台，`migrate` 来自旧数据迁移。基座重建
（`FileStore.rebuild_base`）只覆盖 base 来源，其余来源受保护，除非显式 force。

文档与注释使用中文。Python 3.12+（tar 解压用 `filter='data'`）。
有 pytest 测试套件（`tests/`），改动后运行：
`.venv/Scripts/python -m pytest tests -q`。

## 当前状态与待办（2026-11-04）

- v2 已落地并完成多轮控制台迭代（基座白名单、页面拆分、cron 自动更新、
  `.custom.yaml` 配置表单、词库开关与预设定制文件），`main`，pytest 127 用例
  全绿。
- 控制台有「关于」页与侧边栏常驻版本号（`/about`）。版本号是 `app/api.py`
  的 `SERVER_VERSION` 常量，当前 `2.0.0`，约定随功能更新手动 bump；`/api/health`
  的 `server_version` 字段被 `rime_sync_cli status` 消费，改名需同步客户端。
- 待办：部署机迁移（需用户本人 `git push` 后进行）。步骤：服务器 `git pull`
  → `manage.py import-runtime` → `manage.py import-sync` → systemd ExecStart
  指向 `run.py`（端口 10032 不变）。部署机首次 pull 后要在控制台点一次
  「更新基座并重建」——白名单生效会自动清退旧版误入库的 `.github/`、`*.md`
  等垃圾文件，客户端随 manifest 差量自动删除。
- 生态位：词库从 `rime_dict` 经 `/api/publish` 进入；下游客户端是
  `rime_sync_cli` 与 trime fork（工作区 `rime_sync_android`）。

## 运行

```bash
./start.sh        # 自动建 .venv（Windows: start.bat 或手动 python -m venv .venv）
python run.py     # 监听 config/server.json 的 host/port（沿用旧配置即 10032）
```

## 服务组件

入口是 `run.py` → `app/create_app()`。各服务对象（store/userdb/upstream/
settings/scheduler）挂在 `app.extensions` 上，测试直接取用；测试里 create_app
传 `run_scheduler=False`，避免后台线程搅局。

### store.py（统一文件库）

`app/services/store.py` 的 FileStore：全部变更走 `self._lock` 加 manifest 原子
写（tmp + replace），每次批次最多 revision 加一；sha3 相同即 unchanged（幂等）。

### api.py（8 个端点）

`app/api.py`：`/api/health` 永远免认证，其余走 `settings.token_ok`（多 token：
`server.tokens` 列表，兼容旧 `api_token` 单 token；比对用 hmac.compare_digest）。

警告：HTTP 响应头只能 latin-1。中文提示一律走 percent-encoded 的
`X-Toast-Data` 头，`HX-Trigger` 只放 ASCII 事件名（前端 base.html 的
htmx:afterRequest 监听解码后弹 toast）。若有新代码往响应头塞了非 ASCII，
中文 toast 会再出 latin-1 编码错误。

### console.py（控制台蓝图）

`app/console.py`：密码非空时整站走 session 登录；htmx 动作统一走 `respond()`
（渲染局部模板加 toast 头）；上传是 JSON 接口（同名冲突询问，replace=1 批量
替换），前端 fetch 消费。

### upstream.py（上游基座）

`app/services/upstream.py`：只做 `git clone --depth 1` / `pull --ff-only`，
绝不推送任何仓库；重建后自动重放 rime_ice 联动。

基座入库走白名单（`_is_runtime_file`）：`cn_dicts/en_dicts/lua/opencc` 整目录
加根目录 `*.yaml`/`*.txt`（排除 recipe.yaml）；`.github/`、`others/`、`*.md`、
`LICENSE`、`go.work` 等开发文件永不入库。白名单之外已入库的旧 base 文件随
下次重建自动清退。

`BaseManager._op_lock` 串行化 git 操作（手动按钮 / 调度器 / 改地址并发）；
`set_repo_url`（改远端）与 `reclone`（删目录重克隆，历史分叉时的逃生通道）
都在这里。

### scheduler.py（基座自动更新）

`app/services/scheduler.py`：daemon 线程，cron 表达式驱动
（`settings.base.auto_update` 加 `base.cron`，默认关；「上游基座」页开启）。
纯逻辑 `check_once(now)` 与线程分离，测试注入时间；不追欠账，失败只记
activity 不抛出。git 拉取与文件落库都是既有命令，无任何脚本执行。

### rime_ice.py（词库联动与开关）

`app/services/rime_ice.py`：cn_dicts 词库的发布/上传/删除/基座重建后，自动
维护 `rime_ice.dict.yaml` 的 import_tables，另提供「词库开关」（files 页卡片
加 `/files/toggle`）。

- 条目统一为 `cn_dicts/<名>` 路径形。裸名条目会被 librime 解析到配置根目录，
  挂不住 cn_dicts 下的文件；旧裸名条目在读取/保存时自动升级。
- 解析与改写是行级的：条目行尾注释与块内注释行原样保留，只增删条目行；
  字表类（纯数字名）启用后紧跟 8105 之下，其余追加末尾。
- 选择持久化在 `store/imports.json` 三份名单：managed（联动写入的，文件删除
  则引用撤销）/ disabled（显式关闭，重放时移除）/ enabled（显式启用，基座
  注释态的如 41448 重放时补回，只补文件在库的条目）。兼容旧版纯列表格式。
- `rime_ice.dict.yaml` 不存在时（基座未导入）自动跳过。

### custom_yaml.py 与 config_options.py（配置表单）

定制统一走 librime patch（`X.custom.yaml` 覆盖 `X.yaml`），source=console，
基座重建永不覆盖。

- `app/services/custom_yaml.py`：patch 解析/合并/序列化，统一 slash 路径风格
  （`menu/page_size: 6`）；嵌套与 slash 混写报错；删除键即恢复基座默认；
  表单保存保留用户手写的未知键。PyYAML safe_load/safe_dump 纯文本操作。
- `app/services/config_options.py`：「常用设置」注册表，首版只覆盖
  `default.custom.yaml`（方案列表/菜单/中英切换；以词定字已下架，高级定制走
  源码模式）。weasel/squirrel/trime 等走源码模式，要表单化时往 `TARGETS`
  加组。同文件里的 `PRESETS` 是预设定制文件注册表（default/rime_ice/weasel/
  squirrel/trime 五个 custom.yaml，模板带常用键注释），`/configs/preset`
  一键创建加 HX-Redirect 直达；缺失时基座文件警示条也给一键创建按钮
  （editor 上下文的 `preset_custom` 变量，configs.html 的 include 必须显式
  传入）。
- 表单值约定（`console.configs_patch_save`）：`opt::<key>`（空即删键；bool 用
  true/false）、`hotkey::<value>` 多选框（全不选即删键）、
  `opt::schema_list_order` 逗号分隔方案顺序（第一项为默认方案）。
- 配置页双 Tab：常用设置 / 源码（partials/config_form.html 加 config_source.html）；
  编辑 base 来源文件时显示「会被基座更新覆盖」警示条。

### userdb.py（用户词库中转）

`app/services/userdb.py`：设备快照按 `sync/<installation_id>/` 分桶中转；合并
永远在客户端（librime UserDbMerger）完成，服务器不做任何合并。

### 页面拆分

词库文件页只显示非 base 来源（自定义内容）；上游基座页是基座文件全览
（搜索加下载/删除）。两页互相留了跳转提示。

## 控制台前端注意事项

以下均为实测踩坑后定下的模式，不要回退：

- 危险操作（删除/吊销）模式：按钮 class 为 `danger-action`，带 data-post/
  vals/confirm/remove-row/refresh 属性，base.html 全局委托 → confirmDialog
  （原生 dialog 加手动 resolve，closeConfirm(true/false)）→ fetch 直发 →
  行移除或触发表格自刷新事件。不要改回 hx-confirm 加 issueRequest——
  htmx 1.9.12 被 preventDefault 接管后，issueRequest 在部分状态下会静默丢
  请求（删词库按钮全死的根因）。
- 不要用 `md-select`：Firefox 上菜单打开即关闭（组件 bug）。下拉一律用原生
  `.md-select`（MD3 配色）。md-dialog 没有 showModal，确认框用原生 dialog。
- `md-outlined-text-field` 坑：子节点文本到 value 的初始值迁移在 Chromium 下
  （整页加载与 htmx swap 均如此）不生效。config_source.html 尾部的
  `customElements.whenDefined` 兜底脚本负责补 value，不要删。
- 模板 include 坑：include 的局部模板取的是「最近作用域」变量——外层模板已有
  同名变量（如 files.html 的 `rows`）时会拿到外层值。partials/toggles.html
  这类复用名模板必须用 `{% with %}` 显式绑定再 include；给 editor.html 传参
  也要逐个写全（configs.html 与 /configs/editor 两处入口），漏一个字段按钮
  就不渲染。
- 静态资源：`app/static/material-theme/` 是 MD3 颜色 token（6 套主题，
  `<html>` 根类名切换）；`app/static/console.css` 是自写组件层，只消费
  `--md-sys-color-*` 变量，不写死颜色。

## 部署

- `rime-server.service` 需按实际路径修改 `WorkingDirectory`/`ExecStart`。
- git 忽略运行时数据：`store/ sync/ logs/ trash/` 与 `config/server.json`
  （含密码哈希与 secret_key，不入库）。

## 验证改动

```bash
.venv/Scripts/python -m pytest tests -q          # 单测
.venv/Scripts/python run.py &                    # 手动起服务
curl http://localhost:10032/api/health
```

改模板或 CSS 后要重启（生产模式无模板热载）。中文 toast 若再出 latin-1
编码错误，检查是否有新代码往响应头塞了非 ASCII（见上文 api.py 一节）。

## 从 v1 迁移（部署机上执行一次）

```bash
python manage.py import-runtime <旧runtime目录>   # source=migrate 入库
python manage.py import-sync <旧sync目录>          # 设备快照 + devices.json 元数据
```

`makedict/`、`runtime/`、`sync/` 在迁移完成前不要手删。`makedict/` 是 v1
遗留目录，保留原因是 `rime_dict/research/fetch_glossary_wiki.py` 硬编码引用
其中的 Wiki 爬虫；服务器运行时不碰它，也不要把它接进任何服务端流程。
