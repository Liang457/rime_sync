$timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

#强制同步
./venv/Scripts/python.exe rime_client.py update-rime-ice --force
# 原神词库
./venv/Scripts/python.exe rime_client.py run-script make_ys $timestamp
./venv/Scripts/python.exe rime_client.py edit-file rime_ice.dict.yaml 18 "  - cn_dicts/ys" --action insert
# 崩铁词库
./venv/Scripts/python.exe rime_client.py run-script make_sr $timestamp
./venv/Scripts/python.exe rime_client.py edit-file rime_ice.dict.yaml 18 "  - cn_dicts/sr" --action insert
# ZZZ词库
./venv/Scripts/python.exe rime_client.py run-script make_zzz $timestamp
./venv/Scripts/python.exe rime_client.py edit-file rime_ice.dict.yaml 18 "  - cn_dicts/zzz" --action insert
# 异环词库
./venv/Scripts/python.exe rime_client.py run-script make_yh $timestamp
./venv/Scripts/python.exe rime_client.py edit-file rime_ice.dict.yaml 18 "  - cn_dicts/yh" --action insert
# BV词库
./venv/Scripts/python.exe rime_client.py run-script make_ba $timestamp
./venv/Scripts/python.exe rime_client.py edit-file rime_ice.dict.yaml 18 "  - cn_dicts/ba" --action insert
