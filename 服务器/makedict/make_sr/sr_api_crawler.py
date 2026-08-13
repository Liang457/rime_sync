"""
星穹铁道 Wiki API 数据获取模块。
从米游社官方 Wiki API 获取角色、光锥、遗器、养成材料、消耗品、贵重物、任务道具等词条名称，
并从米游社星铁交互地图公开 JSON API 获取地图地名（区域名 + 地标名）。
"""

import json
import logging
import re
import urllib.request

BASE_URL = (
    "https://act-api-takumi-static.mihoyo.com/common/blackboard/"
    "sr_wiki/v1/home/content/list"
)
APP_SN = "sr_wiki"

# ---- 交互地图地名 API（星铁大地图，无需登录/签名）----
MAP_BASE_URL = "https://api-static.mihoyo.com/common/srmap/sr_map"
MAP_APP_SN = "sr_map"
MAP_LANG = "zh-cn"
# map_id 只需任意一个：tree 接口返回全量层级树，label 树每张图都一样
MAP_ID = "38"
# app_version 是交互地图页面 JS 里硬编码的版本哈希，缺失或过期时 API 返回 -502。
# 失效时打开星铁交互地图页面，在页面引用的 bundle_*.js 中搜索 app_version 重新提取。
MAP_APP_VERSION = "de16a09fca4e0ab89acf69fe0c12514f"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) "
        "Gecko/20100101 Firefox/153.0"
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


def _map_request(endpoint):
    """
    请求星铁交互地图 API（固定携带 map_id / app_sn / lang / app_version 参数）。

    参数:
        endpoint: API 路径，如 /v1/map/tree

    返回:
        retcode 为 0 时的 data 字段

    异常:
        RuntimeError: API 返回非 0 retcode（-502 表示 app_version 失效，附带恢复指引）
    """
    url = (
        f"{MAP_BASE_URL}{endpoint}?map_id={MAP_ID}&app_sn={MAP_APP_SN}"
        f"&lang={MAP_LANG}&app_version={MAP_APP_VERSION}"
    )
    req = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(req, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("retcode") != 0:
        if data.get("retcode") == -502:
            raise RuntimeError(
                "地图 API 返回 -502：app_version 版本哈希可能已失效，"
                "请打开星铁交互地图页面，在页面引用的 bundle_*.js 中搜索 "
                "'app_version' 重新提取，更新 sr_api_crawler.py 的 MAP_APP_VERSION"
            )
        raise RuntimeError(
            f"地图 API 返回错误: {data.get('message')} (retcode={data.get('retcode')})"
        )
    return data.get("data")


def _is_slice_name(name):
    """
    判断地图节点名是否为运营切片名（楼层/编号/立体图/房间等），不应收入词库。

    过滤规则:
        - 纯楼层名: 1层 / -1层 / 3层
        - 纯编号: 1 / 2 / 3（匹诺康尼梦境类切片）
        - 含「立体地图」「房间」「（黎明）」「（永夜）」
        - 以 -数字层 结尾（如「葬忆彼岸」时光归墟-5层）
    """
    if not name:
        return True
    if re.match(r"^-?\d+层$", name):
        return True
    if re.match(r"^\d+$", name):
        return True
    if "立体地图" in name or "房间" in name:
        return True
    if "（黎明）" in name or "（永夜）" in name:
        return True
    if re.search(r"-\d+层$", name):
        return True
    return False


def _extract_region_names(nodes):
    """
    递归提取地图层级树中的区域名。

    参数:
        nodes: /v1/map/tree 返回的节点列表（含嵌套 children）

    返回:
        区域名列表（跳过 is_hide 节点与运营切片名）
    """
    names = []
    for node in nodes or []:
        if node.get("is_hide"):
            continue
        name = node.get("name") or ""
        if not _is_slice_name(name):
            names.append(name)
        children = node.get("children") or []
        if children:
            names.extend(_extract_region_names(children))
    return names


def fetch_place_names():
    """
    从星铁交互地图 API 获取全部地图地名（区域名 + 地标名）。

    返回:
        地名列表（保持出现顺序，已去重）
    """
    # 1. 地图层级树 → 区域/子区域名
    tree_data = _map_request("/v1/map/tree")
    names = _extract_region_names(tree_data.get("tree") or [])

    # 2. 标签树 → 地标名（按名称选取「地标」类，避免硬编码 id）
    label_data = _map_request("/v1/map/label/tree")
    landmark_category = None
    for cat in label_data.get("tree") or []:
        if cat.get("name") == "地标":
            landmark_category = cat
            break
    if landmark_category is None:
        logging.warning("地图标签树中未找到「地标」类，仅使用区域名")
    else:
        for label in landmark_category.get("children") or []:
            name = label.get("name")
            if name:
                names.append(name)

    # 去重
    seen = set()
    result = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


if __name__ == "__main__":
    for cat, cid in CATEGORY_CHANNELS.items():
        names = _fetch_channel(cid)
        print(f"\n=== {cat} (channel_id={cid})：共 {len(names)} 条 ===")
        for i, name in enumerate(names[:10], 1):
            print(f"  {i}. {name}")
        if len(names) > 10:
            print(f"  ... 共 {len(names)} 条")

    place_names = fetch_place_names()
    print(f"\n=== 地图地名（区域 + 地标）：共 {len(place_names)} 条 ===")
    for i, name in enumerate(place_names[:20], 1):
        print(f"  {i}. {name}")
    if len(place_names) > 20:
        print(f"  ... 共 {len(place_names)} 条")
