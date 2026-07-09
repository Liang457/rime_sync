import logging
import os
import subprocess
import glob as glob_mod
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def stop_weasel() -> Optional[str]:
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "(Get-Process WeaselServer -ErrorAction SilentlyContinue).Path"],
            capture_output=True, text=True, timeout=10
        )
        weasel_path = result.stdout.strip()
        subprocess.run(["taskkill", "/f", "/im", "WeaselServer.exe"],
                       capture_output=True, timeout=10)
        logger.info("已停止 WeaselServer.exe（避免完整同步时文件锁定）")
        return weasel_path if weasel_path else None
    except Exception as e:
        logger.warning(f"停止 WeaselServer.exe 失败: {e}")
        return None


def start_weasel(weasel_path: Optional[str] = None):
    try:
        exe = weasel_path
        if not exe or not Path(exe).exists():
            for base in [os.environ.get("ProgramFiles", "C:\\Program Files"),
                         os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")]:
                pattern = os.path.join(base, "Rime", "weasel-*", "WeaselServer.exe")
                matches = sorted(glob_mod.glob(pattern), reverse=True)
                if matches:
                    exe = matches[0]
                    break
        if exe and Path(exe).exists():
            subprocess.Popen([exe], creationflags=0x08000000)
            logger.info("已重启 WeaselServer.exe")
        else:
            logger.warning("未找到 WeaselServer.exe，请手动切换输入法以重启服务")
    except Exception as e:
        logger.warning(f"重启 WeaselServer.exe 失败: {e}，请手动切换输入法")
