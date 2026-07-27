import argparse
import logging
import os
import re
import time

from ba_api_crawler import (
    fetch_student_names,
    fetch_npc_names,
    fetch_gift_names,
)
from moegirl_crawler import fetch_surnames

_CHINESE_RE = re.compile(r"[一-鿿]")
_CHINESE_ONLY_RE = re.compile(r"[一-鿿]+")


def setup_logging():
    """配置日志输出格式。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_version():
    """
    从命令行参数获取版本名，未提供时用当前整数时间戳作为版本名。
    使用 parse_known_args 避免 argparse 遇到 --help 等参数时触发 SystemExit。
    """
    parser = argparse.ArgumentParser(description="生成蔚蓝档案词库 ba.dict.yaml")
    parser.add_argument(
        "version",
        nargs="?",
        default=None,
        help="词库版本名（可选，默认为当前时间戳）",
    )
    args, _ = parser.parse_known_args()
    if args.version:
        return args.version
    return str(int(time.time()))


def read_other_words(filepath="other.txt"):
    """
    读取 other.txt，每行作为一个词返回列表。
    若文件不存在，则创建空文件并返回空列表。
    以 # 开头的行视为注释，整行剔除。
    """
    if not os.path.exists(filepath):
        logging.info(f"{filepath} 不存在，创建空文件")
        with open(filepath, "w", encoding="utf-8") as f:
            pass
        return []

    words = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            word = line.strip()
            if not word or word.startswith("#"):
                continue
            words.append(word)
    logging.info(f"从 {filepath} 读取到 {len(words)} 个词")
    return words


def process_character_name(name):
    """
    角色名特殊处理：
    对含 · / • / 空格 的名字，拆分为多个词条：
    1. 去分隔符的合并形式
    2. 每个分隔部分

    若无分隔符则原样返回。
    """
    if "·" in name:
        sep = "·"
    elif "•" in name:
        sep = "•"
    elif " " in name:
        sep = " "
    else:
        return [name]

    parts = [p.strip() for p in name.split(sep) if p.strip()]
    joined = name.replace(sep, "").replace(" ", "")
    return [joined] + parts


def is_chinese_word(w):
    """判断是否含中文字符，用于过滤纯外文主词条。"""
    return bool(_CHINESE_RE.search(w))


def preprocess_word(word):
    """
    对单个词进行通用预处理。
    返回：预处理后的词列表（可能因拆分返回多个词）

    处理规则：
    1. & 视为拆分
    2. 去除（...）及括号本身（全角）
    3. 去除(...)（半角，BA 变体标记如 妃咲(泳装)）
    4. 去除【...】（GameKee 分类标签）
    5. 去除「」引号本身，保留内部内容
    6. ，（中文逗号）视为拆分
    7. ！、：、《》 去除标点本身
    8. 英文部分去除（仅当词中含中文时）
    9. · / • 去除点本身（角色名已在 process_character_name 处理）
    """
    results = [word]

    # 1. & 拆分
    new_results = []
    for w in results:
        if "&" in w:
            new_results.extend(w.split("&"))
        else:
            new_results.append(w)
    results = [r.strip() for r in new_results if r.strip()]

    # 2. 去除（...）全角
    results = [re.sub(r"（[^）]*）", "", w).strip() for w in results]
    results = [r for r in results if r]

    # 3. 去除(...) 半角（BA 变体标记）
    results = [re.sub(r"\([^)]*\)", "", w).strip() for w in results]
    results = [r for r in results if r]

    # 4. 去除【...】（GameKee 分类标签）
    results = [re.sub(r"【[^】]*】", "", w).strip() for w in results]
    results = [r for r in results if r]

    # 5. 去除「」
    results = [w.replace("「", "").replace("」", "").strip() for w in results]
    results = [r for r in results if r]

    # 6. ，拆分
    new_results = []
    for w in results:
        if "，" in w:
            new_results.extend(w.split("，"))
        else:
            new_results.append(w)
    results = [r.strip() for r in new_results if r.strip()]

    # 7. 去除标点！、：、《》
    results = [re.sub(r"[！、：：《》]", "", w).strip() for w in results]
    results = [r for r in results if r]

    # 8. 英文部分去除
    #    若词中含中文，则去除连续的英文字母+数字片段后保留
    #    纯非中文词直接丢弃（上层会用 fullmatch 做二次过滤，此处提前清理）
    new_results = []
    for w in results:
        if _CHINESE_RE.search(w):
            w = re.sub(r"[a-zA-Z0-9.]+", "", w).strip()
            if w:
                new_results.append(w)
    results = new_results

    # 9. 去除 · / •（只去掉点本身）
    results = [w.replace("·", "").replace("•", "").strip() for w in results]
    results = [r for r in results if r]

    # 10. 清除残留的半角括号
    #     解释：角色名中的 · 若出现在括号内，process_character_name 按 · 拆分后
    #     可能导致括号成对关系断裂。步骤 3 的 (...) 移除是基于完整括号对的，断裂的
    #     残缺括号会被遗漏，因此在此处统一清理所有残留半角括号。
    results = [w.replace("(", "").replace(")", "").strip() for w in results]
    results = [r for r in results if r]

    return results


def deduplicate(words):
    """
    对词列表进行去重，保持首次出现的顺序。
    """
    seen = set()
    result = []
    for w in words:
        if w and w not in seen:
            seen.add(w)
            result.append(w)
    return result


def write_dict_yaml(words, version, filepath="ba.dict.yaml"):
    """
    将词列表写入 ba.dict.yaml 文件。
    文件开头为 YAML 头部，随后每行一词。
    """
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write("name: ba\n")
        f.write(f'version: "{version}"\n')
        f.write("sort: by_weight\n")
        f.write("...\n")
        for word in words:
            f.write(f"{word}\n")
    logging.info(f"词库已写入 {filepath}，共 {len(words)} 个词")


def main():
    setup_logging()

    version = get_version()
    logging.info(f"词库版本: {version}")

    # 1. 从 GameKee Wiki API 获取各分类数据
    raw_students, student_aliases = fetch_student_names()
    logging.info(
        f"共获取到 {len(raw_students)} 个学生，{len(student_aliases)} 个中文别名"
    )

    raw_npcs, npc_aliases = fetch_npc_names()
    logging.info(
        f"共获取到 {len(raw_npcs)} 个 NPC，{len(npc_aliases)} 个中文别名"
    )

    gifts, gift_aliases = fetch_gift_names()
    logging.info(
        f"共获取到 {len(gifts)} 个礼物，{len(gift_aliases)} 个中文别名"
    )

    others = read_other_words()

    # 2. 角色名特殊处理（·/•/空格拆分）
    students = []
    for name in raw_students:
        students.extend(process_character_name(name))
    students = [s for s in students if s]
    logging.info(f"学生名拆分后共 {len(students)} 个")

    npcs = []
    for name in raw_npcs:
        npcs.extend(process_character_name(name))
    npcs = [n for n in npcs if n]
    logging.info(f"NPC 名拆分后共 {len(npcs)} 个")

    # 3. 从萌娘百科抓取带姓全名（姓 + 名）
    try:
        surnamed = fetch_surnames()  # [(日文姓, 日文名, 中文全名), ...]
        full_names_cn = [t[2] for t in surnamed]
        surnames_cn = [
            t[2][:len(t[0])]
            for t in surnamed
            if len(t[2]) >= len(t[0]) and t[2].startswith(t[0])
        ]
        logging.info(
            f"从萌娘百科抓取到 {len(surnamed)} 个带姓全名，"
            f"{len(surnames_cn)} 个姓氏"
        )
    except Exception as e:
        logging.warning(f"萌娘百科抓取失败，跳过全名补充: {e}")
        full_names_cn = []
        surnames_cn = []

    # 4. 合并所有来源
    all_words = (
        students + student_aliases
        + npcs + npc_aliases
        + gifts + gift_aliases
        + others
        + full_names_cn + surnames_cn
    )
    logging.info(f"合并后共 {len(all_words)} 个词（未去重、未预处理）")

    # 5. 通用预处理（返回列表，可能拆分）
    #    两阶段过滤：
    #      预处理前：快速筛掉不含中文或长度不足 2 的词，避免不必要的预处理开销
    #      预处理后：再次校验结果为纯中文且长度 ≥ 2
    #              预处理可能通过拆分/剥离去掉非中文部分，此阶段确保最终词条质量
    processed = []
    for w in all_words:
        w = w.strip()
        if not w:
            continue
        if not is_chinese_word(w):
            continue
        if len(w) < 2:
            continue
        for p in preprocess_word(w):
            p = p.strip()
            if not p:
                continue
            if not _CHINESE_ONLY_RE.fullmatch(p):
                continue
            if len(p) < 2:
                continue
            processed.append(p)
    logging.info(f"预处理后共 {len(processed)} 个词（含拆分）")

    # 6. 去重
    final_words = deduplicate(processed)
    logging.info(f"去重后共 {len(final_words)} 个词")

    # 7. 写入文件
    write_dict_yaml(final_words, version)


if __name__ == "__main__":
    main()
