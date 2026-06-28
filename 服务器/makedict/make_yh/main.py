import argparse
import logging
import os
import re
import time

from yh_api_crawler import (
    fetch_character_names,
    fetch_arc_disk_names,
    fetch_sky_curtain_names,
    fetch_anomaly_names,
    fetch_item_names,
    fetch_ability_names,
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
    parser = argparse.ArgumentParser(description="生成异环词库 yh.dict.yaml")
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


def process_character_name(name):
    """
    角色名特殊处理：
    对含 · / • / 空格 的名字，拆分为多个词条：
    1. 去分隔符的合并形式（如 维琳娜艾嘉德）
    2. 每个分隔部分（如 维琳娜、艾嘉德）

    若无分隔符则原样返回。
    """
    # 检测分隔符
    if "·" in name:
        sep = "·"
    elif "•" in name:
        sep = "•"
    elif " " in name:
        sep = " "
    else:
        return [name]

    parts = [p.strip() for p in name.split(sep) if p.strip()]
    # 合并形式（去分隔符）
    joined = name.replace(sep, "").replace(" ", "")
    return [joined] + parts


def preprocess_word(word):
    """
    对单个词进行通用预处理。
    返回：预处理后的词列表（可能因拆分返回多个词）

    处理规则：
    1. & 视为拆分
    2. 去除（...）及括号本身
    3. 去除【...】（GameKee 分类标签）
    4. 去除「」引号本身，保留内部内容
    5. ，（中文逗号）视为拆分
    6. ！、：、《》 去除标点本身
    7. 英文部分去除（仅当词中含中文时）
    8. · / • 去除点本身（角色名已在 process_character_name 处理）
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

    # 3. 去除【...】（GameKee 分类标签，如"新锐猎人攻略 【道具-角色养成】"）
    results = [re.sub(r"【[^】]*】", "", w).strip() for w in results]
    results = [r for r in results if r]

    # 4. 去除「」
    results = [w.replace("「", "").replace("」", "").strip() for w in results]
    results = [r for r in results if r]

    # 5. ，拆分
    new_results = []
    for w in results:
        if "，" in w:
            new_results.extend(w.split("，"))
        else:
            new_results.append(w)
    results = [r.strip() for r in new_results if r.strip()]

    # 6. 去除标点！、：、《》
    results = [re.sub(r"[！、：：《》]", "", w).strip() for w in results]
    results = [r for r in results if r]

    # 7. 英文部分去除
    #    若词中含中文，则去除连续的英文字母+数字片段
    #    纯英文词保留
    new_results = []
    for w in results:
        if re.search(r"[一-鿿]", w):
            w = re.sub(r"[a-zA-Z0-9.]+", "", w).strip()
            if w:
                new_results.append(w)
        else:
            if w:
                new_results.append(w)
    results = new_results

    # 8. 去除 · / •（只去掉点本身）
    results = [w.replace("·", "").replace("•", "").strip() for w in results]
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


def write_dict_yaml(words, version, filepath="yh.dict.yaml"):
    """
    将词列表写入 yh.dict.yaml 文件。
    文件开头为 YAML 头部，随后每行一词。
    """
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write("name: yh\n")
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
    raw_characters = fetch_character_names()
    logging.info(f"共获取到 {len(raw_characters)} 个角色")

    arc_disks = fetch_arc_disk_names()
    logging.info(f"共获取到 {len(arc_disks)} 个弧盘")

    sky_curtains = fetch_sky_curtain_names()
    logging.info(f"共获取到 {len(sky_curtains)} 个空幕")

    anomalies = fetch_anomaly_names()
    logging.info(f"共获取到 {len(anomalies)} 个异象")

    items = fetch_item_names()
    logging.info(f"共获取到 {len(items)} 个道具")

    abilities = fetch_ability_names()
    logging.info(f"共获取到 {len(abilities)} 个异能")

    others = read_other_words()

    # 2. 角色名特殊处理（·/•/空格拆分）
    characters = []
    for name in raw_characters:
        characters.extend(process_character_name(name))
    characters = [c for c in characters if c]
    logging.info(f"角色名拆分后共 {len(characters)} 个")

    # 3. 合并所有来源
    all_words = characters + arc_disks + sky_curtains + anomalies + items + abilities + others
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
