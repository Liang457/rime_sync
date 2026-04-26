import html
import urllib.request
import re


def fetch_weapon_names():
    """
    从 bilibili 绝区零 wiki 音擎图鉴页面爬取所有音擎名。
    返回：音擎名字符串列表（已去重，保持页面出现顺序）
    """
    url = "https://wiki.biligame.com/zzz/%E9%9F%B3%E6%93%8E%E5%9B%BE%E9%89%B4"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) "
            "Gecko/20100101 Firefox/150.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://wiki.biligame.com/zzz/%E9%9F%B3%E6%93%8E%E5%9B%BE%E9%89%B4",
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
            html_text = raw_data.decode("utf-8")
        except UnicodeDecodeError:
            html_text = raw_data.decode("gbk", errors="ignore")

    # 提取 <div class="role-name"><a>...</a></div> 中 <a> 的文本
    # 与角色图鉴结构一致
    pattern = re.compile(
        r'<div\s+class=["\']role-name["\'][^>]*>\s*<a[^>]*>(.*?)</a>\s*</div>',
        re.S,
    )
    matches = pattern.findall(html_text)

    weapons = []
    seen = set()
    for text in matches:
        name = text.strip()
        # 去除可能残留的 HTML 标签
        name = re.sub(r'<[^>]+>', '', name)
        # 解码 HTML 实体
        name = html.unescape(name)
        if name and name not in seen:
            seen.add(name)
            weapons.append(name)

    return weapons


if __name__ == "__main__":
    for i, name in enumerate(fetch_weapon_names(), 1):
        print(f"{i}. {name}")
