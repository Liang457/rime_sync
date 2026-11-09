"""版本号：从文件内容解析 + 与 manifest 备注组合成展示字段。

两个来源：
- 解析版本：文件自己写的版本，三级取第一个命中的——顶层 `version:`（词库内容
  版本）、`schema:` 块内的 `version:`（方案版本）、顶层 `config_version:`
  （Rime 配置版本；default/weasel/squirrel 与 trime 主题只有这一种）。注释头
  （`# 语料版本: 20261105`）不算，只有行首是键才算。
- 备注版本：manifest 里发布者/人工标注的 version（如主题包的构建标签）。

展示规则（解析优先）：
- 有解析、无备注 → 只显示解析版本；
- 有解析、有备注 → 「解析版本（备注版本）」，两者相同则只显示一次；
- 无解析、有备注 → 只显示备注版本；
- 都没有 → 空串（模板渲染成 `--`）。

`config_version` 命中时同样占据主位，不因备注降级：主题包显示
`3.0（v2.6-restore-…）`，构建标签一律进括号（主人 2026-11-09 定）。

解析失败一律返回空串：版本只是补充信息，不能让列表页因为某个坏文件而报错。
"""
from __future__ import annotations

from pathlib import Path

SUFFIXES = (".yaml", ".yml")
HEAD_BYTES = 8192  # 版本都在文件开头，大词库不整文件读


def _scalar(raw: str) -> str:
    """取 `version:` 后面的标量值：去引号、去行内注释、去首尾空白。"""
    value = raw.strip()
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        if end > 0:
            return value[1:end].strip()
    for sep in (" #", "\t#"):
        cut = value.find(sep)
        if cut >= 0:
            value = value[:cut]
    return value.strip()


def parse_version(text: str) -> str:
    """从（文件开头的）文本里取版本号。

    三级：顶层 `version:`（词库内容版本）→ `schema:` 块内的 `version:`（方案
    版本）→ 顶层 `config_version:`（Rime 配置版本，default/weasel/squirrel 与
    trime 主题只有这个）。
    """
    top = schema = config = ""
    in_schema = False
    for raw in text.splitlines():
        body = raw.strip()
        if not body or body.startswith("#"):
            continue
        if not raw[0].isspace():  # 顶层键同时意味着 schema 块结束
            in_schema = body.endswith(":") and body.split(":", 1)[0].strip() == "schema"
            if not top and body.startswith("version:"):
                top = _scalar(body[len("version:"):])
            elif not config and body.startswith("config_version:"):
                config = _scalar(body[len("config_version:"):])
            continue
        if in_schema and not schema and body.startswith("version:"):
            schema = _scalar(body[len("version:"):])
    return top or schema or config


def inner_version(path: Path | None) -> str:
    """解析文件自身的版本；扩展名不支持或读不到时返回空串。"""
    if path is None or path.suffix.lower() not in SUFFIXES:
        return ""
    try:
        with path.open("rb") as fh:
            head = fh.read(HEAD_BYTES)
    except OSError:
        return ""
    return parse_version(head.decode("utf-8", "replace"))


def display(parsed: str, note: str) -> dict:
    """合成模板要的两个字段：version（主）+ version_note（括号补充，可为空）。"""
    parsed = (parsed or "").strip()
    note = (note or "").strip()
    if parsed:
        return {"version": parsed, "version_note": "" if note == parsed else note}
    return {"version": note, "version_note": ""}
