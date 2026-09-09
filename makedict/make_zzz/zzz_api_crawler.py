"""
绝区零 Wiki API 数据获取模块。
从米游社官方 Wiki API 获取代理人、音擎、邦布、驱动盘、材料等词条名称。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _shared.net import fetch_mihoyo_channel_titles

BASE_URL = (
    "https://act-api-takumi-static.mihoyo.com/common/blackboard/"
    "zzz_wiki/v1/home/content/list"
)
APP_SN = "zzz_wiki"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) "
        "Gecko/20100101 Firefox/153.0"
    ),
    "Accept": "application/json",
    "Referer": "https://wiki.mihoyo.com/zzz/",
}

# 各分类对应的 channel_id
CATEGORY_CHANNELS = {
    "代理人": 43,
    "音擎": 45,
    "邦布": 44,
    "驱动盘": 46,
    "材料": 47,
}


def _fetch_channel(channel_id):
    """
    从指定 channel 获取所有词条标题。

    参数:
        channel_id: 频道 ID

    返回:
        词条标题列表（保持 API 返回顺序，已去重）
    """
    return fetch_mihoyo_channel_titles(BASE_URL, APP_SN, channel_id, HEADERS)


def fetch_agent_names():
    """获取所有代理人名。"""
    return _fetch_channel(43)


def fetch_weapon_names():
    """获取所有音擎名。"""
    return _fetch_channel(45)


def fetch_bangboo_names():
    """获取所有邦布名。"""
    return _fetch_channel(44)


def fetch_drive_disk_names():
    """获取所有驱动盘名。"""
    return _fetch_channel(46)


def fetch_material_names():
    """获取所有材料名。"""
    return _fetch_channel(47)


if __name__ == "__main__":
    for cat, cid in CATEGORY_CHANNELS.items():
        names = _fetch_channel(cid)
        print(f"\n=== {cat} (channel_id={cid})：共 {len(names)} 条 ===")
        for i, name in enumerate(names[:10], 1):
            print(f"  {i}. {name}")
        if len(names) > 10:
            print(f"  ... 共 {len(names)} 条")
