"""backend/plugin_registry 通用插件注册框架测试（P3.3）。"""

from __future__ import annotations

import pytest

from backend.plugin_registry import PluginRegistry, PluginSpec, PluginVersionError


def _spec(plugin_id="p1", api_version="1", version="0.1.0", callable=None, **meta):
    if callable is None:
        callable = lambda *a, **k: ("ok", a, k)  # noqa: E731
    return PluginSpec(
        id=plugin_id,
        api_version=api_version,
        version=version,
        callable=callable,
        metadata=meta,
    )


def test_register_and_get_roundtrip():
    reg = PluginRegistry()
    spec = _spec()
    reg.register(spec)
    assert reg.get("p1") is spec
    assert reg.list() == [spec]


def test_register_duplicate_id_rejected():
    reg = PluginRegistry()
    reg.register(_spec(plugin_id="dup"))
    with pytest.raises(PluginVersionError):
        reg.register(_spec(plugin_id="dup"))


def test_register_incompatible_api_version_rejected():
    reg = PluginRegistry(api_version="1")
    with pytest.raises(PluginVersionError):
        reg.register(_spec(plugin_id="bad", api_version="2"))


def test_register_matching_major_with_minor_ok():
    """api_version 主版本一致（如 "1.5"）应通过。"""
    reg = PluginRegistry(api_version="1")
    spec = _spec(plugin_id="p_minor", api_version="1.5")
    reg.register(spec)
    assert reg.get("p_minor") is spec


def test_disable_hides_from_get_and_list():
    reg = PluginRegistry()
    reg.register(_spec(plugin_id="p1"))
    reg.disable("p1")
    assert reg.is_disabled("p1")
    assert reg.get("p1") is None
    assert reg.list() == []
    # include_disabled 可见
    assert [s.id for s in reg.list(include_disabled=True)] == ["p1"]
    reg.enable("p1")
    assert reg.get("p1") is not None


def test_invoke_calls_plugin():
    reg = PluginRegistry()
    reg.register(_spec(plugin_id="add", callable=lambda x: x + 1))
    assert reg.invoke("add", 1) == 2


def test_invoke_missing_or_disabled_returns_none():
    reg = PluginRegistry()
    assert reg.invoke("nope") is None
    reg.register(_spec(plugin_id="p1"))
    reg.disable("p1")
    assert reg.invoke("p1", 1) is None


def test_invoke_error_boundary_contains_exception():
    """插件抛异常不穿透：返回 None，宿主不受影响。"""

    def boom(*_a, **_k):
        raise RuntimeError("plugin exploded")

    reg = PluginRegistry()
    reg.register(_spec(plugin_id="boom", callable=boom))
    assert reg.invoke("boom") is None
    # 其它插件仍可正常调用（错误隔离）
    reg.register(_spec(plugin_id="ok", callable=lambda: 42))
    assert reg.invoke("ok") == 42


def test_empty_id_rejected():
    reg = PluginRegistry()
    with pytest.raises(PluginVersionError):
        reg.register(_spec(plugin_id=""))
