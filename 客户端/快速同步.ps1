./venv/Scripts/python.exe rime_client.py sync-userdb --action download

& "C:\Program Files\Rime\weasel-0.17.4\WeaselDeployer.exe" /sync
Start-Sleep -Seconds 10

./venv/Scripts/python.exe rime_client.py sync-userdb --action upload