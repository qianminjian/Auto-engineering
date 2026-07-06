"""Extended coverage tests for gates/contract.py (79% → ≥85%).

Covers missed paths:
- _collect_source_files with src/ dir and without
- _check_contract_in_source for all 4 check types
- run() with v5.0 contracts dict path (single/multi agent)
- run() with non-dict contracts → Verdict.failed
- run() with empty contracts → skip
- _check_contracts missing project_root / no source files / non-dict entry
- _check_contracts_dir with JSON files / empty files / absolute path / no files
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from auto_engineering.gates.base import GateVerdict
from auto_engineering.gates.contract import (
    ContractGate,
    _collect_source_files,
    _check_contract_in_source,
    _SOURCE_EXTENSIONS,
)


# ============================================================
# Group 1: _collect_source_files
# ============================================================


def test_collect_source_files_with_src_dir(tmp_path: Path) -> None:
    """_collect_source_files collects from src/ when it exists."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("print('hello')")
    (src_dir / "utils.ts").write_text("export const x = 1")
    # Non-source file (should be excluded)
    (src_dir / "README.md").write_text("# Readme")

    files = _collect_source_files(tmp_path)
    paths = [f.name for f in files]
    assert "main.py" in paths
    assert "utils.ts" in paths
    assert "README.md" not in paths


def test_collect_source_files_without_src_dir(tmp_path: Path) -> None:
    """_collect_source_files falls back to project_root when no src/."""
    (tmp_path / "app.py").write_text("x = 1")
    (tmp_path / "lib.go").write_text("package main")

    files = _collect_source_files(tmp_path)
    paths = [f.name for f in files]
    assert "app.py" in paths
    assert "lib.go" in paths


def test_collect_source_files_nested_src(tmp_path: Path) -> None:
    """_collect_source_files scans subdirectories under src/."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    sub_dir = src_dir / "subpkg"
    sub_dir.mkdir(parents=True)
    (sub_dir / "helper.py").write_text("def f(): pass")

    files = _collect_source_files(tmp_path)
    paths = [f.name for f in files]
    assert "helper.py" in paths


def test_collect_source_files_no_matching(tmp_path: Path) -> None:
    """_collect_source_files returns empty when no source files found."""
    (tmp_path / "readme.md").write_text("hello")
    (tmp_path / "config.toml").write_text("key = value")

    files = _collect_source_files(tmp_path)
    assert files == []


def test_collect_source_files_with_nonexistent_dir(tmp_path: Path) -> None:
    """_collect_source_files with non-existent directory returns [] (defensive)."""
    nonexistent = tmp_path / "nonexistent_dir"
    files = _collect_source_files(nonexistent)
    assert files == []


# ============================================================
# Group 2: _check_contract_in_source — success path
# ============================================================


def test_check_contract_in_source_all_pass(tmp_path: Path) -> None:
    """_check_contract_in_source returns True when all fields found in source."""
    source_file = tmp_path / "app.py"
    source_file.write_text(
        'app.get("/api/users", handler)\n'
        "# returns status 200\n"
        "class CreateUserRequest:\n"
        "    name: str\n"
        "    email: str\n"
    )

    contract = {
        "path": "/api/users",
        "status_code": 200,
        "request": {"name": "str", "email": "str"},
        "response": {},
    }
    passed, msg = _check_contract_in_source(contract, [source_file])
    assert passed is True
    assert msg == "ok"


def test_check_contract_in_source_no_path_declared(tmp_path: Path) -> None:
    """_check_contract_in_source with no path declared → still passes (only checks declared)."""
    source_file = tmp_path / "app.py"
    source_file.write_text("returns status 200")

    contract = {"status_code": 200}
    passed, msg = _check_contract_in_source(contract, [source_file])
    assert passed is True


# ============================================================
# Group 3: _check_contract_in_source — failure paths
# ============================================================


def test_check_contract_path_not_found(tmp_path: Path) -> None:
    """_check_contract_in_source fails when path not in source."""
    source_file = tmp_path / "app.py"
    source_file.write_text("print('hello')")

    contract = {"path": "/api/missing"}
    passed, msg = _check_contract_in_source(contract, [source_file])
    assert passed is False
    assert "path '/api/missing' not found" in msg


def test_check_contract_status_code_not_found(tmp_path: Path) -> None:
    """_check_contract_in_source fails when status_code not in source."""
    source_file = tmp_path / "app.py"
    source_file.write_text("print('hello')")

    contract = {"status_code": 999}
    passed, msg = _check_contract_in_source(contract, [source_file])
    assert passed is False
    assert "status_code '999' not found" in msg


def test_check_contract_request_field_not_found(tmp_path: Path) -> None:
    """_check_contract_in_source fails when request field name not in source."""
    source_file = tmp_path / "app.py"
    source_file.write_text("def handler(): pass")

    contract = {"request": {"missing_field": "str"}}
    passed, msg = _check_contract_in_source(contract, [source_file])
    assert passed is False
    assert "request field 'missing_field'" in msg


def test_check_contract_response_field_not_found(tmp_path: Path) -> None:
    """_check_contract_in_source fails when response field name not in source."""
    source_file = tmp_path / "app.py"
    source_file.write_text("def handler(): pass")

    contract = {"response": {"missing_field": "int"}}
    passed, msg = _check_contract_in_source(contract, [source_file])
    assert passed is False
    assert "response field 'missing_field'" in msg


def test_check_contract_in_source_oserror_handled(tmp_path: Path) -> None:
    """_check_contract_in_source handles OSError when reading source files."""
    # Use a path that doesn't exist as a file
    nonexistent = tmp_path / "nonexistent.py"
    contract = {"path": "/api/test"}
    passed, msg = _check_contract_in_source(contract, [nonexistent])
    # Should not crash, path not found because source text is empty
    assert passed is False


# ============================================================
# Group 4: run() — v5.0 contracts dict path
# ============================================================


def test_run_with_contracts_dict_skip_empty(tmp_path: Path) -> None:
    """run() with empty contracts dict → skip Verdict."""
    gate = ContractGate()
    verdict = gate.run(tmp_path, contracts={})
    assert verdict.passed is True
    assert "skip" in verdict.message.lower()
    assert "空" in verdict.message


def test_run_with_contracts_non_dict(tmp_path: Path) -> None:
    """run() with non-dict contracts → Verdict.failed."""
    gate = ContractGate()
    verdict = gate.run(tmp_path, contracts="not a dict")
    assert verdict.passed is False
    assert "必须是 dict" in verdict.message


def test_run_with_contracts_valid_v5_path(tmp_path: Path) -> None:
    """run() v5.0 path: valid contracts dict with matching source."""
    # Create source file with expected content
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "api.py").write_text(
        'router.get("/api/items", handler)\n'
        "# returns 201 Created\n"
        "class ItemRequest:\n"
        "    name: str\n"
    )

    gate = ContractGate()
    contracts = {
        "items-api": {
            "path": "/api/items",
            "status_code": 201,
            "request": {"name": "str"},
        }
    }
    verdict = gate.run(tmp_path, contracts=contracts)
    assert verdict.passed is True
    assert "通过" in verdict.message


# ============================================================
# Group 5: _check_contracts — error paths
# ============================================================


def test_check_contracts_project_root_not_exist(tmp_path: Path) -> None:
    """_check_contracts: project_root不存在 → Verdict.failed."""
    gate = ContractGate()
    nonexistent = tmp_path / "nonexistent_dir"
    verdict = gate._check_contracts(nonexistent, {"api": {"path": "/x"}})
    assert verdict.passed is False
    assert "不存在" in verdict.message


def test_check_contracts_no_source_files(tmp_path: Path) -> None:
    """_check_contracts: no source files found → Verdict.failed."""
    gate = ContractGate()
    # tmp_path is empty, no source code files
    verdict = gate._check_contracts(tmp_path, {"api": {"path": "/x"}})
    assert verdict.passed is False
    assert "未找到源文件" in verdict.message


def test_check_contracts_non_dict_entry(tmp_path: Path) -> None:
    """_check_contracts: contract entry is not a dict → Verdict.failed."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("hello")

    gate = ContractGate()
    verdict = gate._check_contracts(tmp_path, {"bad": "not a dict"})
    assert verdict.passed is False
    assert "必须是 dict" in verdict.message


def test_check_contracts_mixed_pass_fail(tmp_path: Path) -> None:
    """_check_contracts: first contract passes, second fails (early exit on first failure)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "api.py").write_text(
        'app.get("/api/ok", handler)\n'
        'app.post("/api/create", handler)\n'
    )

    gate = ContractGate()
    contracts = {
        "ok-api": {"path": "/api/ok"},
        "fail-api": {"path": "/api/missing"},
    }
    verdict = gate._check_contracts(tmp_path, contracts)
    # Should fail because second contract's path is not found
    assert verdict.passed is False
    assert "missing" in verdict.message


# ============================================================
# Group 6: _check_contracts_dir — extended paths
# ============================================================


def test_check_contracts_dir_with_json_file(tmp_path: Path) -> None:
    """_check_contracts_dir: JSON format contract file is parsed."""
    import json

    contracts_dir = tmp_path / ".ae-contracts"
    contracts_dir.mkdir()
    (contracts_dir / "api.json").write_text(
        json.dumps({"agents": {"developer": {"provides": ["impl.py"]}}})
    )

    gate = ContractGate(contracts_dir=contracts_dir)
    verdict = gate._check_contracts_dir(tmp_path, 2)
    assert verdict.passed is True
    assert "valid" in verdict.message.lower()


def test_check_contracts_dir_empty_file(tmp_path: Path) -> None:
    """_check_contracts_dir: empty contract file → Verdict.failed."""
    contracts_dir = tmp_path / ".ae-contracts"
    contracts_dir.mkdir()
    (contracts_dir / "empty.yml").write_text("")

    gate = ContractGate(contracts_dir=contracts_dir)
    verdict = gate._check_contracts_dir(tmp_path, 2)
    assert verdict.passed is False
    assert "empty" in verdict.message.lower()


def test_check_contracts_dir_no_yaml_or_json_files(tmp_path: Path) -> None:
    """_check_contracts_dir: directory exists but no .yml/.yaml/.json → Verdict.failed."""
    contracts_dir = tmp_path / ".ae-contracts"
    contracts_dir.mkdir()
    (contracts_dir / "readme.txt").write_text("not a contract file")

    gate = ContractGate(contracts_dir=contracts_dir)
    verdict = gate._check_contracts_dir(tmp_path, 2)
    assert verdict.passed is False
    assert "no contract files" in verdict.message.lower()


def test_check_contracts_dir_with_yaml_file(tmp_path: Path) -> None:
    """_check_contracts_dir: .yaml extension (not .yml) is also accepted."""
    contracts_dir = tmp_path / ".ae-contracts"
    contracts_dir.mkdir()
    (contracts_dir / "api.yaml").write_text("agents:\n  developer:\n    provides: [impl.py]\n")

    gate = ContractGate(contracts_dir=contracts_dir)
    verdict = gate._check_contracts_dir(tmp_path, 2)
    assert verdict.passed is True
    assert "valid" in verdict.message.lower()


def test_check_contracts_dir_relative_path_resolves(tmp_path: Path) -> None:
    """_check_contracts_dir: relative contracts_dir resolved against project_root."""
    contracts_dir = tmp_path / ".ae-contracts"
    contracts_dir.mkdir()
    (contracts_dir / "api.yml").write_text("agents:\n  dev:\n    provides: [x.py]\n")

    # Relative path ".ae-contracts"
    gate = ContractGate(contracts_dir=".ae-contracts")
    verdict = gate._check_contracts_dir(tmp_path, 2)
    assert verdict.passed is True


# ============================================================
# Group 7: backward-compatible paths
# ============================================================


def test_run_single_agent_no_contracts(tmp_path: Path) -> None:
    """run() with single agent, no contracts → skip (backward compat)."""
    gate = ContractGate()
    verdict = gate.run(tmp_path)
    assert verdict.passed is True
    assert "skip" in verdict.message.lower()


def test_run_multi_agent_no_contracts_dir(tmp_path: Path) -> None:
    """_check_contracts_dir without .ae-contracts dir → failed."""
    gate = ContractGate(contracts_dir=".ae-contracts")
    verdict = gate._check_contracts_dir(tmp_path, 3)
    assert verdict.passed is False


def test_contract_gate_default_constructor(tmp_path: Path) -> None:
    """ContractGate default constructor values."""
    gate = ContractGate()
    assert gate.name == "contract"
    assert gate.applies_to_stages == ("developer", "critic")
    assert gate.contracts_dir == Path(".ae-contracts")


def test_contract_gate_custom_constructor(tmp_path: Path) -> None:
    """ContractGate with custom contracts_dir."""
    custom = tmp_path / "custom-contracts"
    gate = ContractGate(contracts_dir=custom)
    assert gate.contracts_dir == custom
