import urllib.request
import re


def fetch_role_names():
    """
    从 bilibili 原神 wiki 角色列表页面爬取所有角色名。
    返回：角色名字符串列表（已去重，保持页面出现顺序）
    """
    url = "https://wiki.biligame.com/ys/%E8%A7%92%E8%89%B2"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) "
            "Gecko/20100101 Firefox/150.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://wiki.biligame.com/ys/%E8%A7%92%E8%89%B2%E7%AD%9B%E9%80%89",
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
        # 优先尝试 UTF-8，若失败则自动检测常见中文编码
        raw_data = response.read()
        try:
            html = raw_data.decode("utf-8")
        except UnicodeDecodeError:
            html = raw_data.decode("gbk", errors="ignore")

    # with open("debug.html", "w") as f:
    #     f.write(html)

    # 提取 <div class="L">角色名</div> 中的角色名
    # 使用非贪婪匹配，忽略 class 中可能出现的额外空格或其他类名
    pattern = re.compile(r'<div\s+class=["\']L["\'][^>]*>(.*?)</div>', re.S)
    matches = pattern.findall(html)

    # 去除 HTML 实体与多余空白，去重但保留顺序
    roles = []
    seen = set()
    for text in matches:
        name = text.strip()
        if name and name not in seen:
            seen.add(name)
            roles.append(name)

    return roles


if __name__ == "__main__":
    for i, name in enumerate(fetch_role_names(), 1):
        print(f"{i}. {name}")
