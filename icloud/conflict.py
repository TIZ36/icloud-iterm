"""Conflict detection and resolution module."""

import shutil
from pathlib import Path
from typing import Optional, Tuple, List
from difflib import unified_diff

from .state import State


class ConflictResolver:
    """Handles conflict detection and resolution."""
    
    # Text file extensions
    TEXT_EXTENSIONS = {
        '.txt', '.py', '.js', '.ts', '.json', '.xml', '.html', '.css',
        '.md', '.yml', '.yaml', '.ini', '.conf', '.cfg', '.sh', '.bat',
        '.c', '.cpp', '.h', '.hpp', '.java', '.go', '.rs', '.rb', '.php',
        '.sql', '.r', '.m', '.swift', '.kt', '.scala', '.clj', '.hs',
        '.lua', '.pl', '.pm', '.vim', '.el', '.lisp', '.scm', '.rkt'
    }
    
    def __init__(self, state: State):
        """Initialize conflict resolver.
        
        Args:
            state: State instance for tracking conflicts
        """
        self.state = state
    
    def is_text_file(self, file_path: Path) -> bool:
        """Check if file is a text file.
        
        Args:
            file_path: Path to file
            
        Returns:
            True if file appears to be text
        """
        if file_path.suffix.lower() in self.TEXT_EXTENSIONS:
            return True
        
        # Try to read first few bytes to detect text
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(512)
                # Check if all bytes are printable or common whitespace
                return all(b < 128 and (32 <= b or b in (9, 10, 13)) for b in chunk)
        except IOError:
            return False
    
    def detect_conflict(self, local_path: Path, remote_content: bytes, 
                       local_hash: str, remote_hash: str) -> bool:
        """Detect if there's a conflict between local and remote versions.
        
        Args:
            local_path: Path to local file
            remote_content: Content of remote file
            local_hash: Hash of local file
            remote_hash: Hash of remote file
            
        Returns:
            True if conflict exists
        """
        if local_hash == remote_hash:
            return False
        
        # Check if local file exists and has been modified
        if not local_path.exists():
            return False
        
        current_local_hash = State.compute_file_hash(local_path)
        stored_hash = self.state.get_file_hash(str(local_path.relative_to(Path.cwd())))
        
        # Conflict if local was modified and remote was also modified
        return (current_local_hash != stored_hash and 
                current_local_hash != remote_hash and
                remote_hash != stored_hash)
    
    def merge_text_files(self, base_content: bytes, local_content: bytes, 
                        remote_content: bytes) -> Tuple[bytes, bool]:
        """Merge text files using 3-way merge (simplified).
        
        Args:
            base_content: Base version (common ancestor)
            local_content: Local version
            remote_content: Remote version
            
        Returns:
            Tuple of (merged_content, success)
        """
        try:
            base_text = base_content.decode('utf-8')
            local_text = local_content.decode('utf-8')
            remote_text = remote_content.decode('utf-8')
        except UnicodeDecodeError:
            return b"", False
        
        # Simple 3-way merge: if local and remote are same, use that
        if local_text == remote_text:
            return local_content, True
        
        # If base equals local, use remote
        if base_text == local_text:
            return remote_content, True
        
        # If base equals remote, use local
        if base_text == remote_text:
            return local_content, True
        
        # Otherwise, create merge conflict markers
        merged_lines = []
        merged_lines.append("<<<<<<< LOCAL\n")
        merged_lines.extend(local_text.splitlines(keepends=True))
        merged_lines.append("=======\n")
        merged_lines.extend(remote_text.splitlines(keepends=True))
        merged_lines.append(">>>>>>> REMOTE\n")
        
        merged_content = "".join(merged_lines).encode('utf-8')
        return merged_content, False  # False indicates manual resolution needed
    
    def resolve_conflict(self, file_path: Path, strategy: str = "auto",
                         sync_manager=None) -> bool:
        """Resolve a conflict for a file.
        
        Args:
            file_path: Path to conflicted file
            strategy: Resolution strategy ('auto', 'local', 'remote', 'merge')
            sync_manager: SyncManager instance (required for 'remote' strategy)
            
        Returns:
            True if resolved successfully
        """
        rel_path = str(file_path.relative_to(Path.cwd()))
        conflict = self.state.get_conflicts().get(rel_path)
        
        if not conflict:
            return False
        
        if strategy == "local":
            # Keep local version - just remove conflict marker
            new_hash = State.compute_file_hash(file_path)
            self.state.set_file_hash(rel_path, new_hash)
            self.state.remove_conflict(rel_path)
            print(f"  Kept local version: {rel_path}")
            return True
        
        if strategy == "remote":
            # Keep remote version - need to re-download from iCloud
            if sync_manager is None:
                print(f"  Error: sync_manager required for 'remote' strategy")
                return False
            
            # Get remote source path from state
            remote_source = self.state.get_file_source(rel_path)
            if not remote_source:
                print(f"  Error: Cannot find remote source for {rel_path}")
                return False
            
            # Create backup of local file
            backup_path = self.create_backup(file_path)
            print(f"  Backup created: {backup_path}")
            
            # Download remote version
            try:
                if sync_manager.download_single_file(remote_source, file_path):
                    new_hash = State.compute_file_hash(file_path)
                    self.state.set_file_hash(rel_path, new_hash)
                    self.state.remove_conflict(rel_path)
                    print(f"  Downloaded remote version: {rel_path}")
                    return True
                else:
                    print(f"  Failed to download remote version: {rel_path}")
                    return False
            except Exception as e:
                print(f"  Error downloading remote: {e}")
                return False
        
        if strategy == "auto":
            # Auto strategy: compare local and remote modification times
            # If we have conflict info with timestamps, use that
            local_hash = conflict.get('local_hash', '')
            remote_hash = conflict.get('remote_hash', '')
            
            # Default: keep local (safer choice - user's changes preserved)
            print(f"  Auto-resolving: keeping local version for {rel_path}")
            new_hash = State.compute_file_hash(file_path)
            self.state.set_file_hash(rel_path, new_hash)
            self.state.remove_conflict(rel_path)
            return True
        
        if strategy == "merge":
            if self.is_text_file(file_path):
                # For text files without base version, just show both versions
                print(f"  Text file {rel_path} needs manual merge.")
                print(f"  Use 'local' or 'remote' strategy, or edit the file manually.")
                return False
            else:
                print(f"  Binary file {rel_path} cannot be merged. Use 'local' or 'remote'.")
                return False
        
        return False
    
    def create_backup(self, file_path: Path) -> Path:
        """Create a backup of a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            Path to backup file
        """
        backup_path = file_path.with_suffix(file_path.suffix + '.backup')
        if file_path.exists():
            shutil.copy2(file_path, backup_path)
        return backup_path

