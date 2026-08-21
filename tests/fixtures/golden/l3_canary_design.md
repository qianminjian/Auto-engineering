# Deterministic Counter Canary

## A1 Core

### A1.1 Counter function

- Package builds use the `hatchling.build` backend declared explicitly in `pyproject.toml`; legacy
  or implicit build-backend discovery is outside this design.
- The source distribution must exclude `.ae-state`, `_scratch`, `.venv`, `dist`, and every
  `__pycache__` directory; Core state and transient workspace artifacts are not product source.
- Use a standard regular-package src layout: create an empty `src/canary_math/__init__.py`.
- The only public import path required by this design is
  `from canary_math.counter import next_value`; do not re-export `next_value` from the package root.
- Implement `next_value(current: int, step: int = 1) -> int` in `src/canary_math/counter.py`.
- Return exactly `current + step`; zero and negative `current` values have no special branch.
- Accept only exact built-in `int` values for both arguments (`type(value) is int`). Reject `bool`,
  `IntEnum`, custom `int` subclasses, float, string, and every other value with `TypeError`.
- Validate both argument types before checking `step`; TypeError message text is not contractual.
- `step <= 0` must raise `ValueError("step must be positive")`.
- The function must have no I/O, network access, or mutable global state.

#### Verification

- `tests/test_counter.py` must cover the default step success path, custom step, zero and negative
  `current`, invalid values for both arguments, and zero/negative `step`.
- Tests must assert the exact ValueError message and must not assert TypeError message text.
- Run exactly these acceptance commands from the project root; their default configuration in
  `pyproject.toml` is contractual and no stricter flags are implied:
  - test: `uv run pytest -q`
  - lint: `uv run ruff check src tests`
  - type check: `uv run mypy src tests`
  - build: `uv build`
  All four commands must pass.
