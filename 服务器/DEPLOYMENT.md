# Rime 服务器部署指南

## 快速启动

1. 确保已安装Python 3.12+和git（tar 解压依赖 `filter='data'`，需 3.12+）
2. 进入项目目录: `cd /home/gk-pi/rime_server`
3. 设置虚拟环境并安装依赖:
   ```
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. 使用启动脚本运行:
   ```
   ./start_server.sh
   ```

## 作为系统服务运行 (systemd)

1. 复制service文件到systemd目录:
   ```bash
   sudo cp rime-server.service.example /etc/systemd/system/rime-server.service
   ```
2. 修改service文件中的用户/组（如果需要）
3. 重新加载systemd配置:
   ```bash
   sudo systemctl daemon-reload
   ```
4. 启用服务（开机自启）:
   ```bash
   sudo systemctl enable rime-server
   ```
5. 启动服务:
   ```bash
   sudo systemctl start rime-server
   ```
6. 查看服务状态:
   ```bash
   sudo systemctl status rime-server
   ```
7. 查看日志:
   ```bash
   sudo journalctl -u rime-server -f
   ```

## 目录结构

- `config/` - 配置文件 (JSON格式)
- `rime_ice_original/` - 从上游克隆的rime-ice仓库
- `runtime/` - 提供给客户端的运行时文件
- `makedict/` - 自定义词库生成脚本
- `sync/` - 用户输入词库同步目录
- `logs/` - 服务器日志
- `backups/` - 备份目录
- `utils/` - Python工具模块

## 配置文件说明

1. `config/server.json` - 服务器基本配置
2. `config/sync.json` - 同步配置
3. `config/dict.json` - 词库管理配置
4. `config/script.json` - 脚本执行配置
5. `config/devices.json` - 设备信息配置

### API 认证（api_token）

`config/server.json` 中的 `server.api_token` 控制 API 访问认证：

- 为空（默认）：不启用认证，所有请求放行（旧行为）
- 非空：所有 `/api/*` 请求必须携带请求头 `X-Api-Token: <token>`，否则返回 401

客户端在 `client_config.json` 的 `server.api_token` 中配置相同值。首次启动后若配置文件中缺少该选项，服务器会自动补充 `"api_token": ""` 并保存。

## API文档

服务器启动后，访问 `http://<树莓派IP>:10032/` 查看API基本信息。

主要API端点:
- `GET /api/health` - 健康检查
- `GET /api/status` - 服务器状态
- `POST /api/rime_ice/update` - 更新rime-ice仓库
- `POST /api/remote_sync` - 远端批量同步（更新rime-ice → 复制到runtime → 批量运行全部词库脚本 → 自动去重插入 `rime_ice.dict.yaml`）。请求体 `{device, version?, force?, add_to_dict?, dict_line?}`；`device` 必填且必须在 `config/script.json` → `scripts.trusted_users` 中，否则在更新前返回 403
- `POST /api/file/edit` - 编辑配置文件
- `POST /api/makedict/run/{script_name}` - 执行词库生成脚本（`version` 可选，缺省时分配服务器时间 `YYYYMMDDHHMMSS`；生成词库与已有文件正文一致（SHA3-256，剔除 YAML 头部）时沿用已有文件，响应的 `output_files_detail[].status` 为 `updated`/`unchanged`）
- `POST /api/config/upload` - 上传配置文件
- `POST /api/sync/upload/tar` - 上传同步 tar 文件
- `GET /api/sync/info` - 获取同步信息
- `GET /api/dict/info` - 获取词库信息
- `GET /api/device/list` - 获取设备列表

## 注意事项

1. 首次启动时，rime-ice仓库会自动克隆（需要网络连接）
2. 确保树莓派防火墙允许端口10032
3. 建议定期备份 `runtime/` 和 `sync/` 目录
4. 脚本执行功能需要信任用户添加的脚本，注意安全

## 故障排除

1. 如果服务器启动失败，检查 `logs/server.log`
2. 确保虚拟环境已正确设置
3. 检查端口10032是否被占用: `sudo lsof -i :10032`
4. 网络问题可能导致rime-ice克隆失败
