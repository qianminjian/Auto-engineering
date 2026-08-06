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

from auto_engineering.gates.contract import (
    ContractGate,
    _check_contract_in_source,
    _collect_source_files,
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
    passed, _msg = _check_contract_in_source(contract, [source_file])
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
    passed, _msg = _check_contract_in_source(contract, [nonexistent])
    # Should not crash, path not found because source text is empty
    assert passed is False


# ============================================================
# Group 4: run() — v5.0 contracts dict path
# ============================================================


def test_run_with_contracts_dict_not_applicable_when_empty(tmp_path: Path) -> None:
    """空契约集合是机器可判定的不适用，而不是通过。"""
    gate = ContractGate()
    gate.contracts = {}
    verdict = gate.run(tmp_path)
    assert verdict.passed is False
    assert verdict.not_applicable is True
    assert "空" in verdict.message


def test_run_single_agent_is_not_applicable(tmp_path: Path) -> None:
    """没有 spawn proof 的单 Agent 项目不需要跨 Agent 契约检查。"""
    verdict = ContractGate().run(tmp_path)
    assert verdict.passed is False
    assert verdict.not_applicable is True
    assert verdict.skipped is True


def test_run_multi_agent_without_declared_contracts_is_not_applicable(tmp_path: Path) -> None:
    """spawn proof 只证明执行过 Agent，不证明项目存在跨模块契约。"""
    proofs = tmp_path / ".ae-state" / "spawn-proofs"
    proofs.mkdir(parents=True)
    (proofs / "proof.json").write_text("{}", encoding="utf-8")

    verdict = ContractGate().run(tmp_path)

    assert verdict.passed is False
    assert verdict.skipped is True
    assert verdict.not_applicable is True


def test_run_with_contracts_non_dict(tmp_path: Path) -> None:
    """run() with non-dict contracts → Verdict.failed."""
    gate = ContractGate()
    gate.contracts = "not a dict"
    verdict = gate.run(tmp_path)
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
    gate.contracts = {
        "items-api": {
            "path": "/api/items",
            "status_code": 201,
            "request": {"name": "str"},
        }
    }
    verdict = gate.run(tmp_path)
    assert verdict.passed is True
    assert "通过" in verdict.message


# ============================================================
# Group 5: _check_contracts — error paths
# ============================================================


def test_check_contracts_project_root_not_exist(tmp_path: Path) -> None:
    """_check_contracts: project_root不存在 → Verdict.failed."""
    gate = ContractGate()
    nonexistent = tmp_path / "nonexistent_dir"
    gate.contracts = {"api": {"path": "/x"}}
    verdict = gate._check_contracts(nonexistent)
    assert verdict.passed is False
    assert "不存在" in verdict.message


def test_check_contracts_no_source_files(tmp_path: Path) -> None:
    """_check_contracts: no source files found → Verdict.failed."""
    gate = ContractGate()
    # tmp_path is empty, no source code files
    gate.contracts = {"api": {"path": "/x"}}
    verdict = gate._check_contracts(tmp_path)
    assert verdict.passed is False
    assert "未找到源文件" in verdict.message


def test_check_contracts_non_dict_entry(tmp_path: Path) -> None:
    """非对象契约必须失败，禁止全部跳过后形成假通过。"""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("hello")

    gate = ContractGate()
    gate.contracts = {"bad": "not a dict"}
    verdict = gate._check_contracts(tmp_path)
    assert verdict.passed is False
    assert "必须为 object" in verdict.message


def test_contract_gate_checks_server_root_when_src_also_exists(tmp_path: Path) -> None:
    """BFF 位于 server/ 时不能因 src/ 存在而漏扫服务端实现。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "client.ts").write_text("export const client = true")
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "route.ts").write_text(
        "router.post('/api/clone', () => ({voice_id: 'x'}))"
    )
    gate = ContractGate()
    gate.contracts = {
        "clone": {"path": "/api/clone", "response": {"voice_id": "string"}}
    }

    assert gate.run(tmp_path).passed is True


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
    gate.contracts = contracts
    verdict = gate._check_contracts(tmp_path)
    # Should fail because second contract's path is not found
    assert verdict.passed is False
    assert "missing" in verdict.message


def test_run_single_agent_no_contracts(tmp_path: Path) -> None:
    """run() with single agent, no contracts → not applicable."""
    gate = ContractGate()
    verdict = gate.run(tmp_path)
    assert verdict.passed is False
    assert verdict.not_applicable is True


def test_contract_gate_default_constructor(tmp_path: Path) -> None:
    """ContractGate default constructor values."""
    gate = ContractGate()
    assert gate.name == "contract"
    assert gate.contracts_dir == Path(".ae-contracts")


def test_contract_gate_custom_constructor(tmp_path: Path) -> None:
    """ContractGate with custom contracts_dir."""
    custom = tmp_path / "custom-contracts"
    gate = ContractGate(contracts_dir=custom)
    assert gate.contracts_dir == custom
