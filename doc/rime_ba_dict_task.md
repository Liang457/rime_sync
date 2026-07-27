# 蔚蓝档案 Rime 词库 — 姓氏/全名 扩展任务说明

> 给 OpenCode 的参考文档。OpenCode 读完后应能独立完成 `rime_server/服务器/makedict/make_ba/` 下脚本的改写。

---

## 1. 任务目标

为 `ba.dict.yaml` 补充学生角色的**全名**（含姓）。当前数据源 GameKee Wiki API 只返回"通称"（如"日奈"），缺失"姓"（如"空崎"）。需要让最终词库在保留通称/变体/别名基础上，多一组"姓+名"形式的全名词条。

---

## 2. 现有代码结构

```
rime_server/服务器/makedict/make_ba/
├── main.py              # 主流程：拉数据 → 预处理 → 去重 → 写 YAML
├── ba_api_crawler.py    # GameKee API 客户端（fetch_*_names）
└── other.txt            # 手动补充词条
```

调用栈：

```
fetch_student_names()  → (names, aliases)   # GameKee pid=23941 板块 49443
fetch_npc_names()      → (names, aliases)   # 板块 107619
fetch_gift_names()     → (names, aliases)   # 板块 107816
                              ↓
process_character_name()  # 角色名按 ·/•/空格 拆分
preprocess_word()         # 10 步通用清洗（含括号/标点/英文/去括号）
deduplicate()             # 保序去重
write_dict_yaml()         # 写 Rime 词库（YAML 头 + 词条每行一个）
```

---

## 3. 现状问题（用户反馈）

| # | 问题 | 数据 | 现状 |
|---|------|------|------|
| 1 | 太多 1 字词 | 学生 25 + NPC 13 = 38 个 1 字 | 进词库没意义 |
| 2 | 主词条含纯外文 | 礼物板块 1 条 `Samuela「The・Beyond」` | `name_alias` 过滤了纯日文/英文，但 `name` 主词条没过滤 |
| 3 | 缺姓氏 | GameKee 列表 API 不存"姓"字段；试了 `detailV1?entry_id=` 全部 404 | 需换数据源 |

---

## 4. 新数据源：萌娘百科"蔚蓝档案/译名对照表"

### 4.1 入口

- 页面 URL：`https://mzh.moegirl.org.cn/蔚蓝档案/译名对照表`
- 字段列：日服原文 / 共识译名 / 国际服译名 / 简中服译名 / 民间译名 / 英文名 / 备注
- 关键：**"日服原文"列 = `姓 名` 形式（中间半角空格）**，"共识译名"列 = 中文全名（如"空崎阳奈"）

### 4.2 已抓样本（20 条）

```
七神  リン        → 七神琳
由良木 モモカ      → 由良木桃香
岩櫃  アユム      → 岩柜步梦
不知火 カヤ       → 不知火花耶
扇喜  アオイ      → 扇喜葵
砂狼  シロコ      → 砂狼白子
小鳥遊 ホシノ     → 小鸟游星野
黒見  セリカ      → 黑见茜香
奥空  アヤネ      → 奥空绫音
十六夜 ノノミ     → 十六夜野乃美
梔子  ユメ        → 栀子梦
羽沼  マコト      → 羽沼真琴
棗  イロハ        → 枣伊吕波
丹花  イブキ      → 丹花伊吹
京極  サツキ      → 京极皋月
元宮  チアキ      → 元宫千秋
空崎  ヒナ        → 空崎阳奈
銀鏡  イオリ      → 银镜伊织
天雨  アコ        → 天雨亚子
火宮  チナツ      → 火宫千夏
```

### 4.3 抓取方式（已验证可跑）

```python
import urllib.request, re

def fetch_moegirl_surnames():
    url = "https://mzh.moegirl.org.cn/蔚蓝档案/译名对照表"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Firefox/153.0"})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")

    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
    out = []  # [(日文姓, 日文名, 中文共识译名), ...]
    for r in rows:
        ja = re.search(r'<span lang="ja">([^<]+)</span>', r)
        if not ja: continue
        src = ja.group(1).strip()
        if " " not in src: continue          # 只取"姓 名"形式
        consensus = re.search(
            r'<td><a href="[^"]+" title="[^"]+">([^<]+)</a></td>', r
        )
        if not consensus: continue
        cn = consensus.group(1).strip()
        if not cn: continue
        fam, given = src.split(" ", 1)
        out.append((fam, given, cn))
    return out
```

实测返回 **167 条**有效记录。

### 4.4 覆盖度说明

- 萌娘页面**只收录有日文全名的学生角色**（~167 个）
- 缺：1 字学生通称（"泉"等 GameKee 学生列表的 25 个"通称"=本名即学生花名）+ NPC/卫星（多数无个人姓氏）+ 礼物
- 缺的部分继续走 GameKee 流水线补齐

---

## 5. 修改需求

### 5.1 新增数据源

在 `ba_api_crawler.py` 或新建 `moegirl_crawler.py` 中加：

```python
def fetch_surnames():
    """从萌娘译名对照表拉 167 个有姓角色。
    返回 [(日文姓, 日文名, 中文全名), ...]"""
    ...
```

### 5.2 主流程改造（main.py）

在 `students = []` 之前，加一行从萌娘拉全名：

```python
surnamed = fetch_surnames()  # [(fam_ja, given_ja, full_cn), ...]
full_names_cn = [t[2] for t in surnamed]  # 只取中文全名
# 也可保留姓+名拆分供 process_character_name
```

合并时把 `full_names_cn` 加到 `all_words` 链尾。

### 5.3 清洗规则修订

`preprocess_word` 之前加 **2 道门**：

```python
def is_chinese_word(w):
    """必须含中文字符，过滤纯外文主词条。"""
    return bool(re.search(r"[一-鿿]", w))
```

应用位置（main.py 的 `processed = []` 循环）：

```python
processed = []
for w in all_words:
    if not is_chinese_word(w):
        continue                          # 门 1：纯外文去掉（影响 1 条礼物）
    if len(w.strip()) < 2:
        continue                          # 门 2：1 字词去掉（影响 38 条学生/NPC）
    processed.extend(preprocess_word(w))
```

注：上面 2 道门加在 `all_words`（含 GameKee 数据）上即可，萌娘数据已全部是中文 + 2 字以上。

### 5.4 不动的部分

- `process_character_name` —— 萌娘数据里没有 `·` `•` 字符，不需要走
- `write_dict_yaml` —— 字段格式 `name: ba` / `version` / `sort: by_weight` 不变
- `other.txt` 加载逻辑不变
- `fetch_student_names` / `fetch_npc_names` / `fetch_gift_names` —— 保留

---

## 6. 验收口径

跑 `python3 main.py` 后检查输出文件：

1. **总量**：去重后行数应较改前**增加约 150-170**（萌娘贡献），1 字行**减少 38**
2. **含中文**：每行必须有中文字符（`grep -P "^[^\u4e00-\u9fff]+$" ba.dict.yaml` 应为空）
3. **3-4 字新词**：抽检应能看到 `空崎阳奈` / `小鸟游星野` / `砂狼白子` / `天童爱丽丝` 等
4. **姓也进词库**：上面"姓+名"之外，可选把单独的姓（"空崎"/"砂狼"/"小鸟游"等）也加入 —— 决定见 §7

---

## 7. 待用户决定

1. 单独的**姓**要不要进词库？（如"空崎"作为 2 字词单独成条）
   - 倾向 **要**，便于用户打"kongqi"上屏；但会膨胀词库
2. 长度下限是 `len < 2` 还是 `len < 3`？学生通称都是 2 字，目前推荐 **`len < 2`**
3. 萌娘抓取失败时（罕见）是否 fallback 继续用 GameKee？建议 **是**（try/except 包住，不阻断主流程）

---

## 8. 风险与注意

- 萌娘页面**非公开 API**，靠解析 HTML；页面结构若改，`re` 模板会失效。**仅做个人/小规模使用**，不可商业化（CC BY-NC-SA 3.0 CN）
- 萌娘页面**更新滞后于游戏**新角色（游戏新学生日服上线后通常 1-2 周才补全）
- GameKee 的 1 字学生通称（如"泉"）和萌娘的全名是**互补**的，不要互相覆盖

---

## 9. 文件改动清单

```
rime_server/服务器/makedict/make_ba/
├── main.py              ← 加 is_chinese_word 门 + 拼接 full_names_cn
├── ba_api_crawler.py    ← 不动
├── moegirl_crawler.py   ← 新建（fetch_surnames 实现）
└── other.txt            ← 不动
```

OpenCode 按这个顺序做即可：`moegirl_crawler.py` → `main.py` 改两步 → 跑 → diff 行数验收。
