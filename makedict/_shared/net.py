"""
makedict 共享网络库，所有词库生成脚本统一从这里导入。

通过两种方式解析到本模块：
- 服务器调用：script_runner 将 makedict 根目录注入子进程 PYTHONPATH；
- 直接运行：各脚本顶部将 makedict 根目录插入 sys.path。

提供的能力：
- urlopen_with_ipv4_fallback: 双栈请求失败后自动回退纯 IPv4；
- fetch_json: JSON API 抓取（按 URL 缓存 + 指数退避重试 + 顶层类型校验）；
- fetch_text: 文本（HTML）抓取（带重试）；
- fetch_mihoyo_channel_titles: 米游社官方 Wiki blackboard API 封装。
"""

import json
import logging
import socket
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

RETRY_MAX = 3
DEFAULT_TIMEOUT = 30

# ---- IPv4 回退 ----

# 置为 True 后，本进程后续请求跳过双栈尝试，直接走 IPv4
_ipv4_only = False
_patched = False


def _install_ipv4_only():
    """将 socket.getaddrinfo 限制为仅返回 IPv4（AF_INET）结果。"""
    global _patched
    if _patched:
        return

    original_getaddrinfo = socket.getaddrinfo

    def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = getaddrinfo_ipv4
    _patched = True


def urlopen_with_ipv4_fallback(req, timeout):
    """
    先按正常（双栈）方式请求，连接层失败后回退纯 IPv4 重试一次。

    参数:
        req: urllib.request.Request 对象（可复用）
        timeout: 单次尝试的超时秒数，两次尝试各自独立计时

    返回:
        与 urllib.request.urlopen 相同的响应对象（需调用方 with 关闭）

    异常:
        urllib.error.HTTPError: 服务器已应答但返回 4xx/5xx（链路可达，不回退）
        OSError: 正常尝试与 IPv4 回退均失败时，抛出 IPv4 尝试的错误
    """
    global _ipv4_only
    if _ipv4_only:
        return urllib.request.urlopen(req, timeout=timeout)

    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError:
        # 服务器已给出 HTTP 应答，说明链路可达，无需回退
        raise
    except OSError as e:
        # URLError / 超时 / 连接被重置等连接层错误
        _ipv4_only = True
        _install_ipv4_only()
        logger.warning(f"正常连接失败（{e}），回退 IPv4 重试: {req.full_url}")
        return urllib.request.urlopen(req, timeout=timeout)


# ---- 通用抓取 ----

# 按 URL 缓存成功解析的 JSON，进程内同一 API 只请求一次
_json_cache = {}


def _retry_loop(req, timeout, retries, decode):
    """
    带指数退避的重试循环：请求 + 读取 + decode 转换。

    参数:
        req: urllib.request.Request 对象
        timeout: 单次尝试的超时秒数
        retries: 最大尝试次数
        decode: 接收响应字节串、返回转换结果的回调（转换异常不重试，直接抛出）

    返回:
        decode 的返回值
    """
    last_err = None
    for attempt in range(retries):
        try:
            with urlopen_with_ipv4_fallback(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))  # 2s, 4s, 8s
            continue

        return decode(raw)

    raise RuntimeError(f"请求失败（重试 {retries} 次后）: {last_err}") from last_err


def fetch_json(url, *, headers=None, timeout=DEFAULT_TIMEOUT, retries=RETRY_MAX,
               expected_type=None):
    """
    抓取 JSON API：按 URL 进程内缓存，网络错误按指数退避重试。

    参数:
        url: API 地址
        headers: 请求头（可为 None）
        timeout: 单次尝试的超时秒数
        retries: 最大尝试次数
        expected_type: 期望的顶层类型（dict/list），None 表示不校验

    返回:
        解析后的 JSON 数据（同一 URL 的后续调用直接命中缓存）

    异常:
        RuntimeError: 重试耗尽 / 返回非 JSON / 顶层类型不符
    """
    if url in _json_cache:
        return _json_cache[url]

    req = urllib.request.Request(url, headers=headers or {})

    def decode(raw):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"API 返回非 JSON: {e}") from e

    data = _retry_loop(req, timeout, retries, decode)

    if expected_type is not None and not isinstance(data, expected_type):
        raise RuntimeError(
            f"API 返回格式异常，期望 {expected_type.__name__}，"
            f"实际: {type(data).__name__}"
        )

    _json_cache[url] = data
    return data


def fetch_text(url, *, headers=None, timeout=60, retries=RETRY_MAX):
    """
    抓取文本响应（如 HTML 页面），带指数退避重试。

    参数:
        url: 页面地址（含非 ASCII 路径时由调用方先 quote）
        headers: 请求头（可为 None）
        timeout: 单次尝试的超时秒数
        retries: 最大尝试次数

    返回:
        UTF-8 解码后的响应文本

    异常:
        RuntimeError: 重试耗尽
    """
    req = urllib.request.Request(url, headers=headers or {})
    return _retry_loop(req, timeout, retries, lambda raw: raw)


# ---- 米游社官方 Wiki blackboard API ----

def fetch_mihoyo_channel_titles(base_url, app_sn, channel_id, headers, *,
                                timeout=DEFAULT_TIMEOUT, retries=RETRY_MAX):
    """
    从米游社官方 Wiki API 获取指定 channel 的所有词条标题。

    sr/ys/zzz 共用的 blackboard API 形态:
    GET {base_url}?app_sn={app_sn}&channel_id={id}
    返回 retcode=0，词条列表位于 data.data.list[0].list。

    参数:
        base_url: API 根地址（各游戏不同）
        app_sn: 站点标识（如 sr_wiki / ys_obc / zzz_wiki）
        channel_id: 频道 ID
        headers: 请求头
        timeout: 单次尝试的超时秒数
        retries: 最大尝试次数

    返回:
        词条标题列表（保持 API 返回顺序，已去重）
    """
    url = f"{base_url}?app_sn={app_sn}&channel_id={channel_id}"
    data = fetch_json(url, headers=headers, timeout=timeout, retries=retries,
                      expected_type=dict)

    if data.get("retcode") != 0:
        raise RuntimeError(
            f"API 返回错误: {data.get('message')} (retcode={data.get('retcode')})"
        )

    ch_list = data["data"]["list"]
    if not ch_list:
        return []

    items = ch_list[0].get("list", [])

    # 去重（API 可能返回重复条目，如「开拓者•存护」出现两次）
    seen = set()
    titles = []
    for item in items:
        title = item["title"]
        if title and title not in seen:
            seen.add(title)
            titles.append(title)

    return titles
