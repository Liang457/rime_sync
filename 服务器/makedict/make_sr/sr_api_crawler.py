"""
星穹铁道 Wiki API 数据获取模块。
从米游社官方 Wiki API 获取角色、光锥、遗器、养成材料、消耗品、贵重物、任务道具等词条名称。
"""

import json
import urllib.request

BASE_URL = (
    "https://act-api-takumi-static.mihoyo.com/common/blackboard/"
    "sr_wiki/v1/home/content/list"
)
APP_SN = "sr_wiki"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) "
        "Gecko/20100101 Firefox/150.0"
    ),
    "Accept": "application/json",
    "Referer": "https://wiki.mihoyo.com/sr/",
}

# 各分类对应的 channel_id
CATEGORY_CHANNELS = {
    "角色": 18,
    "光锥": 19,
    "遗器": 30,
    "养成材料": 20,
    "消耗品": 36,
    "贵重物": 54,
    "任务道具": 53,
}


def _fetch_channel(channel_id):
    """
    从指定 channel 获取所有词条标题。

    参数:
        channel_id: 频道 ID

    返回:
        词条标题列表（保持 API 返回顺序，已去重）
    """
    url = f"{BASE_URL}?app_sn={APP_SN}&channel_id={channel_id}"
    req = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("retcode") != 0:
        raise RuntimeError(f"API 返回错误: {data.get('message')} (retcode={data.get('retcode')})")

    ch_list = data["data"]["list"]
    if not ch_list:
        return []

    ch_data = ch_list[0]
    items = ch_data.get("list", [])

    # 去重（API 可能返回重复条目，如「开拓者•存护」出现两次）
    seen = set()
    titles = []
    for item in items:
        title = item["title"]
        if title and title not in seen:
            seen.add(title)
            titles.append(title)

    return titles


def fetch_role_names():
    """获取所有角色名。"""
    return _fetch_channel(18)


def fetch_weapon_names():
    """获取所有光锥名。"""
    return _fetch_channel(19)


def fetch_relic_names():
    """获取所有遗器名。"""
    return _fetch_channel(30)


def fetch_upgrade_material_names():
    """获取所有养成材料名。"""
    return _fetch_channel(20)


def fetch_consumable_names():
    """获取所有消耗品名。"""
    return _fetch_channel(36)


def fetch_valuable_names():
    """获取所有贵重物名。"""
    return _fetch_channel(54)


def fetch_quest_item_names():
    """获取所有任务道具名。"""
    return _fetch_channel(53)


if __name__ == "__main__":
    for cat, cid in CATEGORY_CHANNELS.items():
        names = _fetch_channel(cid)
        print(f"\n=== {cat} (channel_id={cid})：共 {len(names)} 条 ===")
        for i, name in enumerate(names[:10], 1):
            print(f"  {i}. {name}")
        if len(names) > 10:
            print(f"  ... 共 {len(names)} 条")
