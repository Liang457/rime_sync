#!/usr/bin/env python3
"""
Rime 客户端同步脚本
与 rime-server 交互，同步词库、用户输入词库等配置。
"""
import argparse
import json
import logging
import sys
from pathlib import Path

from core.config import ConfigManager, DEFAULT_CONFIG_PATH
from core.logs import setup_logging
from core.api import APIClient
from core.errors import ClientError, ConfigError, APIError
from core import sync
from core import dicts
from core import fullsync

logger = logging.getLogger(__name__)


def _setup_basic_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stderr)]
    )


def build_parser():
    parser = argparse.ArgumentParser(description="Rime 客户端同步工具")
    parser.add_argument("--config", help="配置文件路径", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    subparsers = parser.add_subparsers(dest="command", help="命令", metavar="COMMAND")

    subparsers.add_parser("status", help="获取服务器状态")

    update_parser = subparsers.add_parser("update-rime-ice", help="更新rime-ice仓库")
    update_parser.add_argument("--force", action="store_true", help="强制更新")

    script_parser = subparsers.add_parser("run-script", help="运行自定义词库脚本")
    script_parser.add_argument("script_name", help="脚本名称")
    script_parser.add_argument("version", help="词库版本")
    script_parser.add_argument("--extra", help="额外参数（JSON格式）")
    script_parser.add_argument("--no-add-to-dict", action="store_true",
                               help="不自动添加到rime_ice.dict.yaml")
    script_parser.add_argument("--dict-line", type=int, default=18,
                               help="插入行号(默认: 18)")

    subparsers.add_parser("list-scripts", help="列出可用自定义词库脚本")

    run_all_parser = subparsers.add_parser("run-all-scripts", help="执行全部自定义词库脚本")
    run_all_parser.add_argument("version", help="词库版本")
    run_all_parser.add_argument("--no-add-to-dict", action="store_true",
                                help="不自动添加到rime_ice.dict.yaml")
    run_all_parser.add_argument("--dict-line", type=int, default=18,
                                help="插入行号(默认: 18)")

    edit_parser = subparsers.add_parser("edit-file", help="编辑配置文件")
    edit_parser.add_argument("path", help="文件路径")
    edit_parser.add_argument("line", type=int, help="行号")
    edit_parser.add_argument("content", help="要插入的内容")
    edit_parser.add_argument("--action", choices=["insert", "replace", "delete"],
                             default="insert", help="编辑操作类型")

    config_upload_parser = subparsers.add_parser("upload-config", help="上传配置文件 (*.custom.yaml)")
    config_upload_parser.add_argument("file", help="配置文件路径")
    config_upload_parser.add_argument("--device", help="设备标识")
    config_upload_parser.add_argument("--overwrite", action="store_true", help="是否覆盖已存在的文件")

    userdb_parser = subparsers.add_parser("sync-userdb", help="同步用户输入词库")
    userdb_parser.add_argument("--action", choices=["download", "upload"], default="upload", help="操作类型")
    userdb_parser.add_argument("--file", help="文件名（仅下载单个文件时使用）")
    userdb_parser.add_argument("--device", help="设备标识")

    sync_upload_tar_parser = subparsers.add_parser("sync-upload-tar", help="上传用户输入词库tar包")
    sync_upload_tar_parser.add_argument("--device", help="设备标识")

    sync_upload_file_parser = subparsers.add_parser("sync-upload-file", help="上传用户输入词库单个文件")
    sync_upload_file_parser.add_argument("file", help="文件路径")
    sync_upload_file_parser.add_argument("--filename", help="文件名（可选）")
    sync_upload_file_parser.add_argument("--device", help="设备标识")

    sync_info_parser = subparsers.add_parser("sync-info", help="获取用户输入词库信息")
    sync_info_parser.add_argument("--device", help="设备标识")
    sync_info_parser.add_argument("--since", help="时间戳（仅返回此时间之后有变动的文件）")

    sync_download_tar_parser = subparsers.add_parser("sync-download-tar", help="下载用户输入词库tar包")
    sync_download_tar_parser.add_argument("--device", help="设备标识")
    sync_download_tar_parser.add_argument("--since", help="时间戳（仅包含此时间之后有变动的文件）")

    sync_download_file_parser = subparsers.add_parser("sync-download-file", help="下载用户输入词库单个文件")
    sync_download_file_parser.add_argument("filename", help="文件名")
    sync_download_file_parser.add_argument("--device", help="设备标识")

    dict_parser = subparsers.add_parser("sync-dict", help="同步配置 (cn_dicts/en_dicts/lua/opencc)")
    dict_parser.add_argument("--category", choices=["cn", "en", "lua", "opencc"], help="配置类别")

    dict_info_parser = subparsers.add_parser("dict-info", help="获取词库信息")
    dict_info_parser.add_argument("--category", choices=["cn", "en"], help="词库类别")
    dict_info_parser.add_argument("--since", help="时间戳（仅返回此时间之后有变动的文件）")

    dict_download_tar_parser = subparsers.add_parser("dict-download-tar", help="下载词库tar包")
    dict_download_tar_parser.add_argument("--category", choices=["cn", "en"], help="词库类别")
    dict_download_tar_parser.add_argument("--since", help="时间戳（仅包含此时间之后有变动的文件）")

    dict_download_file_parser = subparsers.add_parser("dict-download-file", help="下载单个词库文件")
    dict_download_file_parser.add_argument("filename", help="文件名")
    dict_download_file_parser.add_argument("--category", choices=["cn", "en"], help="词库类别")

    full_sync_info_parser = subparsers.add_parser("full-sync-info", help="获取完整配置包信息")
    full_sync_info_parser.add_argument("--exclude", help="额外排除的文件（逗号分隔）")
    full_sync_info_parser.add_argument("--since", help="时间戳（仅返回此时间之后有变动的文件）")

    full_sync_download_parser = subparsers.add_parser("full-sync-download", help="下载完整配置包")
    full_sync_download_parser.add_argument("--exclude", help="额外排除的文件（逗号分隔）")
    full_sync_download_parser.add_argument("--since", help="时间戳（仅包含此时间之后有变动的文件）")

    full_sync_upload_parser = subparsers.add_parser("full-sync-upload", help="上传完整配置包")
    full_sync_upload_parser.add_argument("file", help="tar文件路径")
    full_sync_upload_parser.add_argument("--overwrite", action="store_true", help="是否覆盖现有配置")

    subparsers.add_parser("device-list", help="获取设备列表")
    subparsers.add_parser("health", help="健康检查")
    subparsers.add_parser("interactive", help="启动交互式界面")

    return parser


def _auto_add_to_dict(api, output_files, dict_line):
    for fname in output_files:
        if fname.endswith('.dict.yaml'):
            dict_name = fname[:-10]
        elif fname.endswith('.yaml'):
            dict_name = fname[:-5]
        else:
            dict_name = fname
        try:
            content = f"  - cn_dicts/{dict_name}"
            api.edit_file("rime_ice.dict.yaml", dict_line, content, "insert")
            logger.info(f"已添加 {content} 到 rime_ice.dict.yaml 第{dict_line}行")
            dict_line += 1
        except Exception as e:
            logger.warning(f"添加到 rime_ice.dict.yaml 失败: {e}")


def show_interactive_menu(config, api):
    while True:
        print("\n" + "=" * 50)
        print("Rime 客户端 - 交互式菜单")
        print("=" * 50)

        device_name = config.device_name
        config_dir = config.rime_config_dir
        server_url = config.server_url

        print(f"当前设备: {device_name}")
        print(f"服务器: {server_url}")
        print(f"Rime 配置目录: {config_dir}")

        print("\n检查服务器连接...")
        if api.check_connection():
            print("✓ 服务器连接正常")
        else:
            print("✗ 服务器连接失败")
            print("请确认客户端与服务器在同一局域网内，且服务器已启动")

        print("\n请选择操作:")
        print(" 1. 请求服务器更新 rime-ice 仓库")
        print(" 2. 执行自定义词库脚本")
        print(" 3. 同步用户输入词库 (增量)")
        print(" 4. 同步配置 (cn_dicts/en_dicts/lua/opencc)")
        print(" 5. 编辑配置文件")
        print(" 6. 完整同步 (下载/上传)")
        print(" 7. 查看同步状态")
        print(" 8. 获取设备列表")
        print(" 9. 健康检查")
        print(" 10. 修改配置")
        print(" 11. 退出")

        try:
            choice = input("\n选择 [1-11]: ").strip()

            if choice == "1":
                force = input("强制更新? (y/N): ").strip().lower() == 'y'
                result = api.update_rime_ice(force)
                data = result.get("data", {})
                if data.get("upgraded"):
                    logger.info(f"rime-ice已更新: {data.get('message', '成功')}")
                    changed_files = data.get('changed_files', [])
                    if changed_files:
                        logger.info(f"变更文件: {', '.join(changed_files)}")
                    api.copy_rime_ice_to_runtime()
                else:
                    logger.info(f"rime-ice已是最新: {data.get('message', '无更新')}")

            elif choice == "2":
                print("\n执行自定义词库脚本:")
                print("  1. 列出可用脚本")
                print("  2. 执行单个脚本")
                print("  3. 执行全部脚本 (更新所有)")
                sub_choice = input("选择 [1-3]: ").strip()

                if sub_choice == "1":
                    result = api.list_scripts()
                    data = result.get("data", {})
                    scripts = data.get("scripts", [])
                    if scripts:
                        print(f"\n可用脚本 ({len(scripts)} 个):")
                        for s in scripts:
                            print(f"  - {s}")
                    else:
                        print("\n暂无可执行脚本")

                elif sub_choice == "2":
                    result = api.list_scripts()
                    data = result.get("data", {})
                    available = data.get("scripts", [])

                    if not available:
                        logger.warning("暂无可执行脚本")
                        continue

                    print(f"\n可用脚本: {', '.join(available)}")
                    script_name = input("脚本名称: ").strip()

                    if not script_name:
                        print("未输入脚本名称")
                        continue

                    version = input("词库版本: ").strip()
                    if not version:
                        print("未输入版本")
                        continue

                    add_to_dict = input("自动添加到rime_ice.dict.yaml? (Y/n): ").strip().lower() != 'n'
                    dict_line = 18
                    if add_to_dict:
                        line_input = input(f"插入行号 (默认{dict_line}): ").strip()
                        if line_input:
                            try:
                                dict_line = int(line_input)
                            except ValueError:
                                print("无效行号，使用默认值18")
                                dict_line = 18

                    result = api.run_script(script_name, version)
                    data = result.get("data", {})
                    output_files = data.get('output_files', [])
                    total_size = data.get('total_size', 0)
                    if output_files:
                        logger.info(f"脚本执行成功: {', '.join(output_files)}")
                    else:
                        logger.info("脚本执行成功: 未知文件")
                    logger.info(f"生成大小: {total_size} 字节")

                    if add_to_dict and result.get("success"):
                        _auto_add_to_dict(api, output_files, dict_line)

                elif sub_choice == "3":
                    result = api.list_scripts()
                    data = result.get("data", {})
                    scripts = data.get("scripts", [])

                    if not scripts:
                        logger.warning("暂无可执行脚本")
                        continue

                    print(f"\n将执行 {len(scripts)} 个脚本: {', '.join(scripts)}")
                    version = input("词库版本: ").strip()
                    if not version:
                        print("未输入版本")
                        continue

                    add_to_dict = input("自动添加到rime_ice.dict.yaml? (Y/n): ").strip().lower() != 'n'
                    dict_line = 18
                    if add_to_dict:
                        line_input = input(f"插入行号 (默认{dict_line}): ").strip()
                        if line_input:
                            try:
                                dict_line = int(line_input)
                            except ValueError:
                                print("无效行号，使用默认值18")

                    success_count = 0
                    fail_count = 0
                    for s in scripts:
                        try:
                            logger.info(f"执行: {s}")
                            result = api.run_script(s, version)
                            data = result.get("data", {})
                            output_files = data.get('output_files', [])
                            if output_files:
                                logger.info(f"  {s}: {', '.join(output_files)}")
                            else:
                                logger.info(f"  {s}: 完成")

                            if add_to_dict and result.get("success"):
                                _auto_add_to_dict(api, output_files, dict_line)

                            success_count += 1
                        except Exception as e:
                            logger.warning(f"  {s} 失败: {e}")
                            fail_count += 1

                    logger.info(f"全部脚本执行完成: {success_count} 成功, {fail_count} 失败")

            elif choice == "3":
                print("\n同步用户输入词库 (增量):")
                print("  1. 上传 (仅变更文件)")
                print("  2. 下载 (仅变更文件)")
                sub_choice = input("选择 [1-2] (默认 1): ").strip() or "1"
                if sub_choice == "1":
                    sync.sync_userdb(config, api, "upload")
                elif sub_choice == "2":
                    result = api.get_sync_info(device=config.device_name)
                    data = result.get("data", {})
                    remote_files = data.get("files", [])
                    names = [f.get("name", "") for f in remote_files]
                    if names:
                        print(f"\n服务端文件 ({len(names)} 个):")
                        for n in names:
                            print(f"  - {n}")
                    filename = input("\n文件名 (可选，留空下载全部变更): ").strip() or None
                    sync.sync_userdb(config, api, "download", filename)

            elif choice == "4":
                print("\n同步配置:")
                print("  1. 中文词库 (cn_dicts)")
                print("  2. 英文词库 (en_dicts)")
                print("  3. Lua 脚本 (lua)")
                print("  4. OpenCC 转换 (opencc)")
                print("  5. 全部 (推荐)")
                sub_choice = input("选择 [1-5] (默认 5): ").strip() or "5"
                category_map = {"1": "cn", "2": "en", "3": "lua", "4": "opencc", "5": None}
                category = category_map.get(sub_choice)
                dicts.sync_dicts(config, api, category)

            elif choice == "5":
                path = input("文件路径: ").strip()
                line = int(input("行号: ").strip())
                content = input("内容: ").strip()
                result = api.edit_file(path, line, content)
                logger.info(f"文件编辑成功: {result.get('data', {})}")

            elif choice == "6":
                print("\n完整同步:")
                print("  1. 下载 (从服务器获取)")
                print("  2. 上传 (初始化服务器)")
                sub_choice = input("选择 [1-2]: ").strip()
                if sub_choice == "1":
                    exclude = input("额外排除的文件（逗号分隔，可选）: ").strip() or None
                    since = input("时间戳（可选）: ").strip() or None
                    fullsync.download_full_sync(config, api, exclude, since)
                elif sub_choice == "2":
                    file_path = input("tar文件路径: ").strip()
                    overwrite = input("覆盖服务器配置? (y/N): ").strip().lower() == 'y'
                    result = fullsync.upload_full_sync(config, api, file_path, overwrite)
                    logger.info(f"完整配置包上传成功: {result.get('data', {})}")

            elif choice == "7":
                result = api.get_sync_info()
                data = result.get("data", {})
                devices = data.get("devices", [])
                if devices:
                    for dev in devices:
                        name = dev.get('name', '未知')
                        files = dev.get('files', [])
                        logger.info(f"设备: {name}")
                        logger.info(f"  文件数: {len(files)}")
                        total_size = sum(f.get("size", 0) for f in files)
                        logger.info(f"  总大小: {total_size} 字节")
                        logger.info(f"  最后同步: {dev.get('timestamp', '未知')}")
                else:
                    logger.info("暂无同步数据")

            elif choice == "8":
                result = api.get_device_list()
                data = result.get("data", {})
                devices = data.get("devices", [])
                logger.info(f"发现 {len(devices)} 个设备:")
                for device in devices:
                    if isinstance(device, str):
                        logger.info(f"  设备: {device}")
                        logger.info(f"    详细信息: 使用 sync-info 命令查看详情")
                    elif isinstance(device, dict):
                        logger.info(f"  设备: {device.get('name', '未知')}")
                        logger.info(f"    最后同步: {device.get('last_sync', '未知')}")
                        logger.info(f"    文件数: {device.get('total_files', 0)}")
                        logger.info(f"    总大小: {device.get('total_size', 0)} 字节")
                    else:
                        logger.info(f"  设备: {device} (未知格式)")

            elif choice == "9":
                result = api.check_health()
                if result.get("success"):
                    data = result.get("data", {})
                    disk = data.get("disk", {})
                    mem = data.get("memory", {})
                    logger.info(f"磁盘: {disk.get('percent', '?')}% ({disk.get('free_gb', '?')}GB 可用)")
                    logger.info(f"内存: {mem.get('percent', '?')}% ({mem.get('available_mb', '?')}MB 可用)")
                else:
                    logger.warning("/api/health端点可能未实现，尝试使用/status...")
                    result = api.get_status()
                    data = result.get("data", {})
                    logger.info(f"服务器版本: {data.get('version', '未知')}")

            elif choice == "10":
                print("\n修改配置:")
                print("  1. 查看当前配置")
                print("  2. 修改服务器URL")
                print("  3. 修改Rime配置目录")
                sub_choice = input("选择 [1-3]: ").strip()
                if sub_choice == "1":
                    print(json.dumps(config.config, indent=2, ensure_ascii=False))
                elif sub_choice == "2":
                    new_url = input(f"新服务器URL (当前: {config.server_url}): ").strip()
                    if new_url:
                        config.config['server']['url'] = new_url
                        config.save()
                elif sub_choice == "3":
                    new_dir = input(f"新Rime配置目录 (当前: {config.rime_config_dir}): ").strip()
                    if new_dir:
                        config.config['rime']['config_dir'] = new_dir
                        config.save()

            elif choice == "11":
                print("再见！")
                break
            else:
                print("无效选择")

            input("\n按 Enter 键继续...")

        except KeyboardInterrupt:
            print("\n\n操作已取消")
            break
        except ClientError as e:
            print(f"\n错误: {e}")
            logger.error(str(e))
            input("按 Enter 键返回菜单...")
        except Exception as e:
            print(f"\n错误: {e}")
            logger.error(str(e))
            input("按 Enter 键返回菜单...")


def _dispatch_command(args, config, api):
    command = args.command

    if command == "status":
        result = api.get_status()
        data = result.get("data", {})
        logger.info(f"服务器版本: {data.get('version', '未知')}")
        logger.info(f"rime-ice版本: {data.get('rime_ice_version', '未知')}")
        logger.info(f"运行时间: {data.get('uptime', '未知')}")
        logger.info(f"存储使用: {data.get('storage_usage', '未知')}")
        return data

    elif command == "update-rime-ice":
        result = api.update_rime_ice(args.force)
        data = result.get("data", {})
        if data.get("upgraded"):
            logger.info(f"rime-ice已更新: {data.get('message', '成功')}")
            changed_files = data.get('changed_files', [])
            if changed_files:
                logger.info(f"变更文件: {', '.join(changed_files)}")
            api.copy_rime_ice_to_runtime()
        else:
            logger.info(f"rime-ice已是最新: {data.get('message', '无更新')}")
        return data

    elif command == "run-script":
        extra_params = json.loads(args.extra) if args.extra else None
        result = api.run_script(args.script_name, args.version, extra_params)
        data = result.get("data", {})
        output_files = data.get('output_files', [])
        total_size = data.get('total_size', 0)
        if output_files:
            logger.info(f"脚本执行成功: {', '.join(output_files)}")
        else:
            logger.info("脚本执行成功: 未知文件")
        logger.info(f"生成大小: {total_size} 字节")

        if not getattr(args, 'no_add_to_dict', False) and result.get("success"):
            _auto_add_to_dict(api, output_files, getattr(args, 'dict_line', 18))

        return data

    elif command == "list-scripts":
        result = api.list_scripts()
        data = result.get("data", {})
        scripts = data.get("scripts", [])
        if scripts:
            for s in scripts:
                print(s)
        else:
            print("(无可用脚本)")
        return data

    elif command == "run-all-scripts":
        result = api.list_scripts()
        data = result.get("data", {})
        scripts = data.get("scripts", [])

        if not scripts:
            logger.warning("暂无可执行脚本")
            return {"scripts": 0}

        logger.info(f"将执行 {len(scripts)} 个脚本: {', '.join(scripts)}")

        dict_line = getattr(args, 'dict_line', 18)
        no_add = getattr(args, 'no_add_to_dict', False)

        success_count = 0
        fail_count = 0
        for s in scripts:
            try:
                logger.info(f"执行: {s}")
                result = api.run_script(s, args.version)
                data = result.get("data", {})
                output_files = data.get('output_files', [])
                if output_files:
                    logger.info(f"  {s}: {', '.join(output_files)}")
                else:
                    logger.info(f"  {s}: 完成")

                if not no_add and result.get("success"):
                    _auto_add_to_dict(api, output_files, dict_line)

                success_count += 1
            except Exception as e:
                logger.warning(f"  {s} 失败: {e}")
                fail_count += 1

        logger.info(f"全部脚本执行完成: {success_count} 成功, {fail_count} 失败")
        return {"success": success_count, "failed": fail_count}

    elif command == "edit-file":
        result = api.edit_file(args.path, args.line, args.content, args.action)
        logger.info(f"文件编辑成功: {result.get('data', {})}")
        return result

    elif command == "upload-config":
        device = args.device or config.device_name
        return api.upload_config(args.file, device, args.overwrite)

    elif command == "sync-userdb":
        return sync.sync_userdb(config, api, args.action, args.file)

    elif command == "sync-upload-tar":
        return sync.upload_sync_tar(config, api, args.device)

    elif command == "sync-upload-file":
        return sync.upload_sync_file(config, api, args.file, args.filename, args.device)

    elif command == "sync-info":
        result = api.get_sync_info(args.device, args.since)
        data = result.get("data", {})
        devices = data.get("devices", [])
        if devices:
            for dev in devices:
                name = dev.get('name', '未知')
                files = dev.get('files', [])
                logger.info(f"设备: {name}")
                logger.info(f"  文件数: {len(files)}")
                total_size = sum(f.get("size", 0) for f in files)
                logger.info(f"  总大小: {total_size} 字节")
                logger.info(f"  最后同步: {dev.get('timestamp', '未知')}")
        else:
            files = data.get("files", [])
            if files:
                logger.info(f"文件数: {len(files)}")
                total_size = sum(f.get("size", 0) for f in files)
                logger.info(f"总大小: {total_size} 字节")
                logger.info(f"时间戳: {data.get('timestamp', '未知')}")
        return data

    elif command == "sync-download-tar":
        return sync.download_sync_tar(config, api, args.device, args.since)

    elif command == "sync-download-file":
        return sync.download_sync_file(config, api, args.filename, args.device)

    elif command == "sync-dict":
        return dicts.sync_dicts(config, api, args.category)

    elif command == "dict-info":
        result = api.get_dict_info(args.category, args.since)
        data = result.get("data", {})
        categories = data.get("categories", {})
        for cat, files in categories.items():
            logger.info(f"词库类别: {cat}")
            logger.info(f"  文件数: {len(files)}")
            total_size = sum(f.get("size", 0) for f in files)
            logger.info(f"  总大小: {total_size} 字节")
            for i, file_info in enumerate(files[:5]):
                logger.info(f"    文件{i+1}: {file_info.get('path')} ({file_info.get('size', 0)} 字节)")
            if len(files) > 5:
                logger.info(f"    ... 还有 {len(files) - 5} 个文件")
        logger.info(f"所有词库总大小: {data.get('total_size', 0)} 字节")
        logger.info(f"时间戳: {data.get('timestamp', '未知')}")
        return data

    elif command == "dict-download-tar":
        return dicts.download_dict_tar(config, api, args.category, args.since)

    elif command == "dict-download-file":
        return dicts.download_dict_file(config, api, args.filename, args.category)

    elif command == "full-sync-info":
        result = api.get_full_sync_info(args.exclude, args.since)
        data = result.get("data", {})
        files = data.get("files", [])
        logger.info(f"文件总数: {len(files)}")
        logger.info(f"总大小: {data.get('total_size', 0)} 字节")
        logger.info(f"排除的文件: {data.get('excluded', [])}")
        for i, file_info in enumerate(files[:10]):
            logger.info(f"  文件{i+1}: {file_info.get('path')} ({file_info.get('size', 0)} 字节)")
        if len(files) > 10:
            logger.info(f"  ... 还有 {len(files) - 10} 个文件")
        return data

    elif command == "full-sync-download":
        return fullsync.download_full_sync(config, api, args.exclude, args.since)

    elif command == "full-sync-upload":
        return fullsync.upload_full_sync(config, api, args.file, args.overwrite)

    elif command == "device-list":
        result = api.get_device_list()
        data = result.get("data", {})
        devices = data.get("devices", [])
        logger.info(f"发现 {len(devices)} 个设备:")
        for device in devices:
            if isinstance(device, str):
                logger.info(f"  设备: {device}")
                logger.info(f"    详细信息: 使用 sync-info 命令查看详情")
            elif isinstance(device, dict):
                logger.info(f"  设备: {device.get('name', '未知')}")
                logger.info(f"    最后同步: {device.get('last_sync', '未知')}")
                logger.info(f"    文件数: {device.get('total_files', 0)}")
                logger.info(f"    总大小: {device.get('total_size', 0)} 字节")
            else:
                logger.info(f"  设备: {device} (未知格式)")
        return data

    elif command == "health":
        result = api.check_health()
        if result.get("success"):
            data = result.get("data", {})
            disk = data.get("disk", {})
            mem = data.get("memory", {})
            logger.info(f"磁盘: {disk.get('percent', '?')}% ({disk.get('free_gb', '?')}GB 可用)")
            logger.info(f"内存: {mem.get('percent', '?')}% ({mem.get('available_mb', '?')}MB 可用)")
        else:
            logger.warning("/api/health端点可能未实现，尝试使用/status...")
            result = api.get_status()
            data = result.get("data", {})
            logger.info(f"服务器版本: {data.get('version', '未知')}")
        return result

    elif command == "interactive":
        show_interactive_menu(config, api)

    else:
        raise ValueError(f"未知命令: {command}")


def main():
    _setup_basic_logging()

    parser = build_parser()
    args = parser.parse_args()

    try:
        config = ConfigManager(Path(args.config))
        setup_logging(config)
        api = APIClient(config)
    except ConfigError as e:
        logger.error(str(e))
        sys.exit(1)

    if not args.command:
        if sys.stdin.isatty() and sys.stdout.isatty():
            show_interactive_menu(config, api)
        else:
            parser.print_help()
            sys.exit(1)
    else:
        try:
            _dispatch_command(args, config, api)
        except ClientError as e:
            logger.error(str(e))
            sys.exit(1)
        except Exception as e:
            logger.error(f"执行失败: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
