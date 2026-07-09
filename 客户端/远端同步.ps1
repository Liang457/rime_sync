$timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
# 强制更新 rime-ice
./venv/Scripts/python.exe cli.py update-rime-ice --force
# 执行全部词库脚本并自动添加到 rime_ice.dict.yaml
./venv/Scripts/python.exe cli.py run-all-scripts $timestamp
