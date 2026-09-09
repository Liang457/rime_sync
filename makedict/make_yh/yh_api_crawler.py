"""
异环 GameKee Wiki API 数据获取模块。
从 GameKee Wiki API 获取角色、弧盘、空幕、异象、道具、异能等词条名称。

API 返回层级树结构（JSON 数组），叶子节点 (child=null) 为实际词条。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _shared.net import fetch_json

# GameKee Wiki API - 异环项目 (project_id=50442)
BASE_URL = (
    "https://cdnimg-test.gamekee.com/wiki2.0/pro/50442/"
    "entry/list.json"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) "
        "Gecko/20100101 Firefox/153.0"
    ),
    "Accept": "application/json",
    "Referer": "https://www.gamekee.com/",
}

# 收录的板块 ID（仅收录游戏实体名称，跳过攻略/OST/教程等）
SECTION_IDS = {
    "角色": 170431,
    "弧盘": 170422,
    "空幕": 170436,
    "异象": 171852,
    "道具": 171544,
    "异能": 188180,
}


def _fetch_json():
    """获取完整 API 响应（缓存/重试/类型校验见 _shared.net.fetch_json）。"""
    return fetch_json(BASE_URL, headers=HEADERS, expected_type=list)


def _extract_leaf_names(nodes):
    """
    递归遍历节点树，提取所有叶子节点 (child=null) 的 name。

    参数:
        nodes: 节点列表，每项为 dict 含 id / name / child 字段

    返回:
        叶子节点名称列表（保持遍历顺序，已去重）
    """
    if not nodes:
        return []

    seen = set()
    names = []

    def _walk(node_list):
        for node in node_list:
            children = node.get("child")
            if children:
                _walk(children)
            else:
                name = node.get("name", "").strip()
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)

    _walk(nodes)
    return names


def _fetch_section(section_id):
    """
    从 GameKee Wiki API 获取指定板块的所有叶子词条名称。

    参数:
        section_id: 板块 ID（顶层节点的 id）

    返回:
        词条名称列表
    """
    data = _fetch_json()

    for section in data:
        if section.get("id") == section_id:
            children = section.get("child")
            if not children:
                return []
            return _extract_leaf_names(children)

    raise RuntimeError(f"未找到板块 id={section_id}")


def fetch_character_names():
    """获取所有角色名。"""
    return _fetch_section(170431)


def fetch_arc_disk_names():
    """获取所有弧盘名。"""
    return _fetch_section(170422)


def fetch_sky_curtain_names():
    """获取所有空幕名（卡带 + 驱动块）。"""
    return _fetch_section(170436)


def fetch_anomaly_names():
    """获取所有异象名。"""
    return _fetch_section(171852)


def fetch_item_names():
    """获取所有道具名。"""
    return _fetch_section(171544)


def fetch_ability_names():
    """获取所有异能名（异能类型 + 异能环合）。"""
    return _fetch_section(188180)


if __name__ == "__main__":
    for cat, sid in SECTION_IDS.items():
        names = _fetch_section(sid)
        print(f"\n=== {cat} (section_id={sid})：共 {len(names)} 条 ===")
        for i, name in enumerate(names[:10], 1):
            print(f"  {i}. {name}")
        if len(names) > 10:
            print(f"  ... 共 {len(names)} 条")
