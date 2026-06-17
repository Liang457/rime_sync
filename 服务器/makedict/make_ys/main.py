import argparse
import logging
import os
import re
import time

from ys_api_crawler import (
    fetch_role_names,
    fetch_weapon_names,
    fetch_artifact_names,
    fetch_food_names,
    fetch_bag_item_names,
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
    parser = argparse.ArgumentParser(description="生成原神词库 ys.dict.yaml")
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
            # 跳过空行和注释行
            if not word or word.startswith("#"):
                continue
            words.append(word)
    logging.info(f"从 {filepath} 读取到 {len(words)} 个词")
    return words


def preprocess_word(word):
    """
    对单个词进行预处理：
    1. 去除（...）及括号本身
    2. 去除「」引号本身，保留内部内容
    3. 去除 · 点号
    4. 去除【...】及内部内容（如 桑多涅【预告】→ 桑多涅）
    """
    # 1. 去除（...）及括号本身
    word = re.sub(r"（[^）]*）", "", word)
    # 2. 去除「」引号本身，保留内部内容
    word = word.replace("「", "").replace("」", "")
    # 3. 去除 · 点号
    word = word.replace("·", "")
    # 4. 去除【...】及内部内容（如 桑多涅【预告】→ 桑多涅）
    word = re.sub(r"【[^】]*】", "", word)
    # 最后去除多余空白
    return word.strip()


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


def write_dict_yaml(words, version, filepath="ys.dict.yaml"):
    """
    将词列表写入 ys.dict.yaml 文件。
    文件开头为 YAML 头部，随后每行一词。
    """
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write("name: ys\n")
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
    roles = fetch_role_names()
    logging.info(f"共获取到 {len(roles)} 个角色")

    weapons = fetch_weapon_names()
    logging.info(f"共获取到 {len(weapons)} 个武器")

    artifacts = fetch_artifact_names()
    logging.info(f"共获取到 {len(artifacts)} 个圣遗物")

    foods = fetch_food_names()
    logging.info(f"共获取到 {len(foods)} 个食物")

    bag_items = fetch_bag_item_names()
    logging.info(f"共获取到 {len(bag_items)} 个背包物品")

    others = read_other_words()

    # 2. 合并所有来源
    all_words = roles + weapons + artifacts + foods + bag_items + others
    logging.info(f"合并后共 {len(all_words)} 个词（未去重）")

    # 3. 预处理
    processed = [preprocess_word(w) for w in all_words]
    processed = [w for w in processed if w]
    logging.info("预处理完成")

    # 4. 去重
    final_words = deduplicate(processed)
    logging.info(f"去重后共 {len(final_words)} 个词")

    # 5. 写入文件
    write_dict_yaml(final_words, version)


if __name__ == "__main__":
    main()
