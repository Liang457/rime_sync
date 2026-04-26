# 先执行小狼毫用户资料同步，将用户输入词库同步到 sync/ 目录下
& "C:\Program Files\Rime\weasel-0.17.4\WeaselDeployer.exe" /sync

# 等待用户资料同步完成（异步操作，需等待写入磁盘）
Start-Sleep -Seconds 10

# 上传下载
./venv/Scripts/python.exe rime_client.py sync-userdb --action upload
./venv/Scripts/python.exe rime_client.py sync-userdb --action download