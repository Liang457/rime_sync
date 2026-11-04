"""rime_ice 词库联动：开关、同步、imports.json 兼容、基座重建后重放。"""
import json

import pytest

from app.services import rime_ice
from app.services.store import AddItem


def _add_main(store, text):
    store.add_many([AddItem(rime_ice.MAIN_DICT, text.encode("utf-8"),
                            source="base")])


def _add_dict(store, name, source="publish"):
    store.add_many([AddItem(f"cn_dicts/{name}.dict.yaml", b"E\t1",
                            source=source)])


def _read(store):
    return store.get_path(rime_ice.MAIN_DICT).read_text("utf-8")


# ---- 同步：路径形条目 ---------------------------------------------------------


def test_managed_entries_use_cn_dicts_prefix(env):
    app, client, root = env
    store = app.extensions["store"]
    _add_main(store, "import_tables:\n  - cn_dicts/8105\n")
    _add_dict(store, "zzz")
    report = rime_ice.sync_import_tables(store)
    assert report["added"] == ["cn_dicts/zzz"] and report["changed"]
    assert "- cn_dicts/zzz" in _read(store)
    # 删除词库文件 → 引用撤掉
    store.delete("cn_dicts/zzz.dict.yaml", detail="删")
    report = rime_ice.sync_import_tables(store)
    assert report["removed"] == ["cn_dicts/zzz"]
    assert "- cn_dicts/zzz" not in _read(store)


def test_legacy_bare_entries_upgraded(env):
    """旧版写过的裸名条目（挂不住 cn_dicts 下的文件）在读取时升级。"""
    app, client, root = env
    store = app.extensions["store"]
    (root / "store" / "imports.json").write_text(
        json.dumps(["zzz"]), encoding="utf-8")     # 旧版纯列表 + 裸名
    _add_main(store, "import_tables:\n  - cn_dicts/8105\n  - zzz\n")
    _add_dict(store, "zzz")
    report = rime_ice.sync_import_tables(store)
    assert report["changed"] is True               # 归一化本身就是一次改写
    text = _read(store)
    assert "- cn_dicts/zzz" in text and "\n  - zzz\n" not in text
    state = json.loads((root / "store" / "imports.json").read_text("utf-8"))
    assert state["managed"] == ["cn_dicts/zzz"]
    assert state["disabled"] == []


# ---- 词库开关 -----------------------------------------------------------------


def test_toggle_off_and_on(env):
    app, client, root = env
    store = app.extensions["store"]
    _add_main(store, "import_tables:\n  - cn_dicts/8105\n  - cn_dicts/tencent\n"
              "  - cn_dicts/others\n")
    _add_dict(store, "zzz")
    rime_ice.sync_import_tables(store)

    # 关闭基座自带的腾讯词向量
    report = rime_ice.toggle_table(store, "cn_dicts/tencent", False)
    assert report["removed"] == ["cn_dicts/tencent"]
    assert "tencent" not in _read(store)
    state = json.loads((root / "store" / "imports.json").read_text("utf-8"))
    assert state["disabled"] == ["cn_dicts/tencent"]
    # 关闭自管词库后，后续 sync 不得把它加回来
    rime_ice.toggle_table(store, "cn_dicts/zzz", False)
    report = rime_ice.sync_import_tables(store)
    assert report["added"] == [] and report["changed"] is False
    assert "- cn_dicts/zzz" not in _read(store)

    # 启用大字表 → 紧跟 8105 之后（字表优先级靠前）
    _add_dict(store, "41448", source="base")
    report = rime_ice.toggle_table(store, "cn_dicts/41448", True)
    assert report["added"] == ["cn_dicts/41448"]
    text = _read(store)
    assert text.index("cn_dicts/41448") < text.index("cn_dicts/others")
    assert text.index("cn_dicts/8105") < text.index("cn_dicts/41448")
    state = json.loads((root / "store" / "imports.json").read_text("utf-8"))
    assert state["disabled"] == ["cn_dicts/tencent", "cn_dicts/zzz"]
    # 普通词库启用 → 追加末尾（先补上词库文件）
    _add_dict(store, "tencent", source="base")
    report = rime_ice.toggle_table(store, "cn_dicts/tencent", True)
    assert _read(store).rstrip().endswith("- cn_dicts/tencent")


def test_toggle_validates(env):
    app, client, root = env
    store = app.extensions["store"]
    _add_main(store, "import_tables:\n  - cn_dicts/8105\n")
    with pytest.raises(ValueError):
        rime_ice.toggle_table(store, "../evil", True)
    with pytest.raises(ValueError):
        rime_ice.toggle_table(store, "cn_dicts/ghost", True)   # 文件不在库
    # 关闭悬空条目允许（主词典里存在但文件没了）
    _add_main(store, "import_tables:\n  - cn_dicts/8105\n  - cn_dicts/gone\n")
    report = rime_ice.toggle_table(store, "cn_dicts/gone", False)
    assert report["removed"] == ["cn_dicts/gone"]


def test_toggle_preserves_comments(env):
    """rime-ice 真实文件：条目带行尾注释、块内含注释行——
    开关只增删条目行，注释与其余条目原样保留。"""
    app, client, root = env
    store = app.extensions["store"]
    _add_main(store, """import_tables:
  - cn_dicts/8105    # 字表
  #- cn_dicts/41448  # 大字表（按需启用）
  - cn_dicts/base    # 基础词库
  - cn_dicts/ext     # 扩展词库
  - cn_dicts/tencent # 腾讯词向量
  - cn_dicts/others  # 一些杂项
""")
    for name in ("41448", "tencent"):
        _add_dict(store, name, source="base")

    report = rime_ice.toggle_table(store, "cn_dicts/41448", True)
    text = _read(store)
    assert report["added"] == ["cn_dicts/41448"]
    # 插在 8105 行之后，原有行尾注释全部保留
    assert "  - cn_dicts/8105    # 字表\n  - cn_dicts/41448\n" in text
    assert "#- cn_dicts/41448  # 大字表（按需启用）" in text
    assert "- cn_dicts/base    # 基础词库" in text
    # 关闭腾讯词向量 → 只删那一行
    report = rime_ice.toggle_table(store, "cn_dicts/tencent", False)
    text = _read(store)
    assert report["removed"] == ["cn_dicts/tencent"]
    assert "tencent" not in text
    assert "- cn_dicts/ext     # 扩展词库" in text
    assert "- cn_dicts/41448" in text            # 刚启用的不受影响
    # 再关 41448 → 回到「注释态」
    rime_ice.toggle_table(store, "cn_dicts/41448", False)
    text = _read(store)
    assert "- cn_dicts/41448\n" not in text
    assert "#- cn_dicts/41448  # 大字表（按需启用）" in text


# ---- 行内形式（import_tables: [a, b]）------------------------------------------


def test_toggle_inline_form(env):
    """手写行内形式的开关：sync 增补、关闭、再启用都保持行内书写风格。"""
    app, client, root = env
    store = app.extensions["store"]
    _add_main(store, "import_tables: [cn_dicts/8105, cn_dicts/tencent]\n")
    _add_dict(store, "mine")
    report = rime_ice.sync_import_tables(store)
    assert report["changed"] is True
    assert "import_tables: [cn_dicts/8105, cn_dicts/tencent, cn_dicts/mine]" \
        in _read(store)

    # 关闭腾讯词向量 → 行内条目减少
    report = rime_ice.toggle_table(store, "cn_dicts/tencent", False)
    assert report["removed"] == ["cn_dicts/tencent"]
    text = _read(store)
    assert "tencent" not in text
    assert text.startswith("import_tables: [cn_dicts/8105, cn_dicts/mine]\n")
    state = json.loads((root / "store" / "imports.json").read_text("utf-8"))
    assert state["disabled"] == ["cn_dicts/tencent"]

    # 再启用（文件补回库后）→ 行内追加末尾
    _add_dict(store, "tencent", source="base")
    report = rime_ice.toggle_table(store, "cn_dicts/tencent", True)
    text = _read(store)
    assert "import_tables: [cn_dicts/8105, cn_dicts/mine, cn_dicts/tencent]" in text
    state = json.loads((root / "store" / "imports.json").read_text("utf-8"))
    assert state["disabled"] == []
    assert state["enabled"] == ["cn_dicts/tencent"]


def test_inline_form_digit_table_inserted_after_8105(env):
    """行内形式启用字表类（纯数字名）→ 紧跟 8105 之后而非追加末尾。"""
    app, client, root = env
    store = app.extensions["store"]
    _add_main(store, "import_tables: [cn_dicts/8105, cn_dicts/others]\n")
    _add_dict(store, "41448", source="base")
    report = rime_ice.toggle_table(store, "cn_dicts/41448", True)
    assert report["added"] == ["cn_dicts/41448"]
    assert "import_tables: [cn_dicts/8105, cn_dicts/41448, cn_dicts/others]" \
        in _read(store)


# ---- 裸名条目的归一化边界 ---------------------------------------------------------


def test_bare_entry_without_cn_dicts_file_kept(env):
    """根目录手挂的裸名条目（cn_dicts 下无对应文件）保持原样，不被强制升级。"""
    app, client, root = env
    store = app.extensions["store"]
    _add_main(store, "import_tables:\n  - 8105\n  - mydict\n")
    report = rime_ice.sync_import_tables(store)
    assert report["changed"] is False
    text = _read(store)
    assert "\n  - mydict\n" in text          # 条目原样保留


# ---- 基座重建后重放 -------------------------------------------------------------


def test_replay_after_base_rebuild(env):
    """基座重建把主词典打回原样 → sync 重放：自管加回、显式关闭的移除、
    显式启用（基座注释态的 41448）补回。"""
    app, client, root = env
    store = app.extensions["store"]
    _add_main(store, "import_tables:\n  - cn_dicts/8105\n  - cn_dicts/tencent\n")
    _add_dict(store, "zzz")
    _add_dict(store, "41448", source="base")
    rime_ice.sync_import_tables(store)
    rime_ice.toggle_table(store, "cn_dicts/tencent", False)
    rime_ice.toggle_table(store, "cn_dicts/41448", True)
    text = _read(store)
    assert "- cn_dicts/41448" in text and "tencent" not in text

    # 基座重建：文件打回出厂状态（41448 回到注释态、tencent 回来、zzz 没了）
    _add_main(store, "import_tables:\n  - cn_dicts/8105\n  - cn_dicts/tencent\n"
              "  - cn_dicts/others\n")
    report = rime_ice.sync_import_tables(store)
    text = _read(store)
    assert "tencent" not in text                      # 显式关闭被重放
    assert "- cn_dicts/41448" in text                 # 显式启用被补回
    assert "- cn_dicts/zzz" in text                   # 自管词库被加回
    state = json.loads((root / "store" / "imports.json").read_text("utf-8"))
    assert state["enabled"] == ["cn_dicts/41448"]
    assert state["disabled"] == ["cn_dicts/tencent"]


# ---- 开关页数据 -----------------------------------------------------------------


def test_toggle_rows_order_and_flags(env):
    app, client, root = env
    store = app.extensions["store"]
    _add_main(store, "import_tables:\n  - cn_dicts/8105\n  - cn_dicts/tencent\n"
              "  - cn_dicts/gone\n")     # gone：悬空条目
    _add_dict(store, "mine", source="upload")
    rime_ice.sync_import_tables(store)     # mine 登记进 import_tables
    rime_ice.toggle_table(store, "cn_dicts/others", False)  # 显式关闭
    _add_dict(store, "others", source="base")

    rows = {r["table"]: r for r in rime_ice.toggle_rows(store)}
    assert rows["cn_dicts/8105"]["enabled"] is True
    assert rows["cn_dicts/8105"]["label"]                  # 基座词库带展示名
    assert rows["cn_dicts/tencent"]["enabled"] is True
    assert rows["cn_dicts/gone"]["enabled"] is True
    assert rows["cn_dicts/gone"]["dangling"] is True
    assert rows["cn_dicts/others"]["enabled"] is False
    assert rows["cn_dicts/mine"]["enabled"] is True
    order = [r["table"] for r in rime_ice.toggle_rows(store)]
    assert order.index("cn_dicts/8105") < order.index("cn_dicts/tencent")
