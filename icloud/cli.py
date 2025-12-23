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
      icloud login -u your@icloud.com   # Login to iCloud
      icloud sync                        # Download files from Documents
      icloud list                        # List remote files
      
    \b
    Edit & Submit Workflow:
      icloud add file.txt                # Mark file for upload
      icloud submit -a                   # Upload all marked files
      
    \b
    Common folders: Documents, Desktop, root (iCloud Drive root)
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
              help='Remote folder to sync (default: Documents)')
@click.option('--file', '-n', 'filename', help='Specific file name to sync (optional)')
@click.option('--workers', '-w', default=8, type=int,
              help='Number of concurrent workers (default: 8)')
@click.option('--depth', '-d', default=0, type=int,
              help='Max recursion depth (0 = unlimited, 1 = top level only)')
@click.option('--no-exclude', is_flag=True, default=False,
              help='Disable default exclusions (.git, node_modules, etc.)')
@click.pass_context
def sync(ctx, folder, filename, workers, depth, no_exclude):
    """Sync remote files from iCloud.
    
    \b
    Examples:
      icloud sync                        # Sync all from Documents
      icloud sync -f Desktop             # Sync from Desktop folder
      icloud sync -f root                # Sync from iCloud Drive root
      icloud sync -n report.docx         # Sync single file from Documents
      icloud sync -f root -n data.json   # Sync single file from root
      icloud sync -w 16                  # Use 16 concurrent workers
      icloud sync -d 2                   # Only scan 2 levels deep
      icloud sync --no-exclude           # Include .git, node_modules, etc.
    
    \b
    Notes:
      - Files are downloaded to current directory
      - Folder structure is preserved
      - Existing files are skipped (use reconcile to detect changes)
      - Increase workers (-w) for faster downloads on fast networks
      - By default skips .git, node_modules, __pycache__ for speed
      - Use -d to limit depth for faster scanning of large folders
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
    
    if filename:
        click.echo(f"Syncing file '{filename}' from iCloud folder: {folder}")
        success = sync_manager.sync_single_file(folder, filename)
        if success:
            click.echo(f"Downloaded: {filename}")
        else:
            click.echo(f"Failed to download: {filename}", err=True)
            sys.exit(1)
    else:
        depth_info = f", depth: {depth}" if depth > 0 else ""
        click.echo(f"Syncing from iCloud folder: {folder} (workers: {workers}{depth_info})")
        files_downloaded, conflicts = sync_manager.sync_from_remote(folder)
        
        click.echo(f"Downloaded {files_downloaded} file(s).")
        if conflicts > 0:
            click.echo(f"Found {conflicts} conflict(s). Run 'icloud resolve' to resolve them.")


@cli.command('list')
@click.option('--folder', '-f', default='Documents',
              help='Remote folder to list (default: Documents)')
@click.option('--recursive', '-r', is_flag=True, default=False,
              help='List files recursively')
@click.pass_context
def list_files(ctx, folder, recursive):
    """List files in iCloud Drive.
    
    \b
    Examples:
      icloud list                        # List Documents folder
      icloud list -f Desktop             # List Desktop folder
      icloud list -f root                # List iCloud Drive root
      icloud list -r                     # List recursively
      icloud list -f root -r             # List all files from root
    
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
    
    click.echo(f"Listing files in iCloud folder: {folder}")
    click.echo("=" * 60)
    
    if recursive:
        files = sync_manager.list_remote_files_recursive(folder)
    else:
        files = sync_manager.list_remote_files(folder)
    
    if not files:
        click.echo("No files found.")
        return
    
    # Display files
    for file_info in files:
        file_type = file_info.get('type', 'unknown')
        name = file_info.get('name', 'unknown')
        path = file_info.get('path', name)
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
        
        if recursive and path != name:
            click.echo(f"  {icon} {path}{size_str}")
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
def add(ctx, files):
    """Add files to the opened list for submission.
    
    \b
    Examples:
      icloud add file.txt                # Add single file
      icloud add a.txt b.txt c.txt       # Add multiple files
      icloud add subfolder/doc.pdf       # Add file in subdirectory
      icloud add *.txt                   # Add all txt files (shell glob)
    
    \b
    Notes:
      - Added files will be uploaded on next 'icloud submit -a'
      - Use 'icloud submit' to see current opened files
    """
    state = ctx.obj['state']
    
    if not files:
        click.echo("No files specified. Usage: icloud add <file1> [file2] ...")
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
            click.echo(f"Already opened: {rel_path}")
        else:
            state.add_opened_file(rel_path)
            click.echo(f"Added: {rel_path}")
            added += 1
    
    if added > 0:
        click.echo(f"Added {added} file(s) to opened list.")


@cli.command()
@click.option('--folder', '-f', default='Documents',
              help='Remote folder to upload to (default: Documents)')
@click.option('--file', '-n', 'filename', help='Specific file to upload (optional)')
@click.option('--all', '-a', 'upload_all', is_flag=True, default=False,
              help='Upload all opened files')
@click.pass_context
def submit(ctx, folder, filename, upload_all):
    """Upload local changes to iCloud.
    
    \b
    Examples:
      icloud submit                      # Show opened files list
      icloud submit -a                   # Upload all opened files
      icloud submit -n file.txt          # Upload specific file
      icloud submit -n doc.pdf -f root   # Upload to root (for new files)
    
    \b
    Notes:
      - Files are uploaded to their original iCloud location
      - The -f option is only used as fallback for new files
      - Use 'icloud add' to mark files for upload first
    
    \b
    Workflow:
      1. icloud sync                     # Download files
      2. (edit files locally)
      3. icloud add <files>              # Mark for upload
      4. icloud submit -a                # Upload changes
    """
    config = ctx.obj['config']
    state = ctx.obj['state']
    
    opened_files = state.get_opened_files()
    
    # If no flags specified, just show opened files
    if not filename and not upload_all:
        if not opened_files:
            click.echo("No files to submit.")
            click.echo("Use 'icloud add <file>' to add files, or 'icloud reconcile' to scan for changes.")
            return
        
        click.echo(f"Opened files ({len(opened_files)}):")
        for f in opened_files:
            # Show source path if available
            source = state.get_file_source(f)
            if source:
                click.echo(f"  📄 {f} -> {source}")
            else:
                click.echo(f"  📄 {f} (new file)")
        click.echo()
        click.echo("Use 'icloud submit -a' to upload all, or 'icloud submit -n <file>' to upload specific file.")
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
    
    # Handle single file upload
    if filename:
        if filename not in opened_files:
            # Auto-add the file if it exists
            file_path = Path(filename)
            if file_path.exists():
                state.add_opened_file(filename)
                click.echo(f"Added {filename} to opened list.")
            else:
                click.echo(f"File not found: {filename}", err=True)
                sys.exit(1)
        
        # Check if file is in conflict
        if filename in state.get_conflicts():
            click.echo(f"File {filename} has conflicts. Please resolve first.", err=True)
            sys.exit(1)
        
        # Show source path if available
        source = state.get_file_source(filename)
        if source:
            click.echo(f"Uploading {filename} -> {source}")
        else:
            click.echo(f"Uploading {filename} to iCloud folder: {folder}")
        
        success = sync_manager.upload_single_file(filename, folder)
        if success:
            state.remove_opened_file(filename)
            click.echo(f"Successfully uploaded: {filename}")
        else:
            click.echo(f"Failed to upload: {filename}", err=True)
            sys.exit(1)
        return
    
    # Handle upload all opened files
    if not opened_files:
        click.echo("No files to submit. Run 'icloud add <file>' or 'icloud reconcile' first.")
        return
    
    # Check for conflicts
    conflicts = state.get_conflicts()
    conflicted_opened = [f for f in opened_files if f in conflicts]
    if conflicted_opened:
        click.echo(f"Warning: {len(conflicted_opened)} opened file(s) have conflicts:")
        for f in conflicted_opened:
            click.echo(f"  ⚠️  {f}")
        click.echo("Please resolve conflicts before submitting.")
        sys.exit(1)
    
    click.echo(f"Submitting {len(opened_files)} file(s) to iCloud...")
    files_uploaded = sync_manager.sync_to_remote(folder)
    
    click.echo(f"Successfully uploaded {files_uploaded} file(s).")


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

