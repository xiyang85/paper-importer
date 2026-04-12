#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== paper-importer installation ==="

# Prefer uv (fast), fall back to pip
if command -v uv &>/dev/null; then
    echo "Using uv..."
    cd "$SCRIPT_DIR"
    uv venv .venv --python 3.11 -q
    uv pip install -e . -q
    echo ""
    echo "Installation complete!"
    echo ""
    echo "Add this to your shell config (~/.zshrc or ~/.bashrc):"
    echo ""
    echo "  export PATH=\"$SCRIPT_DIR/.venv/bin:\$PATH\""
    echo ""
    echo "Then restart your shell and run:  paper setup"
elif command -v pip3 &>/dev/null; then
    python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "unknown")
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
        echo "Using pip3 (Python $python_version)..."
        cd "$SCRIPT_DIR"
        pip3 install -e . -q
        echo ""
        echo "Installation complete! Run:  paper setup"
    else
        echo "Error: Python 3.10+ required (found $python_version)."
        echo "Please install Python 3.10+ or uv (https://docs.astral.sh/uv/)"
        exit 1
    fi
else
    echo "Error: Neither uv nor pip3 found."
    echo "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
