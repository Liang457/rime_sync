"""
萌娘百科“蔚蓝档案/译名对照表”抓取模块。

该页面收录了部分学生角色的日文“姓 名”与中文共识译名，
用于为 ba.dict.yaml 补充“姓 + 名”的全名以及单独的姓氏。
"""

import re
import time
import urllib.request
from urllib.parse import quote

URL = "https://mzh.moegirl.org.cn/蔚蓝档案/译名对照表"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) "
        "Gecko/20100101 Firefox/153.0"
    ),
}

RETRY_MAX = 3

_CHINESE_RE = re.compile(r"[一-鿿]")


def fetch_surnames():
    """
    从萌娘百科译名对照表抓取带姓角色。

    返回:
        [(日文姓, 日文名, 中文全名), ...]
    """
    req = urllib.request.Request(quote(URL, safe="/:"), headers=HEADERS)

    last_err = None
    for attempt in range(RETRY_MAX):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8")
            break
        except Exception as e:
            last_err = e
            if attempt < RETRY_MAX - 1:
                time.sleep(2 ** (attempt + 1))
            continue
    else:
        raise RuntimeError(
            f"萌娘百科请求失败（重试 {RETRY_MAX} 次后）: {last_err}"
        ) from last_err

    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', text, re.DOTALL)
    result = []

    for row in rows:
        ja_match = re.search(r'<span lang="ja">([^<]+)</span>', row)
        if not ja_match:
            continue

        src = ja_match.group(1).strip()
        # 只取“姓 名”形式，空格分隔
        if " " not in src:
            continue

        # 定位“日服原文”单元格，取下一格作为“共识译名”
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        ja_idx = None
        for idx, cell in enumerate(cells):
            if '<span lang="ja"' in cell:
                ja_idx = idx
                break
        if ja_idx is None or ja_idx + 1 >= len(cells):
            continue

        consensus_cell = cells[ja_idx + 1]
        # 去除 HTML 标签，保留可见文本
        cn = re.sub(r"<[^>]+>", "", consensus_cell).strip()
        if not cn:
            continue

        # 只保留含中文字符的共识译名（过滤纯外文/占位符）
        if not _CHINESE_RE.search(cn):
            continue

        family, given = src.split(" ", 1)
        result.append((family, given, cn))

    return result


if __name__ == "__main__":
    data = fetch_surnames()
    print(f"共抓取 {len(data)} 条带姓角色")
    for family, given, cn in data[:10]:
        print(f"{family} {given} -> {cn}")
