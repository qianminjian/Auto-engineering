"""共享 metrics 路径工厂 (P1-10).

消除 ratchet.py 和 collector.py 中独立的 _metrics_dir 路径计算重复。
"""

from pathlib import Path


def get_metrics_dir(project_root: Path) -> Path:
    """返回 metrics 数据目录路径: <project_root>/.ae-state/metrics."""
    return project_root / ".ae-state" / "metrics"
