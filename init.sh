#!/bin/bash

# iCloud CLI Tool - Initialization Script

set -e

echo "Initializing iCloud CLI development environment..."

# Check Python version - try multiple ways to find python3
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif [ -f /usr/bin/python3 ]; then
    PYTHON_CMD="/usr/bin/python3"
elif [ -f /usr/local/bin/python3 ]; then
    PYTHON_CMD="/usr/local/bin/python3"
else
    echo "Error: python3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

echo "Using Python: $PYTHON_CMD"

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
REQUIRED_VERSION="3.8"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "Error: Python 3.8 or higher is required. Found: $PYTHON_VERSION"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON_CMD -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
. venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Install project in editable mode
echo "Installing iCloud CLI in editable mode..."
pip install -e .

echo ""
echo "✓ Initialization complete!"
echo ""
echo "To activate the virtual environment, run:"
echo "  source venv/bin/activate"
echo ""
echo "Then you can use the icloud command:"
echo "  icloud login"
echo "  icloud info"
echo ""

