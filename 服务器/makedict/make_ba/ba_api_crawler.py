"""
蔚蓝档案 GameKee Wiki API 数据获取模块。
从 GameKee Wiki API 获取学生、NPC、礼物等词条名称。

API 返回层级树结构（JSON 对象包裹），叶子节点 (child=null) 为实际词条。
叶子节点含 name_alias 字段（逗号分隔别名），仅保留中文别名。
"""

import json
import re
import time
import urllib.request

# GameKee Wiki API - 蔚蓝档案 (pid=23941)
BASE_URL = "https://www.gamekee.com/v1/entry/treesByPidV1?pid=23941"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) "
        "Gecko/20100101 Firefox/153.0"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.gamekee.com/ba/second/23941",
    "X-Requested-With": "XMLHttpRequest",
    "Lang": "zh-cn",
    "game-alias": "ba",
}

# 收录的板块 ID（仅收录游戏实体名称，跳过材料子分类标签）
SECTION_IDS = {
    "实装学生": 49443,
    "NPC及卫星": 107619,
    "礼物": 107816,
}

# 缓存：首次 fetch 后缓存完整 JSON，避免重复请求
_CACHED_DATA = None

RETRY_MAX = 3


def _fetch_json():
    """获取完整 API 响应（带缓存与重试）。"""
    global _CACHED_DATA
    if _CACHED_DATA is not None:
        return _CACHED_DATA

    req = urllib.request.Request(BASE_URL, headers=HEADERS)

    last_err = None
    for attempt in range(RETRY_MAX):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
        except Exception as e:
            last_err = e
            if attempt < RETRY_MAX - 1:
                time.sleep(2 ** (attempt + 1))  # 2s, 4s, 8s
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"API 返回非 JSON: {e}") from e

        if not isinstance(data, dict):
            raise RuntimeError(
                f"API 返回格式异常，期望 dict，实际: {type(data)}"
            )

        if data.get("code") != 0:
            raise RuntimeError(
                f"API 返回错误: code={data.get('code')}, msg={data.get('msg')}"
            )

        tree_data = data.get("data")
        if tree_data is None:
            raise RuntimeError("API 返回 data 为 null")

        _CACHED_DATA = tree_data
        return tree_data

    raise RuntimeError(
        f"API 请求失败（重试 {RETRY_MAX} 次后）: {last_err}"
    ) from last_err


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


def _extract_chinese_aliases(nodes):
    """
    递归遍历节点树，提取所有叶子节点的中文别名。
    从 name_alias 字段按逗号拆分，仅保留含中文字符的别名。

    参数:
        nodes: 节点列表

    返回:
        中文别名列表（去重，如 ["妃姬", "妃妃", "水", "阳奈", "魔王"]）
    """
    if not nodes:
        return []

    seen = set()
    aliases = []

    def _walk(node_list):
        for node in node_list:
            children = node.get("child")
            if children:
                _walk(children)
            else:
                name_alias = node.get("name_alias", "")
                if name_alias:
                    for alias in name_alias.split(","):
                        alias = alias.strip()
                        if not alias:
                            continue
                        # 仅保留含中文字符的别名（过滤纯假名/纯英文/纯数字）
                        if re.search(r"[一-鿿]", alias) and alias not in seen:
                            seen.add(alias)
                            aliases.append(alias)

    _walk(nodes)
    return aliases


def _fetch_section(section_id):
    """
    从 GameKee Wiki API 获取指定板块的所有词条名称 + 中文别名。

    参数:
        section_id: 板块 ID（顶层节点的 id）

    返回:
        (names, aliases) 元组
    """
    data = _fetch_json()

    for section in data.get("child", []):
        if section.get("id") == section_id:
            children = section.get("child")
            if not children:
                return [], []
            names = _extract_leaf_names(children)
            aliases = _extract_chinese_aliases(children)
            return names, aliases

    raise RuntimeError(f"未找到板块 id={section_id}")


def fetch_student_names():
    """获取所有实装学生名 + 中文别名。"""
    return _fetch_section(49443)


def fetch_npc_names():
    """获取所有 NPC 及卫星名 + 中文别名。"""
    return _fetch_section(107619)


def fetch_gift_names():
    """获取所有礼物名 + 中文别名。"""
    return _fetch_section(107816)


if __name__ == "__main__":
    for cat, sid in SECTION_IDS.items():
        names, aliases = _fetch_section(sid)
        print(
            f"\n=== {cat} (section_id={sid})："
            f"词条 {len(names)} 条，别名 {len(aliases)} 条 ==="
        )
        print("  词条:")
        for i, name in enumerate(names[:10], 1):
            print(f"    {i}. {name}")
        if len(names) > 10:
            print(f"    ... 共 {len(names)} 条")
        if aliases:
            print("  别名:")
            for i, alias in enumerate(aliases[:10], 1):
                print(f"    {i}. {alias}")
            if len(aliases) > 10:
                print(f"    ... 共 {len(aliases)} 条")
