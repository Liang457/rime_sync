"""
日志归档管理模块
- 启动时将非当天的旧日志压缩归档到 archive/ 子目录
- 压缩回退链: 7z 命令行 → tar.gz → 无压缩 tar
- 自动清理超过保留期的归档文件
"""

import logging
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional


class LogManager:
    """管理日志归档和清理，在 logging 完整配置前也能独立输出。"""

    def __init__(self, log_dir: Path, retention_days: int = 90):
        self.log_dir = Path(log_dir)
        self.archive_dir = self.log_dir / "archive"
        self.retention_days = retention_days

        self.logger = logging.getLogger("log_manager")
        self.logger.propagate = False
        if not self.logger.handlers:
            h = logging.StreamHandler(sys.stderr)
            h.setFormatter(logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            ))
            self.logger.addHandler(h)
        self.logger.setLevel(logging.INFO)

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def archive_old_logs(self) -> Optional[Path]:
        """
        扫描 log_dir 下非当天的日志文件并归档。
        返回归档文件路径；无文件需归档时返回 None。
        """
        if not self.log_dir.exists():
            return None

        today = date.today()
        old_files: List[Path] = []
        for f in self.log_dir.iterdir():
            if not f.is_file():
                continue
            if f.name.startswith("."):
                continue
            mtime_date = datetime.fromtimestamp(f.stat().st_mtime).date()
            if mtime_date != today:
                old_files.append(f)

        if not old_files:
            self.logger.info("没有需要归档的旧日志文件")
            return None

        self.logger.info(f"发现 {len(old_files)} 个非当天的日志文件，开始归档...")
        for f in old_files:
            self.logger.info(f"  {f.name}")

        self.archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        try:
            archive_path = self._create_archive(old_files, timestamp)
        except Exception:
            self.logger.exception("归档失败，保留原始文件")
            return None

        if not archive_path or not archive_path.exists() or archive_path.stat().st_size == 0:
            self.logger.error("归档文件校验失败（不存在或为空），保留原始文件")
            return None

        size_kb = archive_path.stat().st_size / 1024
        self.logger.info(f"归档完成: {archive_path.name} ({size_kb:.1f} KB)")

        # 只有归档成功后才删除原文件
        for f in old_files:
            try:
                f.unlink()
            except OSError:
                self.logger.warning(f"无法删除原日志文件: {f}")

        return archive_path

    def cleanup_old_archives(self) -> int:
        """删除超过保留期的归档文件，返回删除数量。"""
        if not self.archive_dir.exists():
            return 0

        cutoff = datetime.now() - timedelta(days=self.retention_days)
        deleted = 0

        for f in self.archive_dir.iterdir():
            if not f.is_file():
                continue
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                try:
                    f.unlink()
                    self.logger.info(f"已删除过期归档: {f.name}")
                    deleted += 1
                except OSError:
                    self.logger.warning(f"删除过期归档失败: {f}")

        if deleted > 0:
            self.logger.info(f"过期清理完成，删除 {deleted} 个归档文件")
        return deleted

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _create_archive(self, file_list: List[Path], timestamp: str) -> Path:
        """
        三步回退创建归档：
        1. tar + 7z  →  logs_<ts>.tar.7z
        2. tar.gz     →  logs_<ts>.tar.gz
        3. tar        →  logs_<ts>.tar
        """
        # 先用 tarfile 打包
        tar_path = Path(tempfile.gettempdir()) / f"rime_logs_{timestamp}.tar"
        try:
            with tarfile.open(tar_path, "w") as tar:
                for f in file_list:
                    tar.add(str(f), arcname=f.name)
        except Exception:
            if tar_path.exists():
                tar_path.unlink(missing_ok=True)
            raise

        # 尝试压缩
        methods = [
            (".tar.7z", self._compress_7z),
            (".tar.gz", self._compress_gzip),
        ]

        for suffix, method in methods:
            archive_path = self.archive_dir / f"logs_{timestamp}{suffix}"
            try:
                method(tar_path, archive_path)
                tar_path.unlink(missing_ok=True)
                return archive_path
            except Exception:
                if archive_path.exists():
                    archive_path.unlink(missing_ok=True)
                continue

        # 最终回退：无压缩 tar
        final_path = self.archive_dir / f"logs_{timestamp}.tar"
        shutil.move(str(tar_path), str(final_path))
        return final_path

    @staticmethod
    def _compress_7z(tar_path: Path, archive_path: Path) -> None:
        """使用 7z 命令行压缩 tar 文件。"""
        result = subprocess.run(
            ["7z", "a", str(archive_path), str(tar_path)],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            raise RuntimeError(f"7z 压缩失败: {result.stderr.strip()}")

    @staticmethod
    def _compress_gzip(tar_path: Path, archive_path: Path) -> None:
        """使用 Python 内置 gzip 压缩 tar 文件（流式读取避免内存膨胀）。"""
        import gzip
        with open(tar_path, "rb") as src, gzip.open(archive_path, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
