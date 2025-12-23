# iCloud CLI Tool

A command-line tool for syncing files with iCloud Drive, similar to Perforce workflow.

## Installation

```bash
pip install -e .
```

## Usage

```bash
# Login to iCloud
icloud login

# List files in iCloud Drive
icloud list
icloud list -f root          # List root directory
icloud list -f Documents -r  # List recursively

# Sync remote files (download)
icloud sync                          # Sync Documents folder
icloud sync -f root                  # Sync root folder
icloud sync -f root -n file.txt      # Sync single file

# Add files to opened list
icloud add file1.txt file2.txt       # Add specific files
icloud reconcile                      # Auto-detect changed files

# Submit local changes (upload)
icloud submit                         # Show opened files
icloud submit -a                      # Upload all opened files
icloud submit -n file.txt             # Upload specific file
icloud submit -n file.txt -f root     # Upload to root folder

# Resolve conflicts
icloud resolve

# Show status
icloud info

# Logout
icloud logout
```

## Commands

- `icloud login`: Authenticate with iCloud and save credentials
- `icloud logout`: Logout and clear saved credentials
- `icloud list`: List files in iCloud Drive
- `icloud add`: Add files to the opened list for submission
- `icloud reconcile`: Scan local changes and mark files as opened
- `icloud sync`: Download remote changes from iCloud
- `icloud submit`: Upload opened files to iCloud
- `icloud resolve`: Resolve file conflicts
- `icloud info`: Display current status, opened files, and conflicts
- `icloud submit`: Upload local changes to iCloud
- `icloud info`: Display current status, opened files, and conflicts

