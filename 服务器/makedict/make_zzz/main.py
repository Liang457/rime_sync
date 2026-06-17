import argparse
import logging
import os
import re
import time

from zzz_api_crawler import (
    fetch_agent_names,
    fetch_weapon_names,
    fetch_bangboo_names,
    fetch_drive_disk_names,
    fetch_material_names,
)


def setup_logging():
    """配置日志输出格式。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_version():
    """
    解析命令行参数获取版本名。
    若未提供参数或解析失败，则使用当前时间戳作为 fallback。
    """
    parser = argparse.ArgumentParser(description="生成绝区零词库 zzz.dict.yaml")
    parser.add_argument(
        "version",
        nargs="?",
        default=None,
        help="词库版本名（可选，默认为当前时间戳）",
    )
    try:
        args = parser.parse_args()
    except SystemExit:
        logging.warning("命令行参数解析失败，使用 time.time() 作为版本名")
        return str(time.time())

    if args.version:
        return args.version
    return str(time.time())


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


def process_agent_names(names):
    """
    代理人名字特殊处理：
    对含 · / • / 半角空格 的名字，拆分为多个词条：
    1. 去分隔符的合并形式（如 维琳娜艾嘉德）
    2. 每个分隔部分（如 维琳娜、艾嘉德）

    示例：
      维琳娜·艾嘉德 → 维琳娜艾嘉德, 维琳娜, 艾嘉德
      浮波 柚叶     → 浮波柚叶, 浮波, 柚叶
      星徽·比利·奇德 → 星徽比利奇德, 星徽, 比利, 奇德
    """
    results = []
    for name in names:
        # 判断使用哪种分隔符
        if "·" in name:
            sep = "·"
        elif "•" in name:
            sep = "•"
        elif " " in name:
            sep = " "
        else:
            results.append(name)
            continue

        parts = [p.strip() for p in name.split(sep) if p.strip()]
        # 合并形式
        joined = name.replace(sep, "").replace(" ", "")
        results.append(joined)
        for p in parts:
            results.append(p)

    return results


def preprocess_word(word):
    """
    对单个词进行通用预处理。
    返回：预处理后的词列表（可能因拆分返回多个词）

    处理规则：
    1. & 视为拆分
    2. 去除（...）及括号本身
    3. 去除「」引号本身，保留内部内容
    4. ，（中文逗号）视为拆分
    5. ！、：、《》 去除标点本身
    6. 英文部分去除（仅当词中含中文时）
    7. · / • 去除点本身（代理人名已在 process_agent_names 处理）
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

    # 2. 去除（...）
    results = [re.sub(r"（[^）]*）", "", w).strip() for w in results]
    results = [r for r in results if r]

    # 3. 去除「」
    results = [w.replace("「", "").replace("」", "").strip() for w in results]
    results = [r for r in results if r]

    # 4. ，拆分
    new_results = []
    for w in results:
        if "，" in w:
            new_results.extend(w.split("，"))
        else:
            new_results.append(w)
    results = [r.strip() for r in new_results if r.strip()]

    # 5. 去除标点！、：、《》
    results = [re.sub(r"[！、：：《》]", "", w).strip() for w in results]
    results = [r for r in results if r]

    # 6. 英文部分去除
    #    若词中含中文，则去除连续的英文字母片段（如 耀嘉音LV → 耀嘉音）
    #    纯英文词保留。不删除数字（如 11号 应保留）
    new_results = []
    for w in results:
        if re.search(r"[一-鿿]", w):
            w = re.sub(r"[a-zA-Z.]+", "", w).strip()
            if w:
                new_results.append(w)
        else:
            if w:
                new_results.append(w)
    results = new_results

    # 7. 去除 · / • / 空格（只去掉分隔符本身）
    results = [w.replace("·", "").replace("•", "").replace(" ", "").strip() for w in results]
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


def write_dict_yaml(words, version, filepath="zzz.dict.yaml"):
    """
    将词列表写入 zzz.dict.yaml 文件。
    文件开头为 YAML 头部，随后每行一词。
    """
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write("name: zzz\n")
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

    # 1. 从米游社 Wiki API 获取各分类数据
    raw_agents = fetch_agent_names()
    logging.info(f"共获取到 {len(raw_agents)} 个代理人")

    weapons = fetch_weapon_names()
    logging.info(f"共获取到 {len(weapons)} 个音擎")

    bangboos = fetch_bangboo_names()
    logging.info(f"共获取到 {len(bangboos)} 个邦布")

    drive_disks = fetch_drive_disk_names()
    logging.info(f"共获取到 {len(drive_disks)} 个驱动盘")

    materials = fetch_material_names()
    logging.info(f"共获取到 {len(materials)} 个材料")

    others = read_other_words()

    # 2. 代理人名特殊处理（·/空格拆分）
    agents = process_agent_names(raw_agents)
    logging.info(f"代理人名拆分后共 {len(agents)} 个")

    # 3. 合并所有来源
    all_words = agents + weapons + bangboos + drive_disks + materials + others
    logging.info(f"合并后共 {len(all_words)} 个词（未去重、未预处理）")

    # 4. 通用预处理（返回列表，可能拆分）
    processed = []
    for w in all_words:
        processed.extend(preprocess_word(w))
    logging.info(f"预处理后共 {len(processed)} 个词（含拆分）")

    # 5. 去重
    final_words = deduplicate(processed)
    logging.info(f"去重后共 {len(final_words)} 个词")

    # 6. 写入文件
    write_dict_yaml(final_words, version)


if __name__ == "__main__":
    main()
