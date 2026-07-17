#!/bin/bash
# install.sh — Auto-Engineering multi-platform plugin installer (v8.0)
# Supports: Claude Code (claude), Codex (codex), CodeBuddy (codebuddy)
#
# Usage:
#   ./install.sh                    # auto-detect platform and install
#   ./install.sh --claude-code      # force Claude Code install
#   ./install.sh --codex            # force Codex install
#   ./install.sh --codebuddy        # force CodeBuddy install
#   ./install.sh --all              # install for all detected platforms
#   ./install.sh --uninstall        # remove from all platforms
#
# Exit codes: 0=success, 1=partial failure, 2=no platform detected

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_NAME="auto-engineering"

# ── Platform detection ──

detect_platforms() {
    local detected=""
    if command -v claude &>/dev/null || [[ -d "$HOME/.claude" ]]; then
        detected="$detected claude-code"
    fi
    if command -v codex &>/dev/null || [[ -d "$HOME/.codex" ]]; then
        detected="$detected codex"
    fi
    if command -v codebuddy &>/dev/null || [[ -d "$HOME/.codebuddy" ]]; then
        detected="$detected codebuddy"
    fi
    echo "${detected# }"
}

# ── Install per platform ──

install_claude_code() {
    local target="$HOME/.claude/plugins/$PLUGIN_NAME"
    echo "  Installing Claude Code plugin → $target"
    mkdir -p "$(dirname "$target")"
    rm -rf "$target"
    cp -r "$SCRIPT_DIR/.claude-plugin" "$target"
    echo "  ✓ Claude Code plugin installed"
}

install_codex() {
    local target="$HOME/.codex/plugins/$PLUGIN_NAME"
    echo "  Installing Codex plugin → $target"
    mkdir -p "$(dirname "$target")"
    rm -rf "$target"
    cp -r "$SCRIPT_DIR/.codex-plugin" "$target"
    echo "  ✓ Codex plugin installed"
}

install_codebuddy() {
    local target="$HOME/.codebuddy/plugins/$PLUGIN_NAME"
    echo "  Installing CodeBuddy plugin → $target (symlink to Claude Code)"
    mkdir -p "$(dirname "$target")"
    rm -rf "$target"
    ln -sfn "$HOME/.claude/plugins/$PLUGIN_NAME" "$target"
    echo "  ✓ CodeBuddy plugin installed (symlink → Claude Code)"
}

# ── Uninstall ──

uninstall_all() {
    echo "Uninstalling Auto-Engineering plugin..."
    for dir in "$HOME/.claude/plugins/$PLUGIN_NAME" \
               "$HOME/.codex/plugins/$PLUGIN_NAME" \
               "$HOME/.codebuddy/plugins/$PLUGIN_NAME"; do
        if [[ -e "$dir" ]]; then
            rm -rf "$dir"
            echo "  ✓ Removed $dir"
        fi
    done
    echo "✓ Uninstall complete"
}

# ── Main ──

main() {
    local mode="${1:-auto}"

    case "$mode" in
        --uninstall)
            uninstall_all
            exit 0
            ;;
        --claude-code)
            echo "Auto-Engineering Plugin Installer (Claude Code only)"
            install_claude_code
            ;;
        --codex)
            echo "Auto-Engineering Plugin Installer (Codex only)"
            install_codex
            ;;
        --codebuddy)
            echo "Auto-Engineering Plugin Installer (CodeBuddy only)"
            install_codebuddy
            ;;
        --all)
            echo "Auto-Engineering Plugin Installer (all detected platforms)"
            local platforms
            platforms=$(detect_platforms)
            if [[ -z "$platforms" ]]; then
                echo "✗ No platforms detected. Install manually with --claude-code / --codex / --codebuddy"
                exit 2
            fi
            echo "Detected: $platforms"
            for p in $platforms; do
                case "$p" in
                    claude-code) install_claude_code ;;
                    codex) install_codex ;;
                    codebuddy) install_codebuddy ;;
                esac
            done
            ;;
        ""|auto|--auto)
            echo "Auto-Engineering Plugin Installer (auto-detect)"
            local platforms
            platforms=$(detect_platforms)
            if [[ -z "$platforms" ]]; then
                echo "✗ No platforms detected. Install manually:"
                echo "  ./install.sh --claude-code"
                echo "  ./install.sh --codex"
                echo "  ./install.sh --codebuddy"
                exit 2
            fi
            echo "Detected: $platforms"
            for p in $platforms; do
                case "$p" in
                    claude-code) install_claude_code ;;
                    codex) install_codex ;;
                    codebuddy) install_codebuddy ;;
                esac
            done
            ;;
        *)
            echo "Usage: $0 [--auto|--claude-code|--codex|--codebuddy|--all|--uninstall]"
            exit 1
            ;;
    esac

    echo ""
    echo "✓ Installation complete. Verify with: cd $PLUGIN_NAME && ae doctor"
}

main "${1:-auto}"
