---
name: ae-init
version: 0.1.0
description: >-
  Initialize project environment for Claude Code agents. Supports two modes:
  (1)存量项目: analyzes existing codebase, auto-detects project type, scaffolds missing files.
  (2)新项目: wizard-style prompts, generates customized project skeleton.

  Core inspiration: Copier (5-phase pipeline) + Cookiecutter (template rendering) + SST (auto-detect).
  Trigger: /ae-init or "ae init" in agent prompt.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
inputs:
  command:
    type: string
    required: true
    description: |
      Command to execute. Supported formats:
      - "init <project> --type <type>" — initialize new project
      - "init . --type <type>" — initialize in current directory
      - "analyze <path>" — analyze existing project type
      - "detect <path>" — detect project type without initializing
  project_type:
    type: string
    required: false
    description: |
      Project type hint. One of: app-service, library, cli-tool,
      skill, hook, mcp-server, spec-doc, monorepo.
  package_manager:
    type: string
    required: false
    description: |
      Preferred package manager. Auto-detected if not specified.
      Options: npm, pnpm, yarn, bun, uv, poetry, cargo, go
  ci_platform:
    type: string
    required: false
    description: CI platform. Options: github, gitlab, none
  use_typescript:
    type: boolean
    required: false
    description: Use TypeScript (for TypeScript/Python/Go/Rust projects)
  use_lefthook:
    type: boolean
    required: false
    description: Install Lefthook git hooks
  defaults:
    type: boolean
    required: false
    description: Non-interactive mode, use all default values
  force:
    type: boolean
    required: false
    description: Allow overwriting non-empty directory
  incremental:
    type: boolean
    required: false
    description: Incremental mode: only add missing files, do not overwrite existing
  analyze_only:
    type: boolean
    required: false
    description: "For existing projects: only analyze type, do not initialize"
trigger: /ae-init
---

# ae-init

Agent Skill for project environment initialization. Run `/ae-init` in any project directory.

## Two Modes

### Mode 1 — 存量项目 (Existing Project Analysis)

Auto-detects project type by scanning known file signatures (package.json, pyproject.toml, Cargo.toml, etc.), then scaffolds missing configuration files without modifying existing source code.

```bash
# Analyze existing project
ae init --analyze /path/to/project

# Detect type only (no initialization)
ae init --detect /path/to/project
```

### Mode 2 — 新项目 (New Project Scaffolding)

Wizard-style prompts for project configuration, generates a customized project skeleton from templates.

```bash
# New TypeScript project
ae init my-project --type app-service --use-typescript

# New Python library
ae init my-lib --type library --package-manager uv

# Non-interactive (all defaults)
ae init my-project --type app-service --defaults
```

## 5-Phase Pipeline

```
detect → prompt → render → tasks → finalize
```

| Phase | What it does |
|-------|-------------|
| **detect** | Scan directory, match FRAMEWORK_SIGNATURES, auto-detect or ask |
| **prompt** | Interactive questions (supports secret/multiselect/placeholder) |
| **render** | Jinja2 double-pass rendering (filename + content) to temp dir |
| **tasks** | Execute pre/post hooks (git init, install, etc.) |
| **finalize** | Atomic move from temp dir to target, write .ae-answers.yml |

## Project Types (8 types × 4 languages = 32 combinations)

| Type | TS/Node | Python | Go | Rust |
|------|---------|--------|-----|------|
| app-service | ✓ | ✓ | ✓ | - |
| library | ✓ | ✓ | ✓ | ✓ |
| cli-tool | ✓ | ✓ | ✓ | ✓ |
| skill | ✓ (Claude Code) | - | - | - |
| hook | Bash (Bats) | - | - | - |
| mcp-server | ✓ | ✓ | - | - |
| spec-doc | Markdown | - | - | - |
| monorepo | ✓ (pnpm) | - | - | - |

## Key Features

- **Auto-detect**: Infers project type from existing files, zero-configuration for existing projects
- **Incremental mode**: Only adds missing files, never overwrites existing (`--incremental`)
- **Template composition**: 8 types × 4 languages, shared base templates via `_shared/` + `_features/`
- **Secret support**: Password/token fields hidden during input
- **Partial save**: Ctrl-C saves partial answers to `~/.ae-partial-answers.yml`
- **Answers replay**: `--from-answers .ae-answers.yml` replays a previous session

## Outputs

After initialization, the project contains:

| File | Purpose |
|------|---------|
| `.ae-answers.yml` | Project configuration (committed to git) |
| `CLAUDE.md` | AI context for downstream agents |
| `.claude/rules/` | Project-level rules |
| `{package,pyproject,Cargo}.{json,toml}` | Package manifest |
| `{tsconfig,eslint,prettier}.{json,js}` | TypeScript config (if applicable) |
| `*.test.{ts,py,go,rs}` | Test files (if applicable) |

## Configuration

Edit `.ae-answers.yml` to change project configuration after initialization:

```yaml
project_name: my-project
project_type: app-service
language: typescript
package_manager: pnpm
```

## Directory Structure (as Claude Code Skill)

```
auto-engineering/          # Python package (Skill implementation)
├── __init__.py
├── skill.py               # Skill entry point
├── errors.py              # Shared errors
├── init/                  # Init engine
│   ├── detector.py       # Project type detection
│   ├── renderer.py       # Jinja2 template renderer
│   ├── answers.py        # AnswersMap (6-layer ChainMap)
│   ├── prompts.py        # Interactive prompt
│   ├── hooks.py          # Task runner
│   ├── scaffold_phases.py # 5-phase pipeline
│   ├── templates/        # Project templates
│   │   ├── _shared/      # Shared base templates
│   │   ├── _features/    # Composable language features
│   │   └── <type>/       # 8 project types
│   └── errors.py         # Init-specific errors
├── config/
│   └── environment.py   # .ae-answers.yml reader
└── cli/
    └── __init__.py      # CLI commands

SKILL.md                   # This file — Skill metadata
.claude/rules/             # Project-level rules
tests/                     # Test suite
design/                    # Design documents
```

## Error Handling

All errors have `exit_code` for CLI integration:

| exit_code | Error | When |
|-----------|-------|------|
| 1 | InitError | Generic failure |
| 2 | ConfigFileError | ae-template.yml missing or version mismatch |
| 3 | UnsatisfiedPrerequisiteError | git/python not installed |
| 4 | TargetDirectoryError | Directory not writable or non-empty without --force |
| 5 | ValidationError | User input validation failed |
| 6 | TaskExecutionError | Hook command failed |
| 7 | TemplateRenderError | Jinja2 rendering failed |
| 130 | InitInterruptedError | User pressed Ctrl-C |
