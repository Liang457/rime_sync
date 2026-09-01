import logging
import threading
from pathlib import Path

from utils.config_loader import config_manager
from utils.error_handler import APIError
from utils.rime_ice_manager import update_rime_ice_repo, copy_to_runtime
from utils.script_runner import script_runner

logger = logging.getLogger(__name__)

# 进程内互斥锁：防止多线程同时触发流水线导致 runtime 目录竞态搬移
# （仅适用于单进程部署，如 waitress；多进程部署需外部文件锁）
_remote_sync_lock = threading.Lock()


def _dict_name_from_file(fname):
    """从输出文件名推导 dict 名称（与客户端 _auto_add_to_dict 一致）。"""
    if fname.endswith('.dict.yaml'):
        return fname[:-10]
    if fname.endswith('.yaml'):
        return fname[:-5]
    return fname


def _read_lines(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.readlines()


def _write_lines(path, lines):
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def _auto_add_to_dict(dict_entries, dict_line):
    """把生成的词库条目写入 runtime/rime_ice.dict.yaml（先去重再插入）。

    参数:
        dict_entries: [(dict_name, entry)]，entry 形如 "  - cn_dicts/<name>"
        dict_line: 起始插入行号（1-based）

    返回:
        每条目的状态列表: {"dict_name", "entry", "line", "status": "added"|"exists"}
    """
    runtime_path = Path(config_manager.resolve_path(config_manager.get("server", "paths.runtime")))
    dict_file = runtime_path / "rime_ice.dict.yaml"

    if not dict_file.exists():
        logger.error(f"rime_ice.dict.yaml 不存在: {dict_file}")
        raise APIError("rime_ice.dict.yaml 不存在", 404)

    lines = _read_lines(dict_file)
    existing = {line.strip() for line in lines}
    additions = []
    current_line = dict_line

    for dict_name, entry in dict_entries:
        key = entry.strip()
        if key in existing or current_line < 1 or current_line > len(lines) + 1:
            additions.append({
                "dict_name": dict_name, "entry": entry, "line": None, "status": "exists"
            })
            logger.info(f"条目已存在或行号无效，跳过: {entry}")
            continue
        lines.insert(current_line - 1, entry + '\n')
        existing.add(key)
        additions.append({
            "dict_name": dict_name, "entry": entry, "line": current_line, "status": "added"
        })
        logger.info(f"已添加 {entry} 到 rime_ice.dict.yaml 第{current_line}行")
        current_line += 1

    if any(a["status"] == "added" for a in additions):
        _write_lines(dict_file, lines)
    return additions


def run_remote_sync(device, version=None, force=True, add_to_dict=True, dict_line=18):
    """完整远端同步流水线：更新 rime-ice → 复制到 runtime → 批量脚本 → 自动插入 dict。

    参数:
        device: 调用设备标识（必须在 scripts.trusted_users 中）
        version: 词库版本（缺省时由服务器分配）
        force: 是否强制更新 rime-ice（默认 True）
        add_to_dict: 是否自动把生成的词库写入 rime_ice.dict.yaml
        dict_line: 插入行号（默认 18）

    返回:
        聚合结果字典（update / runtime_copy / scripts / dict_additions / summary）
    """
    # Step A — 权限预检（在任何耗时操作之前 fail-fast，且不占用流水线锁）
    script_runner.check_permission(device)

    with _remote_sync_lock:
        return _run_remote_sync_locked(device, version, force, add_to_dict, dict_line)


def _run_remote_sync_locked(device, version=None, force=True, add_to_dict=True, dict_line=18):
    """在持有流水线锁的前提下执行完整同步（由 run_remote_sync 调用）。"""
    result = {
        "update": None,
        "runtime_copy": None,
        "scripts": [],
        "dict_additions": [],
        "summary": {
            "total": 0, "success": 0, "failed": 0,
            "dict_added": 0, "dict_skipped": 0,
            "files_unchanged": 0, "files_updated": 0, "files_created": 0,
        },
    }

    # Step B — 更新 rime-ice
    logger.info(f"[remote_sync] 设备 {device} 发起完整同步")
    update_result = update_rime_ice_repo(force=force)
    result["update"] = update_result

    # Step C — 复制到 runtime（仅当有更新）
    if update_result.get("upgraded"):
        logger.info("[remote_sync] rime-ice 已更新，复制到 runtime")
        result["runtime_copy"] = copy_to_runtime()

    # Step D — 批量运行脚本（失败不中断，保留 run-all-scripts 语义）
    scripts = script_runner.list_scripts()
    if not scripts:
        logger.info("[remote_sync] 无可执行脚本")
    else:
        logger.info(f"[remote_sync] 将执行 {len(scripts)} 个脚本: {', '.join(scripts)}")
        for name in scripts:
            script_result = {
                "script": name,
                "success": False,
                "version": version,
                "output_files": [],
                "total_size": 0,
                "error": None,
            }
            try:
                r = script_runner.run_script(name, version, device)
                script_result["success"] = True
                script_result["version"] = r.get("version", version)
                script_result["output_files"] = r.get("output_files", [])
                script_result["output_files_detail"] = r.get("output_files_detail", [])
                script_result["total_size"] = r.get("total_size", 0)
                result["summary"]["success"] += 1
                for detail in script_result["output_files_detail"]:
                    key = f"files_{detail.get('status', 'updated')}"
                    if key in result["summary"]:
                        result["summary"][key] += 1
            except APIError as e:
                script_result["error"] = e.message
                result["summary"]["failed"] += 1
                logger.warning(f"[remote_sync] {name} 失败: {e.message}")
            result["scripts"].append(script_result)
        result["summary"]["total"] = len(scripts)

    # Step E — 自动插入 dict
    if add_to_dict:
        dict_entries = []
        for s in result["scripts"]:
            if s["success"]:
                for fname in s["output_files"]:
                    dict_name = _dict_name_from_file(fname)
                    dict_entries.append((dict_name, f"  - cn_dicts/{dict_name}"))
        if dict_entries:
            result["dict_additions"] = _auto_add_to_dict(dict_entries, dict_line)
            result["summary"]["dict_added"] = sum(1 for a in result["dict_additions"] if a["status"] == "added")
            result["summary"]["dict_skipped"] = sum(1 for a in result["dict_additions"] if a["status"] == "exists")

    logger.info(f"[remote_sync] 完成: {result['summary']}")
    return result
