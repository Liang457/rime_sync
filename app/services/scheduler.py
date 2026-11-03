"""基座自动更新调度器：cron 表达式驱动的后台 daemon 线程。

只做一件事：到点触发既有的 BaseManager.update_and_rebuild（git 拉取 + 文件
落库），不引入任何脚本执行。默认关闭，在「上游基座」页开启。

设计要点：
- 线程每 TICK_SECONDS 醒一次调 check_once()，纯逻辑与线程分离，测试直接调
  check_once(注入时间) 验证到期/重排行为；
- (enabled, cron) 变化即重排下次执行时间；不追欠账——关了很久再打开，从
  「现在」起算下一次，而不是把错过的轮次补跑一遍；
- 执行结果写 store activity；失败不抛出（断网不能杀死线程），记录在
  last 里供页面展示。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

TICK_SECONDS = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class BaseUpdateScheduler:
    def __init__(self, settings, upstream, store):
        self.settings = settings
        self.upstream = upstream
        self.store = store
        self._lock = threading.Lock()
        self._sig: tuple | None = None      # (enabled, cron)，变化即重排
        self._next_run: float | None = None
        self._last: dict | None = None      # {"time", "ok", "detail"}
        self._thread: threading.Thread | None = None

    # ---- 状态（页面展示） ---------------------------------------------------

    def status(self) -> dict:
        with self._lock:
            cron_ok = self._cron_ok(self.settings.base_cron) \
                if self.settings.base_auto_update else None
            return {
                "enabled": self.settings.base_auto_update,
                "cron": self.settings.base_cron,
                "cron_ok": cron_ok,
                "next_run": self._next_run,
                "last": dict(self._last) if self._last else None,
            }

    # ---- 调度核心 ------------------------------------------------------------

    @staticmethod
    def _cron_ok(expr: str) -> bool:
        try:
            from croniter import croniter

            croniter(expr)
            return True
        except Exception:
            return False

    def _compute_next(self, now: float) -> float | None:
        if not self.settings.base_auto_update \
                or not self._cron_ok(self.settings.base_cron):
            return None
        from croniter import croniter

        return croniter(self.settings.base_cron, now).get_next(float)

    def check_once(self, now: float) -> dict | None:
        """推进一次时钟：到期则执行基座更新。返回执行结果，未到期返回 None。"""
        with self._lock:
            sig = (self.settings.base_auto_update, self.settings.base_cron)
            if sig != self._sig:  # 开关或表达式变了 → 按当前配置重排
                self._sig = sig
                self._next_run = self._compute_next(now)
            if self._next_run is None or now < self._next_run:
                return None
        result = self._run_once()
        with self._lock:
            self._last = {"time": _now_iso(), **result}
            self._next_run = self._compute_next(now)
        return result

    def _run_once(self) -> dict:
        try:
            report = self.upstream.update_and_rebuild(force=False)
            rb = report["rebuild"]
            commit = report["git"]["commit"].split(" ", 1)[0][:12]
            detail = (f"自动更新基座 {commit}：新增 {rb['added']}，"
                      f"更新 {rb['updated']}，移除 {rb['removed']}")
            result = {"ok": True, "detail": detail}
        except Exception as e:  # GitError 或意外错误——断网不能杀死线程
            result = {"ok": False, "detail": f"自动更新失败：{e}"}
        self.store.activity("base-auto", result["detail"])
        return result

    # ---- 线程 -----------------------------------------------------------------

    def reconfigure(self) -> None:
        """设置被页面改动后调用：立即按当前配置重排，页面马上能看到下次执行时间。"""
        import time

        with self._lock:
            self._sig = None
            self._next_run = self._compute_next(time.time())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, name="base-auto-update", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        import time

        while True:
            time.sleep(TICK_SECONDS)
            try:
                self.check_once(time.time())
            except Exception:  # 任何意外都不能让调度线程死掉
                continue
