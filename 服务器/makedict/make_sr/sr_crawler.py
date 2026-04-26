import html
import urllib.request
import re


def fetch_role_names():
    """
    从 bilibili 星穹铁道 wiki 角色图鉴页面爬取所有角色名。
    返回：角色名字符串列表（已去重，保持页面出现顺序）
    """
    url = "https://wiki.biligame.com/sr/%E8%A7%92%E8%89%B2%E5%9B%BE%E9%89%B4"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) "
            "Gecko/20100101 Firefox/150.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://wiki.biligame.com/sr/%E8%A7%92%E8%89%B2%E5%9B%BE%E9%89%B4",
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

    # 提取 <div class="chara-name">角色名</div> 中的角色名
    pattern = re.compile(r'<div\s+class=["\']chara-name["\'][^>]*>(.*?)</div>', re.S)
    matches = pattern.findall(html_text)

    roles = []
    seen = set()
    for text in matches:
        name = text.strip()
        # 去除内部可能残留的 HTML 标签
        name = re.sub(r'<[^>]+>', '', name)
        # 解码 HTML 实体
        name = html.unescape(name)
        if name and name not in seen:
            seen.add(name)
            roles.append(name)

    return roles


if __name__ == "__main__":
    for i, name in enumerate(fetch_role_names(), 1):
        print(f"{i}. {name}")
