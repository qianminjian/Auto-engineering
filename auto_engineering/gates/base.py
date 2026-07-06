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
from typing import Any

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
    """

    gate_name: str = ""
    passed: bool = False
    message: str = ""

    # 注: passed 字段与 GateVerdict.passed() 类方法同名是 dataclass 不可避免的副作用,
    # 通过 @classmethod 访问避免歧义. 字段访问走 v.passed, 方法访问走 GateVerdict.passed().
    @classmethod
    def passed(cls, msg: str = "", gate_name: str = "") -> GateVerdict:  # noqa: F811
        """构造一个通过的 GateVerdict."""
        return cls(gate_name=gate_name, passed=True, message=msg)

    @classmethod
    def failed(cls, msg: str, gate_name: str = "") -> GateVerdict:
        """构造一个失败的 GateVerdict."""
        return cls(gate_name=gate_name, passed=False, message=msg)


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

    子类必须实现 run(project_root) 方法, 返回 Verdict.
    默认实现: 检查项目根存在 → 委托子类.

    旧接口 Gate.check(stage, context) 保留供 v2.0 Guardrail 体系使用.

    v5.0 §B2.9 扩展:
        - 类属性 applies_to_stages: tuple[str, ...] — 标识该 Gate 在哪些
          Stage 阶段运行 (architect/developer/critic). 默认 = 三阶段全跑.
        - run() 新增 contracts: dict | None = None 参数 — 供 ContractGate
          等需要契约数据的 Gate 使用 (向后兼容: 默认 None).
    """

    name: str = "base"
    # v5.0 §B2.9: 默认覆盖三阶段, 子类按需覆盖 (如 CoverageGate 仅 developer)
    applies_to_stages: tuple[str, ...] = ("architect", "developer", "critic")

    def run(
        self,
        project_root: Path,
        contracts: dict | None = None,
    ) -> GateVerdict:
        """执行 Gate 检查.

        Args:
            project_root: 项目根目录路径
            contracts: v5.0 §B2.9 — 可选契约字典 (供 ContractGate 等使用)

        Returns:
            GateVerdict (passed + message)

        Raises:
            NotImplementedError: 子类未实现时
        """
        raise NotImplementedError(
            f"{type(self).__name__}.run() must be implemented by subclass"
        )

# v5.4: DEFAULT_GATES / _build_default_gates / build_gates_from_manifest
# 已提取到 auto_engineering.gates.registry, 消除 base ↔ build 导入循环.
# 消费者请用: from auto_engineering.gates.registry import DEFAULT_GATES