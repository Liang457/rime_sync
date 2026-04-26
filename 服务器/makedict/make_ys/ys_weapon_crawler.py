import urllib.request
import re


def fetch_weapon_names():
    """
    从 bilibili 原神 wiki 武器列表页面爬取所有武器名。
    返回：武器名字符串列表（已去重，保持页面出现顺序）
    """
    url = "https://wiki.biligame.com/ys/%E6%AD%A6%E5%99%A8%E4%B8%80%E8%A7%88"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) "
            "Gecko/20100101 Firefox/150.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://wiki.biligame.com/ys/%E6%AD%A6%E5%99%A8%E4%B8%80%E8%A7%88",
        "Sec-GPC": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Priority": "u=0, i",
    }

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        raw_data = response.read()
        try:
            html = raw_data.decode("utf-8")
        except UnicodeDecodeError:
            html = raw_data.decode("gbk", errors="ignore")

    pattern = re.compile(r'<div\s+class=["\']L["\'][^>]*>(.*?)</div>', re.S)
    matches = pattern.findall(html)

    weapons = []
    seen = set()
    for text in matches:
        name = text.strip()
        if name and name not in seen:
            seen.add(name)
            weapons.append(name)

    return weapons


if __name__ == "__main__":
    for i, name in enumerate(fetch_weapon_names(), 1):
        print(f"{i}. {name}")
