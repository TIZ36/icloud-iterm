"""State management for tracking opened files and conflicts."""

import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime


class State:
    """Manages local state for iCloud sync."""
    
    def __init__(self, state_dir: Optional[Path] = None):
        """Initialize state manager.
        
        Args:
            state_dir: Directory to store state file. Defaults to .icloud in current directory
        """
        if state_dir is None:
            state_dir = Path.cwd() / ".icloud"
        self.state_dir = Path(state_dir)
        self.state_file = self.state_dir / "state.json"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._state: Dict = {
            "opened_files": [],
            "conflicts": {},
            "last_sync": None,
            "tracked_folders": [],
            "file_hashes": {},
            "file_sources": {}  # Maps local file path -> remote iCloud path
        }
        self.load()
    
    def load(self) -> None:
        """Load state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self._state.update(loaded)
            except (json.JSONDecodeError, IOError):
                pass
    
    def save(self) -> None:
        """Save state to file."""
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self._state, f, indent=2, ensure_ascii=False)
    
    def add_opened_file(self, file_path: str) -> None:
        """Add a file to opened files list.
        
        Args:
            file_path: Relative path to file
        """
        if file_path not in self._state["opened_files"]:
            self._state["opened_files"].append(file_path)
            self.save()
    
    def remove_opened_file(self, file_path: str) -> None:
        """Remove a file from opened files list.
        
        Args:
            file_path: Relative path to file
        """
        if file_path in self._state["opened_files"]:
            self._state["opened_files"].remove(file_path)
            self.save()
    
    def get_opened_files(self) -> List[str]:
        """Get list of opened files.
        
        Returns:
            List of opened file paths
        """
        return self._state["opened_files"].copy()
    
    def clear_opened_files(self) -> None:
        """Clear all opened files."""
        self._state["opened_files"] = []
        self.save()
    
    def add_conflict(self, file_path: str, local_hash: str, remote_hash: str) -> None:
        """Add a conflict record.
        
        Args:
            file_path: Relative path to file
            local_hash: Hash of local file
            remote_hash: Hash of remote file
        """
        self._state["conflicts"][file_path] = {
            "local_hash": local_hash,
            "remote_hash": remote_hash,
            "status": "needs_resolution"
        }
        self.save()
    
    def remove_conflict(self, file_path: str) -> None:
        """Remove a conflict record.
        
        Args:
            file_path: Relative path to file
        """
        if file_path in self._state["conflicts"]:
            del self._state["conflicts"][file_path]
            self.save()
    
    def get_conflicts(self) -> Dict[str, Dict]:
        """Get all conflicts.
        
        Returns:
            Dictionary of conflict records
        """
        return self._state["conflicts"].copy()
    
    def has_conflicts(self) -> bool:
        """Check if there are any conflicts.
        
        Returns:
            True if conflicts exist
        """
        return len(self._state["conflicts"]) > 0
    
    def set_file_hash(self, file_path: str, file_hash: str) -> None:
        """Set hash for a file.
        
        Args:
            file_path: Relative path to file
            file_hash: SHA256 hash of file
        """
        self._state["file_hashes"][file_path] = file_hash
        self.save()
    
    def get_file_hash(self, file_path: str) -> Optional[str]:
        """Get hash for a file.
        
        Args:
            file_path: Relative path to file
            
        Returns:
            File hash or None
        """
        return self._state["file_hashes"].get(file_path)
    
    def set_file_source(self, local_path: str, remote_path: str) -> None:
        """Set the remote iCloud path for a local file.
        
        Args:
            local_path: Relative local path to file
            remote_path: Full remote iCloud path (e.g., "Documents/subfolder/file.txt")
        """
        if "file_sources" not in self._state:
            self._state["file_sources"] = {}
        self._state["file_sources"][local_path] = remote_path
        self.save()
    
    def get_file_source(self, local_path: str) -> Optional[str]:
        """Get the remote iCloud path for a local file.
        
        Args:
            local_path: Relative local path to file
            
        Returns:
            Remote iCloud path or None if not tracked
        """
        if "file_sources" not in self._state:
            return None
        return self._state["file_sources"].get(local_path)
    
    def remove_file_source(self, local_path: str) -> None:
        """Remove file source tracking for a local file.
        
        Args:
            local_path: Relative local path to file
        """
        if "file_sources" in self._state and local_path in self._state["file_sources"]:
            del self._state["file_sources"][local_path]
            self.save()
    
    def get_all_file_sources(self) -> Dict[str, str]:
        """Get all file source mappings.
        
        Returns:
            Dictionary mapping local paths to remote paths
        """
        if "file_sources" not in self._state:
            return {}
        return self._state["file_sources"].copy()
    
    def update_last_sync(self) -> None:
        """Update last sync timestamp."""
        self._state["last_sync"] = datetime.utcnow().isoformat() + "Z"
        self.save()
    
    def get_last_sync(self) -> Optional[str]:
        """Get last sync timestamp.
        
        Returns:
            ISO format timestamp or None
        """
        return self._state.get("last_sync")
    
    @staticmethod
    def compute_file_hash(file_path: Path) -> str:
        """Compute SHA256 hash of a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            SHA256 hash as hex string
        """
        sha256 = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256.update(chunk)
        except IOError:
            return ""
        return sha256.hexdigest()

