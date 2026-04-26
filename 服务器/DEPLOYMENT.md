# Rime 服务器部署指南

## 快速启动

1. 确保已安装Python 3.7+和git
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

## API文档

服务器启动后，访问 `http://<树莓派IP>:10032/` 查看API基本信息。

主要API端点:
- `GET /api/health` - 健康检查
- `GET /api/status` - 服务器状态
- `POST /api/rime_ice/update` - 更新rime-ice仓库
- `POST /api/file/edit` - 编辑配置文件
- `POST /api/makedict/run/{script_name}` - 执行词库生成脚本
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
