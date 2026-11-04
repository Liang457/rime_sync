"""基座自动更新调度器：到期触发、cron 变更重排、失败兜底。"""
from datetime import datetime, timedelta

from app.services.scheduler import BaseUpdateScheduler


class FakeSettings:
    def __init__(self, enabled=False, cron="* * * * *"):
        self.enabled = enabled
        self.cron = cron

    @property
    def base_auto_update(self) -> bool:
        return self.enabled

    @property
    def base_cron(self) -> str:
        return self.cron


class FakeUpstream:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def update_and_rebuild(self, force=False):
        self.calls += 1
        if self.fail:
            raise RuntimeError("断网")
        return {"git": {"commit": "abc123 fix: x"},
                "rebuild": {"added": 1, "updated": 0, "removed": 0}}


class FakeStore:
    def __init__(self):
        self.activities = []

    def activity(self, kind, detail):
        self.activities.append((kind, detail))


def test_disabled_never_fires():
    s = BaseUpdateScheduler(FakeSettings(False), FakeUpstream(), FakeStore())
    assert s.check_once(3600.0) is None
    assert s.status()["enabled"] is False


def test_fires_when_due_then_reschedules():
    up = FakeUpstream()
    s = BaseUpdateScheduler(FakeSettings(True, "* * * * *"), up, FakeStore())
    assert s.check_once(3600.0) is None          # 排期：下一次整分 3660
    assert s.check_once(3659.0) is None
    r = s.check_once(3660.0)                     # 到点触发
    assert r and r["ok"] and up.calls == 1
    assert "自动更新基座" in r["detail"]
    assert s.check_once(3680.0) is None          # 已重排到 3720
    assert s.check_once(3720.0) is not None
    assert up.calls == 2


def test_setting_change_reschedules():
    st = FakeSettings(False, "* * * * *")
    up = FakeUpstream()
    s = BaseUpdateScheduler(st, up, FakeStore())
    assert s.check_once(0.0) is None
    st.enabled = True                            # 中途打开：从当前时刻起算
    assert s.check_once(1.0) is None             # 重排为 60，不补欠账
    assert s.check_once(59.0) is None
    assert s.check_once(60.0) is not None
    assert up.calls == 1


def test_failure_recorded_not_raised():
    up = FakeUpstream(fail=True)
    st = FakeStore()
    s = BaseUpdateScheduler(FakeSettings(True, "* * * * *"), up, st)
    assert s.check_once(0.0) is None             # 首次调用只排期（下一分钟）
    r = s.check_once(60.0)                       # 到点触发
    assert r and r["ok"] is False and "断网" in r["detail"]
    assert st.activities and st.activities[0][0] == "base-auto"
    assert s.status()["last"]["ok"] is False


def test_invalid_cron_never_fires():
    s = BaseUpdateScheduler(FakeSettings(True, "bad cron!"),
                            FakeUpstream(), FakeStore())
    assert s.status()["cron_ok"] is False
    assert s.check_once(3660.0) is None
    assert s.check_once(99999.0) is None


def test_cron_matches_local_walltime():
    """回归：裸 float 时间戳曾被 croniter 按 UTC 解析小时字段，导致
    「0 2 */2 * *」在服务器本地上午 10 点触发。注入 epoch 的真实形态下，
    下次执行必须精确落在本地墙钟 02:00。"""
    base = datetime.now().astimezone().replace(
        hour=1, minute=0, second=0, microsecond=0)          # 本地某日 01:00
    expected = (base + timedelta(hours=1)).timestamp()      # 同日本地 02:00
    s = BaseUpdateScheduler(FakeSettings(True, "0 2 * * *"),
                            FakeUpstream(), FakeStore())
    assert s.check_once(base.timestamp()) is None           # 只排期不触发
    assert s.status()["next_run"] == expected
