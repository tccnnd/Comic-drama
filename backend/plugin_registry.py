"""通用插件注册框架（P3.3，E5 收敛范围）。

承诺范围（初版）：
- 显式注册：register() 校验插件 id 唯一 + api_version 主版本匹配
- 版本校验：插件声明目标 API 版本，主版本不一致则拒绝注册
- 错误边界：invoke() 捕获插件抛出的任何异常，记录 WARNING 并返回 None
- 禁用插件：disable()/enable()/is_disabled()，被禁用的插件 get/invoke 返回 None

不承诺（E5 明确排除）：
- 热加载（运行时动态 import/reload）
- 安全隔离（插件在宿主进程内执行；若需隔离须独立进程 + IPC + 超时设计，另立项）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from backend.logger import get_logger

logger = get_logger(__name__)

# 框架当前 API 主版本。插件声明的 api_version 主版本必须与此一致。
API_VERSION = "1"


class PluginVersionError(ValueError):
    """插件 api_version 与框架不兼容，或 id 冲突。"""


@dataclass
class PluginSpec:
    """插件声明契约。

    - id: 唯一标识（重复注册抛 PluginVersionError）
    - api_version: 目标框架 API 主版本（如 "1" 或 "1.x"），主版本必须匹配 API_VERSION
    - version: 插件自身版本（展示用，不参与兼容性判断）
    - callable: 插件入口（可调用对象）
    - metadata: 可选元数据（作者、描述等）
    """

    id: str
    api_version: str
    version: str
    callable: Callable[..., Any]
    metadata: dict[str, Any] = field(default_factory=dict)


def _major(version: str) -> str:
    """提取语义化版本主版本号；无法解析时原样返回。"""
    return version.split(".", 1)[0].strip() if version else ""


class PluginRegistry:
    """插件注册表：注册 / 查询 / 调用 / 禁用。"""

    def __init__(self, api_version: str = API_VERSION) -> None:
        self.api_version = api_version
        self._major = _major(api_version)
        self._plugins: dict[str, PluginSpec] = {}
        self._disabled: set[str] = set()

    def register(self, spec: PluginSpec) -> PluginSpec:
        """显式注册插件；id 重复或 api_version 主版本不匹配则抛 PluginVersionError。"""
        if not spec.id:
            raise PluginVersionError("plugin id must not be empty")
        if spec.id in self._plugins:
            raise PluginVersionError(f"plugin id already registered: {spec.id}")
        if _major(spec.api_version) != self._major:
            raise PluginVersionError(
                f"plugin {spec.id} api_version {spec.api_version!r} "
                f"incompatible with registry {self.api_version!r}"
            )
        self._plugins[spec.id] = spec
        logger.info("registered plugin %s v%s", spec.id, spec.version)
        return spec

    def disable(self, plugin_id: str) -> None:
        self._disabled.add(plugin_id)
        logger.info("disabled plugin %s", plugin_id)

    def enable(self, plugin_id: str) -> None:
        self._disabled.discard(plugin_id)
        logger.info("enabled plugin %s", plugin_id)

    def is_disabled(self, plugin_id: str) -> bool:
        return plugin_id in self._disabled

    def get(self, plugin_id: str) -> PluginSpec | None:
        """返回插件 spec；未注册或被禁用返回 None。"""
        spec = self._plugins.get(plugin_id)
        if spec is None:
            return None
        if plugin_id in self._disabled:
            logger.warning("plugin %s is disabled, ignoring", plugin_id)
            return None
        return spec

    def list(self, include_disabled: bool = False) -> list[PluginSpec]:
        specs = list(self._plugins.values())
        if include_disabled:
            return specs
        return [s for s in specs if s.id not in self._disabled]

    def invoke(self, plugin_id: str, *args: Any, **kwargs: Any) -> Any:
        """调用插件并施加错误边界。

        未注册/被禁用返回 None；插件抛异常则记录 WARNING 并返回 None，
        绝不让插件异常穿透到宿主调用方。
        """
        spec = self.get(plugin_id)
        if spec is None:
            return None
        try:
            return spec.callable(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 错误边界：插件异常不外溢
            logger.warning("plugin %s raised %s: %s", plugin_id, type(exc).__name__, exc)
            return None
