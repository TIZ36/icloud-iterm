#!/bin/bash

# iCloud CLI Tool - Rebuild Script

set -e

echo "Rebuilding iCloud CLI..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Running init.sh first..."
    ./init.sh
    exit 0
fi

# Activate virtual environment
echo "Activating virtual environment..."
. venv/bin/activate

# Check Python command
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif [ -f /usr/bin/python3 ]; then
    PYTHON_CMD="/usr/bin/python3"
elif [ -f /usr/local/bin/python3 ]; then
    PYTHON_CMD="/usr/local/bin/python3"
else
    echo "Error: python3 is not installed."
    exit 1
fi

# Clean old build files
echo "Cleaning old build files..."
rm -rf build/
rm -rf dist/
rm -rf *.egg-info/
find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Reinstall dependencies
echo "Reinstalling dependencies..."
pip install --upgrade -r requirements.txt

# Uninstall old version if exists
echo "Uninstalling old version..."
pip uninstall -y icloud-cli 2>/dev/null || true

# Reinstall project in editable mode
echo "Reinstalling iCloud CLI in editable mode..."
pip install -e . --force-reinstall

echo ""
echo "✓ Rebuild complete!"
echo ""
echo "The icloud command is now updated."
echo ""

