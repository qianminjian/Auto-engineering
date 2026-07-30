"""v2.0 Phase 04 — Gate 基类 + GateVerdict dataclass.

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 + §4.8 关键数据结构.

核心要点:
    - Gate 基类: 实现 run() 接口, 入参 project_root, 返回 GateVerdict
    - GateVerdict: 数据类, 携带 passed / message / gate_name
    - 6 道 Gate: safety / lint / type_check / contract / test / build
    - 单 Gate 失败不抛异常, 返回 passed=False + message (上层决定 block / retry)

向后兼容:
    - GateResult 保留供向后兼容 (v6.0 删除)
"""

from __future__ import annotations

import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_engineering.config.runtime_config import RuntimeConfig

# ============================================================
# GateVerdict (v5.0 §B6.1 — Verdict → GateVerdict 重命名)
# ============================================================


@dataclass
class GateVerdict:
    """Gate 检查结果 (v5.0 §B6.1 重命名自 Verdict).

    Attributes:
        gate_name: Gate 名称(由 Gate 实例填入, 调用方无需传)
        passed: True = 通过, False = 失败
        message: 失败/通过的详细信息(便于排查)
        details: v5.5 扩展 — 结构化详情 (如 DeepAuditGate 的 findings 摘要)
        suggestions: v5.5 扩展 — 修复建议列表
    """

    gate_name: str = ""
    passed: bool = False
    message: str = ""
    details: dict | None = None
    suggestions: list[str] | None = None
    # P0 修复 (2026-07-26 真跑): 区分「跳过」与「通过」。旧版 gate 工具缺失/无测试时
    # 返回 ok（passed=True）报 ✓，使 skip 被误当通过（test/lint/type_check 对 TS 项目
    # 大面积静默 skip 却报 ✓）。skipped=True 表示未真正执行（不阻断，但区别于真通过）。
    skipped: bool = False
    # 仅用于系统可证明当前 Gate 不适用的场景。not_applicable 不等于通过，
    # runner 对外序列化为 passed=null，且不计入通过或失败。
    not_applicable: bool = False

    # 注: passed 布尔字段与 GateVerdict.ok() 类方法不冲突.
    # 字段访问走 v.passed (bool), 工厂方法走 GateVerdict.ok().
    @classmethod
    def ok(
        cls, msg: str = "", gate_name: str = "",
        details: dict | None = None, suggestions: list[str] | None = None,
    ) -> GateVerdict:
        """构造一个通过的 GateVerdict."""
        return cls(gate_name=gate_name, passed=True, message=msg,
                   details=details, suggestions=suggestions)

    @classmethod
    def failed(
        cls, msg: str, gate_name: str = "",
        details: dict | None = None, suggestions: list[str] | None = None,
    ) -> GateVerdict:
        """构造一个失败的 GateVerdict."""
        return cls(gate_name=gate_name, passed=False, message=msg,
                   details=details, suggestions=suggestions)

    @classmethod
    def skip(
        cls, msg: str, gate_name: str = "",
        details: dict | None = None, suggestions: list[str] | None = None,
    ) -> GateVerdict:
        """构造一个跳过的 GateVerdict（未真正执行，不阻断，区别于通过）."""
        return cls(gate_name=gate_name, passed=True, skipped=True, message=msg,
                   details=details, suggestions=suggestions)

    @classmethod
    def not_applicable_verdict(
        cls, msg: str, gate_name: str = "",
        details: dict | None = None, suggestions: list[str] | None = None,
    ) -> GateVerdict:
        """构造机器可证明不适用的 GateVerdict。"""
        return cls(
            gate_name=gate_name,
            passed=False,
            skipped=True,
            not_applicable=True,
            message=msg,
            details=details,
            suggestions=suggestions,
        )


# v5.4 P2-2: Verdict 别名保留向后兼容, 通过 __getattr__ 触发 DeprecationWarning.
# 新代码应使用 GateVerdict. v6.0 将移除 Verdict 别名.


def __getattr__(name: str) -> object:
    if name == "Verdict":
        warnings.warn(
            "Verdict 是 GateVerdict 的废弃别名, 将在 v6.0 移除. 请使用 GateVerdict.",
            DeprecationWarning,
            stacklevel=2,
        )
        return GateVerdict
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Gate", "GateVerdict", "SubprocessResult", "run_gate_command"]


# ============================================================
# Subprocess helper (v5.4 P2-18 — 跨 Gate 提取公共 subprocess.run 模式)
# ============================================================


@dataclass
class SubprocessResult:
    """subprocess.run 的标准化结果.

    Attributes:
        returncode: 进程退出码. -1 表示 timed_out 或 not_found.
        stdout: 标准输出
        stderr: 标准错误
        timed_out: 是否超时
        not_found: 命令是否未找到
    """

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    not_found: bool = False


def run_gate_command(cmd: list[str], cwd: Path, timeout: float) -> SubprocessResult:
    """安全执行 subprocess 命令, 捕获常见错误.

    各 Gate 子类调用此函数替代裸 subprocess.run, 按各自策略处理
    timed_out / not_found / returncode != 0 等结果.
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return SubprocessResult(
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )
    except subprocess.TimeoutExpired:
        return SubprocessResult(returncode=-1, stdout="", stderr="", timed_out=True)
    except FileNotFoundError:
        return SubprocessResult(returncode=-1, stdout="", stderr="", not_found=True)


class Gate:
    """Gate 基类(v2.0 Phase 04 新接口).

    子类必须实现 run(project_root) 方法, 返回 GateVerdict.
    默认实现: 检查项目根存在 → 委托子类.

    旧接口 Gate.check(stage, context) 保留供 v2.0 Guardrail 体系使用.

    v5.5 audit P1-9: contracts 从 run() 签名移除, 改为实例属性.
          仅 ContractGate 需要 contracts, 其他 6 个 Gate 不再有冗余参数.
        - v5.5 audit P2-15: _register_alias 统一向后兼容别名模式.
    """

    name: str = "base"
    # v5.5 audit P1-9: contracts 实例属性 (仅 ContractGate 使用, 其他 Gate 忽略)
    contracts: dict | None = None
    # _resolve_timeout / _validate_project_root 是 protected 方法 (Python 约定: _ 前缀 = 子类可访问).
    # 被 6+ 个 Gate 子类跨模块调用 — 这是基类→子类的标准 OOP 模式, 不是封装破坏.
    @staticmethod
    def _resolve_timeout(default: float, config: RuntimeConfig | None = None) -> float:
        """从 AE_GATE_TIMEOUT 读取 timeout, 未设置则用 default.

        P1-10: 支持 RuntimeConfig 注入, 未注入时降级到 get_default_config().
        """
        from auto_engineering.config.runtime_config import get_default_config
        cfg = config if config is not None else get_default_config()
        val = cfg.gate_timeout
        return float(val) if val is not None else default

    @classmethod
    def _register_alias(cls, old_name: str, new_name: str) -> None:
        """注册废弃别名 property, 访问时触发 DeprecationWarning.

        Usage (at module level after class definition):
            LintGate._register_alias("ruff_bin", "linter_bin")
        """
        import warnings

        def _getter(self: Gate) -> object:
            warnings.warn(
                f"{cls.__name__}.{old_name} is deprecated, use .{new_name} instead",
                DeprecationWarning,
                stacklevel=2,
            )
            return getattr(self, new_name)

        setattr(cls, old_name, property(_getter))

    def run(
        self,
        project_root: Path,
    ) -> GateVerdict:
        """执行 Gate 检查.

        Args:
            project_root: 项目根目录路径

        Returns:
            GateVerdict (passed + message)

        Raises:
            NotImplementedError: 子类未实现时
        """
        raise NotImplementedError(
            f"{type(self).__name__}.run(project_root: Path) -> GateVerdict 必须由子类实现.\n"
            f"参考实现: 覆写 run(), 调用 self._validate_project_root(project_root) 验证项目路径, "
            f"然后执行 Gate 特定检查逻辑."
        )

    @classmethod
    def from_manifest(
        cls,
        manifest: dict,
        timeout: float | None = None,
        **extra_kwargs: object,
    ) -> Gate:
        """从 init-manifest.json 构造 Gate 实例。

        默认实现从 manifest 提取工具配置并通过 _MANIFEST_TOOL_KEY /
        _TOOL_BIN_KWARG 类属性映射到构造参数。
        子类如需支持此功能，定义以下类属性即可：
            _MANIFEST_TOOL_KEY: str — tools dict 中的键名 (如 "linter")
            _TOOL_BIN_KWARG: str   — 构造函数的参数名 (如 "linter_bin")
        """
        from auto_engineering.gates._tools import get_gate_tools_from_manifest
        tools = get_gate_tools_from_manifest(manifest)
        tool_key: str | None = getattr(cls, "_MANIFEST_TOOL_KEY", None)
        bin_kwarg: str | None = getattr(cls, "_TOOL_BIN_KWARG", None)
        if tool_key is None or bin_kwarg is None:
            raise NotImplementedError(
                f"{cls.__name__}.from_manifest() 未实现 — "
                f"该 Gate 不支持从 init-manifest.json 构造"
            )
        kwargs: dict[str, object] = {bin_kwarg: tools[tool_key]}
        if timeout is not None:
            kwargs["timeout"] = timeout
        kwargs.update(extra_kwargs)
        return cls(**kwargs)

    def _validate_project_root(self, project_root: Path) -> GateVerdict | None:
        """验证 project_root 存在且为目录 (v5.5 P1-4: 消除 5 处重复).

        Returns:
            None 表示验证通过; GateVerdict.failed 表示失败.
        """
        root = Path(project_root)
        if not root.is_dir():
            return GateVerdict.failed(
                f"project_root 不存在或非目录: {root}",
                gate_name=self.name,
            )
        return None

# v5.4: DEFAULT_GATES / _build_default_gates / build_gates_from_manifest
# 已提取到 auto_engineering.gates.registry, 消除 base ↔ build 导入循环.
# 消费者请用: from auto_engineering.gates.registry import DEFAULT_GATES
