"""Configuration management for iCloud CLI."""

import json
import os
from pathlib import Path
from typing import List, Optional, Dict, Any


class Config:
    """Manages configuration for iCloud CLI."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize config manager.
        
        Args:
            config_dir: Directory to store config files. Defaults to ~/.icloud
        """
        if config_dir is None:
            config_dir = Path.home() / ".icloud"
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "config.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._config: Dict[str, Any] = {}
        self.load()
    
    def load(self) -> None:
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._config = {}
        else:
            self._config = {}
    
    def save(self) -> None:
        """Save configuration to file."""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.
        
        Args:
            key: Configuration key (supports dot notation, e.g., 'auth.token')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value.
        
        Args:
            key: Configuration key (supports dot notation)
            value: Value to set
        """
        keys = key.split('.')
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
        self.save()
    
    def get_tracked_folders(self) -> List[str]:
        """Get list of tracked folders.
        
        Returns:
            List of folder names to sync
        """
        folders = self.get('tracked_folders', ['Documents'])
        if not isinstance(folders, list):
            return ['Documents']
        return folders
    
    def set_tracked_folders(self, folders: List[str]) -> None:
        """Set list of tracked folders.
        
        Args:
            folders: List of folder names to sync
        """
        self.set('tracked_folders', folders)
    
    def get_auth_token(self) -> Optional[str]:
        """Get authentication token.
        
        Returns:
            Auth token or None
        """
        return self.get('auth.token')
    
    def set_auth_token(self, token: str) -> None:
        """Set authentication token.
        
        Args:
            token: Auth token to save
        """
        self.set('auth.token', token)
    
    def get_username(self) -> Optional[str]:
        """Get username.
        
        Returns:
            Username or None
        """
        return self.get('auth.username')
    
    def set_username(self, username: str) -> None:
        """Set username.
        
        Args:
            username: Username to save
        """
        self.set('auth.username', username)
    
    def clear_auth(self) -> None:
        """Clear authentication data."""
        if 'auth' in self._config:
            del self._config['auth']
            self.save()
    
    def get_china_mainland(self) -> Optional[bool]:
        """Get China mainland region preference.
        
        Returns:
            True if using China mainland endpoint, False for international, None if not set
        """
        return self.get('auth.china_mainland')
    
    def set_china_mainland(self, china_mainland: bool) -> None:
        """Set China mainland region preference.
        
        Args:
            china_mainland: Whether to use China mainland endpoint
        """
        self.set('auth.china_mainland', china_mainland)

