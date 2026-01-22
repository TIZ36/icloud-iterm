"""CLI interface for iCloud tool."""

import sys
from pathlib import Path
import click

from .auth import AuthManager
from .config import Config
from .state import State
from .sync import SyncManager
from .conflict import ConflictResolver


@click.group()
@click.pass_context
def cli(ctx):
    """iCloud CLI - Sync files with iCloud Drive (Perforce-like workflow).
    
    \b
    Quick Start:
      icloud login -u your@icloud.com    # Login to iCloud
      icloud list                         # List iCloud Drive root
      icloud list Documents               # List Documents folder
      icloud sync -f Documents            # Sync Documents to local
      
    \b
    Download Single File:
      icloud download Documents/file.txt  # Download specific file
      
    \b
    Edit & Submit Workflow (like Perforce):
      icloud checkout file.txt            # Mark file for editing
      (edit file locally)
      icloud submit file.txt              # Upload changes
      icloud submit -a                    # Upload all checked out files
      
    \b
    Other Commands:
      icloud revert file.txt              # Undo checkout
      icloud reconcile                    # Scan for local changes
      icloud info                         # Show status
    """
    ctx.ensure_object(dict)
    ctx.obj['config'] = Config()
    ctx.obj['state'] = State()


@cli.command()
@click.option('--username', '-u', help='Apple ID username')
@click.pass_context
def login(ctx, username):
    """Login to iCloud and save credentials.
    
    \b
    Examples:
      icloud login                       # Interactive login
      icloud login -u your@icloud.com    # Login with username
    
    \b
    Notes:
      - Supports 2FA verification
      - Credentials stored securely in system keyring
      - Session cached in ~/.pyicloud
    """
    config = ctx.obj['config']
    auth = AuthManager(config)
    
    if auth.login(username):
        click.echo("Successfully logged in to iCloud.")
    else:
        click.echo("Login failed.", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def logout(ctx):
    """Logout from iCloud and clear saved credentials.
    
    \b
    Example:
      icloud logout
    
    \b
    Notes:
      - Clears keyring password
      - Removes session cookies
    """
    config = ctx.obj['config']
    auth = AuthManager(config)
    
    auth.logout()
    click.echo("Successfully logged out from iCloud.")


@cli.command()
@click.pass_context
def reconcile(ctx):
    """Scan local changes and mark files as opened.
    
    \b
    Example:
      icloud reconcile
    
    \b
    Notes:
      - Compares local files with stored hashes
      - New or modified files are marked as 'opened'
      - Run 'icloud submit -a' to upload opened files
    """
    config = ctx.obj['config']
    state = ctx.obj['state']
    
    # Check authentication
    auth = AuthManager(config)
    if not auth.is_authenticated():
        click.echo("Not authenticated. Please run 'icloud login' first.", err=True)
        sys.exit(1)
    
    # Get sync manager (we need service for sync, but reconcile only needs state)
    service = auth.get_service()
    if not service:
        click.echo("Failed to get iCloud service.", err=True)
        sys.exit(1)
    
    sync_manager = SyncManager(service, state, config)
    
    click.echo("Scanning for local changes...")
    files_opened = sync_manager.reconcile_local_changes()
    
    if files_opened > 0:
        click.echo(f"Marked {files_opened} file(s) as opened.")
    else:
        click.echo("No local changes found.")


@cli.command()
@click.option('--folder', '-f', default='Documents', 
              help='Remote folder path to sync (e.g., Documents, Documents/subfolder)')
@click.option('--workers', '-w', default=8, type=int,
              help='Number of concurrent workers (default: 8)')
@click.option('--depth', '-d', default=0, type=int,
              help='Max recursion depth (0 = unlimited, 1 = top level only)')
@click.option('--no-exclude', is_flag=True, default=False,
              help='Disable default exclusions (.git, node_modules, etc.)')
@click.pass_context
def sync(ctx, folder, workers, depth, no_exclude):
    """Sync remote folder from iCloud to local.
    
    \b
    Examples:
      icloud sync                        # Sync all from Documents
      icloud sync -f Desktop             # Sync from Desktop folder
      icloud sync -f root                # Sync from iCloud Drive root
      icloud sync -f Documents/Projects  # Sync specific subfolder
      icloud sync -w 16                  # Use 16 concurrent workers
      icloud sync -d 2                   # Only scan 2 levels deep
    
    \b
    Notes:
      - Files downloaded to current directory preserving folder structure
      - Existing files are skipped (use 'icloud reconcile' to detect changes)
    """
    config = ctx.obj['config']
    state = ctx.obj['state']
    
    # Check authentication
    auth = AuthManager(config)
    if not auth.is_authenticated():
        click.echo("Not authenticated. Please run 'icloud login' first.", err=True)
        sys.exit(1)
    
    service = auth.get_service()
    if not service:
        click.echo("Failed to get iCloud service.", err=True)
        sys.exit(1)
    
    # Set exclude patterns
    exclude_patterns = set() if no_exclude else None  # None = use default
    
    sync_manager = SyncManager(service, state, config, max_workers=workers,
                               exclude_patterns=exclude_patterns, max_depth=depth)
    
    depth_info = f", depth: {depth}" if depth > 0 else ""
    click.echo(f"Syncing from iCloud: {folder} (workers: {workers}{depth_info})")
    files_downloaded, conflicts = sync_manager.sync_from_remote(folder)
    
    click.echo(f"Downloaded {files_downloaded} file(s).")
    if conflicts > 0:
        click.echo(f"Found {conflicts} conflict(s). Run 'icloud resolve' to resolve them.")


@cli.command('list')
@click.argument('path', default='root', required=False)
@click.option('--recursive', '-r', is_flag=True, default=False,
              help='List files recursively')
@click.pass_context
def list_files(ctx, path, recursive):
    """List files in iCloud Drive.
    
    \b
    Examples:
      icloud list                        # List iCloud Drive root
      icloud list Documents              # List Documents folder
      icloud list Documents/Projects     # List subfolder
      icloud list -r                     # List root recursively
      icloud list Documents -r           # List Documents recursively
    
    \b
    Icons:
      📁 Folder    📄 File    📱 App Library
    """
    config = ctx.obj['config']
    state = ctx.obj['state']
    
    # Check authentication
    auth = AuthManager(config)
    if not auth.is_authenticated():
        click.echo("Not authenticated. Please run 'icloud login' first.", err=True)
        sys.exit(1)
    
    service = auth.get_service()
    if not service:
        click.echo("Failed to get iCloud service.", err=True)
        sys.exit(1)
    
    sync_manager = SyncManager(service, state, config)
    
    display_path = path if path != "root" else "iCloud Drive"
    click.echo(f"📂 {display_path}")
    click.echo("=" * 60)
    
    if recursive:
        files = sync_manager.list_remote_files_recursive(path)
    else:
        files = sync_manager.list_remote_files(path)
    
    if not files:
        click.echo("  (empty)")
        return
    
    # Display files
    for file_info in files:
        file_type = file_info.get('type', 'unknown')
        name = file_info.get('name', 'unknown')
        file_path = file_info.get('path', name)
        size = file_info.get('size', 0)
        
        if file_type in ('folder', 'FOLDER'):
            icon = '📁'
            size_str = ''
        elif file_type in ('app_library', 'app'):
            icon = '📱'
            size_str = ''
        else:
            icon = '📄'
            size_str = f" ({_format_size(size)})" if size else ''
        
        if recursive and file_path != name:
            click.echo(f"  {icon} {file_path}{size_str}")
        else:
            click.echo(f"  {icon} {name}{size_str}")
    
    click.echo("=" * 60)
    click.echo(f"Total: {len(files)} item(s)")


def _format_size(size: int) -> str:
    """Format file size in human-readable format."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"


@cli.command()
@click.argument('remote_path')
@click.argument('local_path', required=False)
@click.pass_context
def download(ctx, remote_path, local_path):
    """Download a single file from iCloud.
    
    \b
    Examples:
      icloud download Documents/report.pdf           # Download to current dir
      icloud download Documents/data.json ./data/    # Download to specific dir
      icloud download Desktop/notes.txt ~/Desktop/   # Download to home Desktop
    
    \b
    Arguments:
      REMOTE_PATH  Full path in iCloud (e.g., Documents/subfolder/file.txt)
      LOCAL_PATH   Local destination (optional, defaults to current directory)
    """
    config = ctx.obj['config']
    state = ctx.obj['state']
    
    # Check authentication
    auth = AuthManager(config)
    if not auth.is_authenticated():
        click.echo("Not authenticated. Please run 'icloud login' first.", err=True)
        sys.exit(1)
    
    service = auth.get_service()
    if not service:
        click.echo("Failed to get iCloud service.", err=True)
        sys.exit(1)
    
    sync_manager = SyncManager(service, state, config)
    
    # Determine local path
    if local_path:
        local_dest = Path(local_path)
        if local_dest.is_dir():
            # If it's a directory, use the filename from remote
            filename = remote_path.split('/')[-1]
            local_dest = local_dest / filename
    else:
        filename = remote_path.split('/')[-1]
        local_dest = Path.cwd() / filename
    
    click.echo(f"Downloading: {remote_path}")
    click.echo(f"        To: {local_dest}")
    
    success = sync_manager.download_single_file(remote_path, local_dest)
    if success:
        click.echo(f"✓ Downloaded successfully")
    else:
        click.echo(f"✗ Download failed", err=True)
        sys.exit(1)


@cli.command()
@click.option('--strategy', '-s', 
              type=click.Choice(['auto', 'local', 'remote', 'merge'], case_sensitive=False),
              default='auto',
              help='Resolution strategy (default: auto)')
@click.option('--file', '-f', help='Specific file to resolve (optional)')
@click.pass_context
def resolve(ctx, strategy, file):
    """Resolve file conflicts.
    
    \b
    Examples:
      icloud resolve                     # Resolve all conflicts (auto)
      icloud resolve -s local            # Keep local version for all
      icloud resolve -s remote           # Keep remote version for all
      icloud resolve -f doc.txt          # Resolve specific file
      icloud resolve -f doc.txt -s local # Keep local for specific file
    
    \b
    Strategies:
      auto   - Automatically choose based on timestamps
      local  - Keep local version, discard remote
      remote - Keep remote version, discard local
      merge  - Attempt to merge (for text files)
    """
    config = ctx.obj['config']
    state = ctx.obj['state']
    resolver = ConflictResolver(state)
    
    conflicts = state.get_conflicts()
    
    if not conflicts:
        click.echo("No conflicts to resolve.")
        return
    
    if file:
        # Resolve specific file
        file_path = Path.cwd() / file
        if file not in conflicts:
            click.echo(f"File {file} is not in conflict.", err=True)
            sys.exit(1)
        
        if resolver.resolve_conflict(file_path, strategy):
            click.echo(f"Resolved conflict for {file}.")
        else:
            click.echo(f"Failed to resolve conflict for {file}.", err=True)
            sys.exit(1)
    else:
        # Resolve all conflicts
        resolved = 0
        failed = 0
        
        for rel_path in list(conflicts.keys()):
            file_path = Path.cwd() / rel_path
            if resolver.resolve_conflict(file_path, strategy):
                resolved += 1
                click.echo(f"Resolved: {rel_path}")
            else:
                failed += 1
                click.echo(f"Failed to resolve: {rel_path}", err=True)
        
        click.echo(f"Resolved {resolved} conflict(s).")
        if failed > 0:
            click.echo(f"Failed to resolve {failed} conflict(s).", err=True)


@cli.command()
@click.argument('files', nargs=-1, type=click.Path(exists=True))
@click.pass_context
def checkout(ctx, files):
    """Mark local files for editing (like Perforce checkout).
    
    \b
    Examples:
      icloud checkout file.txt           # Checkout single file
      icloud checkout a.txt b.txt        # Checkout multiple files
      icloud checkout subfolder/doc.pdf  # Checkout file in subdirectory
      icloud checkout *.txt              # Checkout all txt files (shell glob)
    
    \b
    Notes:
      - Checked out files will be uploaded on 'icloud submit'
      - Use 'icloud submit' to see current checked out files
      - Use 'icloud revert <file>' to undo checkout
    """
    state = ctx.obj['state']
    
    if not files:
        # Show currently checked out files
        opened_files = state.get_opened_files()
        if not opened_files:
            click.echo("No files checked out.")
            click.echo("Usage: icloud checkout <file1> [file2] ...")
            return
        
        click.echo(f"Checked out files ({len(opened_files)}):")
        for f in opened_files:
            source = state.get_file_source(f)
            if source:
                click.echo(f"  📝 {f} <- {source}")
            else:
                click.echo(f"  📝 {f} (new file)")
        return
    
    added = 0
    for file_path in files:
        path = Path(file_path)
        if not path.exists():
            click.echo(f"File not found: {file_path}", err=True)
            continue
        
        try:
            rel_path = str(path.relative_to(Path.cwd()))
        except ValueError:
            rel_path = str(path)
        
        if rel_path in state.get_opened_files():
            click.echo(f"Already checked out: {rel_path}")
        else:
            state.add_opened_file(rel_path)
            click.echo(f"✓ Checked out: {rel_path}")
            added += 1
    
    if added > 0:
        click.echo(f"\nChecked out {added} file(s). Use 'icloud submit' to upload.")


@cli.command()
@click.argument('files', nargs=-1, type=click.Path(exists=True))
@click.pass_context
def add(ctx, files):
    """Alias for 'checkout' - mark files for editing.
    
    \b
    Examples:
      icloud add file.txt                # Same as 'icloud checkout file.txt'
    """
    # Delegate to checkout
    ctx.invoke(checkout, files=files)


@cli.command()
@click.argument('files', nargs=-1, type=click.Path())
@click.option('--all', '-a', 'upload_all', is_flag=True, default=False,
              help='Upload all checked out files')
@click.option('--folder', '-f', default='Documents',
              help='Remote folder for new files (default: Documents)')
@click.pass_context
def submit(ctx, files, upload_all, folder):
    """Upload local changes to iCloud (like Perforce submit).
    
    \b
    Examples:
      icloud submit                      # Show checked out files
      icloud submit file.txt             # Upload specific file
      icloud submit a.txt b.txt          # Upload multiple files
      icloud submit -a                   # Upload all checked out files
      icloud submit newfile.txt -f root  # Upload new file to root
    
    \b
    Workflow (Perforce-like):
      1. icloud sync -f Documents        # Get latest files
      2. icloud checkout file.txt        # Mark file for editing
      3. (edit file locally)
      4. icloud submit file.txt          # Upload changes
    
    \b
    Or submit all at once:
      icloud submit -a                   # Upload all checked out files
    """
    config = ctx.obj['config']
    state = ctx.obj['state']
    
    opened_files = state.get_opened_files()
    
    # If no files and no flags specified, just show checked out files
    if not files and not upload_all:
        if not opened_files:
            click.echo("No files checked out.")
            click.echo("Use 'icloud checkout <file>' to mark files, or 'icloud reconcile' to scan.")
            return
        
        click.echo(f"📋 Checked out files ({len(opened_files)}):")
        for f in opened_files:
            source = state.get_file_source(f)
            if source:
                click.echo(f"  📝 {f} -> {source}")
            else:
                click.echo(f"  📝 {f} (new file)")
        click.echo()
        click.echo("Use 'icloud submit <file>' or 'icloud submit -a' to upload.")
        return
    
    # Check authentication
    auth = AuthManager(config)
    if not auth.is_authenticated():
        click.echo("Not authenticated. Please run 'icloud login' first.", err=True)
        sys.exit(1)
    
    service = auth.get_service()
    if not service:
        click.echo("Failed to get iCloud service.", err=True)
        sys.exit(1)
    
    sync_manager = SyncManager(service, state, config)
    
    # Handle specific files
    if files:
        success_count = 0
        fail_count = 0
        
        for filename in files:
            file_path = Path(filename)
            
            # Check if file exists
            if not file_path.exists():
                click.echo(f"✗ File not found: {filename}", err=True)
                fail_count += 1
                continue
            
            try:
                rel_path = str(file_path.relative_to(Path.cwd()))
            except ValueError:
                rel_path = str(file_path)
            
            # Auto-checkout if not already
            if rel_path not in opened_files:
                state.add_opened_file(rel_path)
            
            # Check if file is in conflict
            if rel_path in state.get_conflicts():
                click.echo(f"✗ {rel_path}: has conflicts, resolve first", err=True)
                fail_count += 1
                continue
            
            # Show destination
            source = state.get_file_source(rel_path)
            if source:
                click.echo(f"Submitting: {rel_path} -> {source}")
            else:
                click.echo(f"Submitting: {rel_path} -> {folder}/{rel_path}")
            
            success = sync_manager.upload_single_file(rel_path, folder)
            if success:
                state.remove_opened_file(rel_path)
                click.echo(f"✓ Submitted: {rel_path}")
                success_count += 1
            else:
                click.echo(f"✗ Failed: {rel_path}", err=True)
                fail_count += 1
        
        click.echo(f"\nSubmitted {success_count} file(s).", nl=False)
        if fail_count > 0:
            click.echo(f" ({fail_count} failed)", err=True)
        else:
            click.echo("")
        return
    
    # Handle upload all opened files (-a flag)
    if not opened_files:
        click.echo("No files to submit.")
        return
    
    # Check for conflicts
    conflicts = state.get_conflicts()
    conflicted_opened = [f for f in opened_files if f in conflicts]
    if conflicted_opened:
        click.echo(f"⚠️  {len(conflicted_opened)} file(s) have conflicts:")
        for f in conflicted_opened:
            click.echo(f"    {f}")
        click.echo("Resolve conflicts before submitting.")
        sys.exit(1)
    
    click.echo(f"Submitting {len(opened_files)} file(s)...")
    files_uploaded = sync_manager.sync_to_remote(folder)
    
    click.echo(f"✓ Submitted {files_uploaded} file(s).")


@cli.command()
@click.argument('files', nargs=-1, type=click.Path())
@click.option('--all', '-a', 'revert_all', is_flag=True, default=False,
              help='Revert all checked out files')
@click.pass_context
def revert(ctx, files, revert_all):
    """Revert checked out files (undo checkout).
    
    \b
    Examples:
      icloud revert file.txt             # Revert single file
      icloud revert a.txt b.txt          # Revert multiple files
      icloud revert -a                   # Revert all checked out files
    
    \b
    Notes:
      - This removes files from the checkout list
      - Local file changes are NOT reverted (use git or backup)
      - To restore original file, use 'icloud download'
    """
    state = ctx.obj['state']
    opened_files = state.get_opened_files()
    
    if not files and not revert_all:
        click.echo("Usage: icloud revert <file> or icloud revert -a")
        return
    
    if revert_all:
        if not opened_files:
            click.echo("No files to revert.")
            return
        
        count = len(opened_files)
        for f in list(opened_files):
            state.remove_opened_file(f)
        click.echo(f"✓ Reverted {count} file(s).")
        return
    
    reverted = 0
    for filename in files:
        try:
            rel_path = str(Path(filename).relative_to(Path.cwd()))
        except ValueError:
            rel_path = str(filename)
        
        if rel_path in opened_files:
            state.remove_opened_file(rel_path)
            click.echo(f"✓ Reverted: {rel_path}")
            reverted += 1
        else:
            click.echo(f"  Not checked out: {rel_path}")
    
    if reverted > 0:
        click.echo(f"\nReverted {reverted} file(s).")


@cli.command()
@click.pass_context
def info(ctx):
    """Display current status and information.
    
    \b
    Example:
      icloud info
    
    \b
    Shows:
      - Authentication status
      - Opened files (pending upload)
      - Conflicts (if any)
      - Last sync time
    """
    config = ctx.obj['config']
    state = ctx.obj['state']
    
    click.echo("iCloud CLI Status")
    click.echo("=" * 50)
    
    # Authentication status
    auth = AuthManager(config)
    if auth.is_authenticated():
        username = config.get_username() or "Unknown"
        click.echo(f"Authenticated as: {username}")
    else:
        click.echo("Not authenticated. Run 'icloud login' to authenticate.")
    
    click.echo()
    
    # Opened files
    opened_files = state.get_opened_files()
    click.echo(f"Opened files: {len(opened_files)}")
    if opened_files:
        for file_path in opened_files:
            click.echo(f"  - {file_path}")
    
    click.echo()
    
    # Conflicts
    conflicts = state.get_conflicts()
    click.echo(f"Conflicts: {len(conflicts)}")
    if conflicts:
        for file_path, conflict_info in conflicts.items():
            status = conflict_info.get('status', 'unknown')
            click.echo(f"  - {file_path} ({status})")
    
    click.echo()
    
    # Last sync
    last_sync = state.get_last_sync()
    if last_sync:
        click.echo(f"Last sync: {last_sync}")
    else:
        click.echo("Last sync: Never")
    
    click.echo()
    
    # Tracked folders
    tracked_folders = config.get_tracked_folders()
    click.echo(f"Tracked folders: {', '.join(tracked_folders)}")


def main():
    """Main entry point for CLI."""
    cli()


if __name__ == '__main__':
    main()

