import logging
import os
import tempfile
import tarfile
from datetime import date, datetime, timedelta
from pathlib import Path
from logging.handlers import RotatingFileHandler

from core.config import ConfigManager

logger = logging.getLogger(__name__)


def setup_logging(config: ConfigManager):
    log_config = config.log_config
    level = getattr(logging, log_config.get("level", "INFO").upper())
    log_file_str = log_config.get("file", "logs/rime_client.log")
    max_bytes = log_config.get("max_size_mb", 10) * 1024 * 1024
    backup_count = 5

    log_file = (config.config_path.parent / log_file_str).resolve()
    log_dir = log_file.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    if log_config.get("archive_enabled", True):
        _archive_old_logs(log_dir, log_config.get("archive_retention_days", 90))

    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)

    root.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    fh = RotatingFileHandler(
        str(log_file), maxBytes=max_bytes,
        backupCount=backup_count, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)


def _archive_old_logs(log_dir: Path, retention_days: int):
    today = date.today()
    old_files = [
        f for f in log_dir.iterdir()
        if f.is_file()
        and not f.name.startswith(".")
        and datetime.fromtimestamp(f.stat().st_mtime).date() != today
    ]
    if not old_files:
        return

    archive_dir = log_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    archive_path = _try_compress(old_files, archive_dir, ts)

    if archive_path and archive_path.stat().st_size > 0:
        logger.info(
            f"日志归档完成: {archive_path.name} ({archive_path.stat().st_size / 1024:.1f} KB)"
        )
        for f in old_files:
            try:
                f.unlink()
            except OSError:
                pass

    _cleanup_old_archives(archive_dir, retention_days)


def _try_compress(file_list: list, archive_dir: Path, timestamp: str) -> Path | None:
    import shutil
    import subprocess

    temp_dir = Path(tempfile.gettempdir())
    tar_path = temp_dir / f"rime_client_logs_{timestamp}.tar"

    try:
        with tarfile.open(tar_path, "w") as tar:
            for f in file_list:
                tar.add(str(f), arcname=f.name)
    except Exception:
        if tar_path.exists():
            tar_path.unlink(missing_ok=True)
        return None

    archive_path = archive_dir / f"logs_{timestamp}.tar.7z"
    try:
        result = subprocess.run(
            ["7z", "a", str(archive_path), str(tar_path)],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            tar_path.unlink(missing_ok=True)
            return archive_path
    except Exception:
        pass
    if archive_path.exists():
        archive_path.unlink(missing_ok=True)

    archive_path = archive_dir / f"logs_{timestamp}.tar.gz"
    try:
        import gzip
        with open(tar_path, "rb") as src, gzip.open(archive_path, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        tar_path.unlink(missing_ok=True)
        return archive_path
    except Exception:
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)

    final_path = archive_dir / f"logs_{timestamp}.tar"
    shutil.move(str(tar_path), str(final_path))
    return final_path


def _cleanup_old_archives(archive_dir: Path, retention_days: int):
    if not archive_dir.exists():
        return
    cutoff = datetime.now() - timedelta(days=retention_days)
    for f in archive_dir.iterdir():
        if not f.is_file():
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            try:
                f.unlink()
                logger.info(f"已删除过期归档: {f.name}")
            except OSError:
                pass
