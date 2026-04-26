import html
import urllib.request
import re


def fetch_material_names():
    """
    从 bilibili 星穹铁道 wiki 道具筛选页面爬取所有道具名。
    页面中 id="CardSelectTr" 的表格内，每行的第二个 <td> 中 <a> 的文本即为道具名。
    返回：道具名字符串列表（已去重，保持页面出现顺序）
    """
    url = "https://wiki.biligame.com/sr/%E9%81%93%E5%85%B7%E7%AD%9B%E9%80%89"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) "
            "Gecko/20100101 Firefox/150.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://wiki.biligame.com/sr/%E9%81%93%E5%85%B7%E7%AD%9B%E9%80%89",
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

    # 1. 提取整个目标 table（id="CardSelectTr"）
    table_pattern = re.compile(
        r'<table[^>]*\bid=["\']CardSelectTr["\'][^>]*>(.*?)</table>',
        re.S,
    )
    table_match = table_pattern.search(html_text)
    if not table_match:
        return []
    table_html = table_match.group(1)

    # 2. 提取 tbody 内容（若存在）
    tbody_pattern = re.compile(r'<tbody[^>]*>(.*?)</tbody>', re.S)
    tbody_match = tbody_pattern.search(table_html)
    if tbody_match:
        tbody_html = tbody_match.group(1)
    else:
        tbody_html = table_html

    # 3. 提取所有行 <tr>...</tr>
    tr_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
    tr_matches = tr_pattern.findall(tbody_html)

    materials = []
    seen = set()
    td_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.S)
    a_pattern = re.compile(r'<a[^>]*>(.*?)</a>', re.S)

    for tr_html in tr_matches:
        # 跳过包含 <th> 的表头行
        if '<th' in tr_html:
            continue

        td_matches = td_pattern.findall(tr_html)
        if len(td_matches) < 2:
            continue

        second_td = td_matches[1]
        a_match = a_pattern.search(second_td)
        if not a_match:
            continue

        name = a_match.group(1).strip()
        # 去除可能残留的 HTML 标签
        name = re.sub(r'<[^>]+>', '', name)
        # 解码 HTML 实体
        name = html.unescape(name)
        # 过滤脏数据（如 NAME==xxx 占位符）
        if name.startswith("NAME=="):
            continue
        if name and name not in seen:
            seen.add(name)
            materials.append(name)

    return materials


if __name__ == "__main__":
    for i, name in enumerate(fetch_material_names(), 1):
        print(f"{i}. {name}")
