"""
makedict 共享网络库，所有词库生成脚本统一从这里导入。

通过两种方式解析到本模块：
- 服务器调用：script_runner 将 makedict 根目录注入子进程 PYTHONPATH；
- 直接运行：各脚本顶部将 makedict 根目录插入 sys.path。

提供的能力：
- fetch_json: JSON API 抓取（按 URL 缓存 + 重试 + 顶层类型校验）；
- fetch_text: 文本（HTML）抓取（带重试）；
- fetch_mihoyo_channel_titles: 米游社官方 Wiki blackboard API 封装。

传输层：
- 优先使用系统 curl 子进程：Happy Eyeballs 并行双栈连接、
  --connect-timeout / --max-time 硬时限，避开 urllib 串行连接
  在半残 IPv6 环境下每个域名白等一整个超时的问题；
- curl 不可用时回退 urllib（保留原有 IPv4 回退逻辑）；
- 行为开关是文件内变量（ALLOW_IPV6 / FORCE_URLLIB），见下方定义。
"""

import json
import logging
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

RETRY_MAX = 3
DEFAULT_TIMEOUT = 30

# ---- 传输层开关（调整行为时改这里，无需动其他代码） ----

# 是否允许 IPv6：默认 False（仅 IPv4）。
# False 时 curl 加 -4，urllib 把 getaddrinfo 限制为 AF_INET；
# 确认所在网络 IPv6 出网正常后可改为 True 恢复双栈。
ALLOW_IPV6 = False

# 强制走 urllib 传输：默认 False。curl 行为异常时可临时改为 True 排查。
FORCE_URLLIB = False

# curl 连接阶段硬时限（秒）：连不上快速失败，不必等满整个请求超时
CURL_CONNECT_TIMEOUT = 8

# 单请求耗时超过该值（秒）额外记 WARNING，便于在日志里定位慢在哪个域名
SLOW_REQUEST_THRESHOLD = 3

# curl 退出码的常用含义，仅用于错误提示
_CURL_EXIT_HINTS = {
    6: "域名解析失败",
    7: "无法连接服务器",
    28: "请求超时",
    35: "TLS 握手失败",
    47: "重定向次数过多",
    60: "TLS 证书校验失败",
}


class HTTPStatusError(Exception):
    """
    服务器已应答但返回 4xx/5xx。

    retryable 判断是否值得重试：仅 408/429 与 5xx 重试，
    其余 4xx（403 风控、404 等）重试无意义还可能加重对方限制。
    """

    def __init__(self, status, body, url):
        self.status = status
        self.url = url
        snippet = body[:200].strip() if body else ""
        super().__init__(f"HTTP {status} ({url}): {snippet}")

    @property
    def retryable(self):
        return self.status >= 500 or self.status in (408, 429)


# ---- curl 传输（主路径） ----

_CURL_PATH = None if FORCE_URLLIB else shutil.which("curl")
if _CURL_PATH is None:
    logger.warning("系统 curl 不可用（或 FORCE_URLLIB=True），回退 urllib 传输")


def _curl_fetch(url, *, headers, timeout):
    """
    用系统 curl 抓取一个 URL，返回响应字节串。

    curl 参数设计：
    - -4 / 双栈          由 ALLOW_IPV6 决定；
    - -L --max-redirs 5  与 urllib 默认行为一致地跟随重定向；
    - --connect-timeout  连接阶段硬时限；
    - --max-time         单次尝试总时限（连接+TLS+读取全部计入）；
    - --compressed       自动处理 gzip 压缩；
    - 不用 -f            保留错误响应体，状态码经 -w 追加到 stdout 末尾。

    异常:
        HTTPStatusError: 服务器返回 4xx/5xx
        OSError: 连接层失败 / 超时 / curl 进程异常
    """
    cmd = [
        _CURL_PATH,
        "-sS",
        "-L",
        "--max-redirs", "5",
        "--compressed",
        "--connect-timeout", str(CURL_CONNECT_TIMEOUT),
        "--max-time", str(timeout),
        "-w", "\n%{http_code}",
    ]
    if not ALLOW_IPV6:
        cmd.append("-4")

    for name, value in (headers or {}).items():
        cmd += ["-H", f"{name}: {value}"]
    # "--" 结束选项解析，URL 不会被误认为 curl 选项
    cmd.append("--")
    cmd.append(url)

    start = time.monotonic()
    try:
        # 比 --max-time 多留 5 秒，覆盖 curl 自身收尾开销
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
    except subprocess.TimeoutExpired as e:
        raise OSError(f"curl 进程超时（>{timeout + 5}s）: {url}") from e

    elapsed = time.monotonic() - start

    if proc.returncode != 0:
        hint = _CURL_EXIT_HINTS.get(proc.returncode)
        hint_text = f"（{hint}）" if hint else ""
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        logger.warning(
            "请求失败: %s, %.2fs, curl 退出码 %s%s",
            url, elapsed, proc.returncode, hint_text,
        )
        raise OSError(
            f"curl 退出码 {proc.returncode}{hint_text}: {stderr[:200]} ({url})"
        )

    # -w 追加的最后一行是 HTTP 状态码
    body, sep, code = proc.stdout.rpartition(b"\n")
    if not sep:
        raise OSError(f"curl 输出中没有状态码: {url}")

    status = int(code.strip() or 0)
    logger.info(
        "GET %s -> %s, %.2fs, %d bytes (curl)", url, status, elapsed, len(body)
    )
    if elapsed > SLOW_REQUEST_THRESHOLD:
        logger.warning("请求偏慢: %s 耗时 %.2fs (curl)", url, elapsed)

    if status == 0:
        raise OSError(f"curl 未收到 HTTP 状态码: {url}")
    if status >= 400:
        raise HTTPStatusError(status, body.decode("utf-8", errors="replace"), url)

    return body


# ---- urllib 传输（回退路径） ----

# ALLOW_IPV6=False 时初始即为 True，urllib 路径直接单栈 IPv4
_ipv4_only = not ALLOW_IPV6
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


def _urlopen_with_ipv4_fallback(req, timeout):
    """
    urllib 双栈请求，连接层失败后回退纯 IPv4 重试一次。

    仅在 ALLOW_IPV6=True 时会真正先走双栈；ALLOW_IPV6=False 时
    getaddrinfo 已在模块加载时被限制为 IPv4，本函数等同直接 urlopen。
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


def _urllib_fetch(url, *, headers, timeout):
    """
    用 urllib 抓取一个 URL，返回响应字节串（curl 不可用时的回退路径）。

    异常:
        HTTPStatusError: 服务器返回 4xx/5xx
        OSError: 连接层失败 / 超时
    """
    req = urllib.request.Request(url, headers=headers or {})
    start = time.monotonic()
    try:
        with _urlopen_with_ipv4_fallback(req, timeout=timeout) as resp:
            status = resp.getcode()
            body = resp.read()
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read()
        except Exception:
            err_body = b""
        elapsed = time.monotonic() - start
        logger.info(
            "GET %s -> %s, %.2fs, %d bytes (urllib)",
            url, e.code, elapsed, len(err_body),
        )
        raise HTTPStatusError(
            e.code, err_body.decode("utf-8", errors="replace"), url
        ) from e
    except OSError as e:
        # URLError / 超时 / 连接被重置等连接层错误（HTTPError 已在上方拦截）
        elapsed = time.monotonic() - start
        logger.warning("请求失败: %s, %.2fs, %s (urllib)", url, elapsed, e)
        raise

    elapsed = time.monotonic() - start
    logger.info(
        "GET %s -> %s, %.2fs, %d bytes (urllib)", url, status, elapsed, len(body)
    )
    if elapsed > SLOW_REQUEST_THRESHOLD:
        logger.warning("请求偏慢: %s 耗时 %.2fs (urllib)", url, elapsed)

    if status >= 400:
        raise HTTPStatusError(status, body.decode("utf-8", errors="replace"), url)

    return body


def _transport_fetch(url, *, headers, timeout):
    """选择可用传输抓取 URL，返回响应字节串。"""
    if _CURL_PATH is not None:
        return _curl_fetch(url, headers=headers, timeout=timeout)
    return _urllib_fetch(url, headers=headers, timeout=timeout)


if not ALLOW_IPV6:
    _install_ipv4_only()


# ---- 通用抓取 ----

# 按 URL 缓存成功解析的 JSON，进程内同一 API 只请求一次
_json_cache = {}


def _retry_loop(fetch, retries, decode):
    """
    带指数退避的重试循环：fetch 执行一次请求，decode 转换响应文本。

    参数:
        fetch: 无参回调，执行一次请求并返回响应字节串
        retries: 最大尝试次数
        decode: 接收响应文本、返回转换结果的回调（转换异常不重试，直接抛出）

    重试策略:
        - 4xx（除 408/429）：重试无意义，首次即抛 HTTPStatusError；
        - 5xx / 408 / 429 / 连接层错误：退避后重试（2s, 4s）。

    返回:
        decode 的返回值
    """
    last_err = None
    for attempt in range(retries):
        try:
            body = fetch().decode("utf-8")
        except HTTPStatusError as e:
            if not e.retryable:
                raise
            last_err = e
        except Exception as e:
            last_err = e
        else:
            return decode(body)

        if attempt < retries - 1:
            time.sleep(2 ** (attempt + 1))  # 2s, 4s

    raise RuntimeError(f"请求失败（重试 {retries} 次后）: {last_err}") from last_err


def fetch_json(url, *, headers=None, timeout=DEFAULT_TIMEOUT, retries=RETRY_MAX,
               expected_type=None):
    """
    抓取 JSON API：按 URL 进程内缓存，网络错误按指数退避重试。

    参数:
        url: API 地址
        headers: 请求头（可为 None）
        timeout: 单次尝试的总时限秒数
        retries: 最大尝试次数
        expected_type: 期望的顶层类型（dict/list），None 表示不校验

    返回:
        解析后的 JSON 数据（同一 URL 的后续调用直接命中缓存）

    异常:
        HTTPStatusError: 4xx（除 408/429），不重试直接抛出
        RuntimeError: 重试耗尽 / 返回非 JSON / 顶层类型不符
    """
    if url in _json_cache:
        return _json_cache[url]

    def fetch():
        return _transport_fetch(url, headers=headers, timeout=timeout)

    def decode(raw):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"API 返回非 JSON: {e}") from e

    data = _retry_loop(fetch, retries, decode)

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
        timeout: 单次尝试的总时限秒数
        retries: 最大尝试次数

    返回:
        UTF-8 解码后的响应文本

    异常:
        HTTPStatusError: 4xx（除 408/429），不重试直接抛出
        RuntimeError: 重试耗尽
    """
    def fetch():
        return _transport_fetch(url, headers=headers, timeout=timeout)

    return _retry_loop(fetch, retries, lambda raw: raw)


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
        timeout: 单次尝试的总时限秒数
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
