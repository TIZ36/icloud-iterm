"""File synchronization module."""

import time
from pathlib import Path
from typing import List, Optional, Dict, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from pyicloud import PyiCloudService
from pyicloud.services.drive import DriveService

from .state import State
from .config import Config
from .conflict import ConflictResolver
from .logger import logger

# Default concurrent download settings
DEFAULT_MAX_WORKERS = 8
DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1MB chunks for faster streaming
# Default folders to skip during sync (speeds up scanning)
DEFAULT_EXCLUDE_PATTERNS = {'.git', 'node_modules', '__pycache__', '.svn', '.hg'}


class SyncManager:
    """Manages file synchronization with iCloud."""
    
    def __init__(self, service: PyiCloudService, state: State, config: Config,
                 max_workers: int = DEFAULT_MAX_WORKERS,
                 exclude_patterns: Optional[set] = None,
                 max_depth: int = 0):
        """Initialize sync manager.
        
        Args:
            service: Authenticated PyiCloudService instance
            state: State instance
            config: Config instance
            max_workers: Maximum concurrent download/upload workers
            exclude_patterns: Set of folder names to exclude (default: .git, node_modules, etc.)
            max_depth: Maximum recursion depth (0 = unlimited)
        """
        self.service = service
        self.state = state
        self.config = config
        self.drive: Optional[DriveService] = None
        self.resolver = ConflictResolver(state)
        self.max_workers = max_workers
        self._state_lock = threading.Lock()  # Thread-safe state updates
        self.exclude_patterns = exclude_patterns if exclude_patterns is not None else DEFAULT_EXCLUDE_PATTERNS
        self.max_depth = max_depth
        
        if hasattr(service, 'drive'):
            self.drive = service.drive
    
    def get_drive(self) -> DriveService:
        """Get Drive service.
        
        Returns:
            DriveService instance
            
        Raises:
            RuntimeError: If drive service is not available
        """
        if self.drive is None:
            raise RuntimeError("iCloud Drive service not available. Please login first.")
        return self.drive
    
    def list_remote_files(self, folder_name: str = "Documents") -> List[Dict]:
        """List files in remote iCloud folder.
        
        Args:
            folder_name: Name of folder to list (e.g., "Documents", "Desktop")
            
        Returns:
            List of file metadata dictionaries
        """
        drive = self.get_drive()
        try:
            # Get root folder
            logger.debug(f"Getting drive root...")
            root = drive.root
            
            # Navigate to requested folder
            folder = root
            if folder_name != "root":
                # Try to find folder using get_children() which returns DriveNode objects
                logger.debug(f"Getting root children to find folder '{folder_name}'...")
                children = root.get_children()
                for item in children:
                    item_name = getattr(item, 'name', str(item))
                    item_type = getattr(item, 'type', 'unknown')
                    if item_name == folder_name and item_type in ("folder", "FOLDER"):
                        folder = item
                        break
                else:
                    # Try direct access with bracket notation
                    try:
                        folder = root[folder_name]
                    except (KeyError, Exception):
                        # Folder doesn't exist, return empty list
                        logger.warning(f"Folder '{folder_name}' not found")
                        return []
            
            files = []
            # Use get_children() which returns DriveNode objects
            logger.debug(f"Getting children of folder '{folder_name}'...")
            children = folder.get_children()
            logger.debug(f"Found {len(list(children)) if hasattr(children, '__len__') else 'unknown'} children")
            for item in children:
                item_name = getattr(item, 'name', str(item))
                item_type = getattr(item, 'type', 'unknown')
                # Normalize type to lowercase
                if isinstance(item_type, str):
                    item_type = item_type.lower()
                
                files.append({
                    'name': item_name,
                    'path': item_name,
                    'size': getattr(item, 'size', 0),
                    'modified': getattr(item, 'date_modified', None),
                    'type': item_type,
                    'item': item
                })
            
            return files
        except Exception as e:
            logger.error(f"Error listing remote files: {e}")
            print(f"Error listing remote files: {e}")
            return []
    
    def list_remote_files_recursive(self, folder_name: str = "Documents", 
                                     prefix: str = "") -> List[Dict]:
        """List files in remote iCloud folder recursively.
        
        Args:
            folder_name: Name of folder to list
            prefix: Path prefix for nested items
            
        Returns:
            List of file metadata dictionaries with full paths
        """
        files = []
        items = self.list_remote_files(folder_name)
        
        for item in items:
            item_name = item.get('name', '')
            item_type = item.get('type', 'unknown')
            
            # Build full path
            if prefix:
                full_path = f"{prefix}/{item_name}"
            else:
                full_path = item_name
            
            item['path'] = full_path
            files.append(item)
            
            # Recursively list subdirectories
            if item_type in ('folder', 'FOLDER'):
                folder_node = item.get('item')
                if folder_node:
                    sub_files = self._list_folder_recursive(folder_node, full_path)
                    files.extend(sub_files)
        
        return files
    
    def _list_folder_recursive(self, folder_node, prefix: str) -> List[Dict]:
        """Recursively list contents of a folder node.
        
        Args:
            folder_node: DriveNode folder object
            prefix: Path prefix
            
        Returns:
            List of file metadata dictionaries
        """
        files = []
        try:
            children = folder_node.get_children()
        except Exception as e:
            logger.error(f"Error getting children: {e}")
            return []
        
        for item in children:
            item_name = getattr(item, 'name', str(item))
            item_type = getattr(item, 'type', 'unknown')
            if isinstance(item_type, str):
                item_type = item_type.lower()
            
            full_path = f"{prefix}/{item_name}"
            
            file_info = {
                'name': item_name,
                'path': full_path,
                'size': getattr(item, 'size', 0),
                'modified': getattr(item, 'date_modified', None),
                'type': item_type,
                'item': item
            }
            files.append(file_info)
            
            if item_type in ('folder', 'FOLDER'):
                sub_files = self._list_folder_recursive(item, full_path)
                files.extend(sub_files)
        
        return files
    
    def sync_single_file(self, folder_name: str, filename: str,
                         local_base: Optional[Path] = None) -> bool:
        """Sync a single file from iCloud.
        
        Args:
            folder_name: Remote folder name
            filename: Name of the file to sync (can include path like "subfolder/file.txt")
            local_base: Local base directory. Defaults to current directory
            
        Returns:
            True if download successful
        """
        if local_base is None:
            local_base = Path.cwd()
        
        local_base = Path(local_base)
        
        drive = self.get_drive()
        root = drive.root
        
        try:
            # Navigate to the folder
            if folder_name == "root":
                folder = root
            else:
                try:
                    folder = root[folder_name]
                except (KeyError, Exception):
                    logger.error(f"Folder '{folder_name}' not found")
                    return False
            
            # Parse filename path (support "subfolder/file.txt" format)
            path_parts = filename.split('/')
            target_name = path_parts[-1]
            subfolder_path = path_parts[:-1]
            
            # Navigate through subfolders
            current_folder = folder
            for subfolder in subfolder_path:
                try:
                    current_folder = current_folder[subfolder]
                except (KeyError, Exception):
                    logger.error(f"Subfolder '{subfolder}' not found")
                    return False
            
            # Find the file
            target_item = None
            children = current_folder.get_children()
            for item in children:
                item_name = getattr(item, 'name', str(item))
                if item_name == target_name:
                    target_item = item
                    break
            
            if target_item is None:
                logger.error(f"File '{filename}' not found in folder")
                return False
            
            # Check if it's a folder
            item_type = getattr(target_item, 'type', 'unknown')
            if isinstance(item_type, str):
                item_type = item_type.lower()
            
            if item_type in ('folder', 'FOLDER'):
                logger.error(f"'{filename}' is a folder, not a file")
                return False
            
            if item_type in ('app_library', 'app'):
                logger.error(f"'{filename}' is an app library and cannot be downloaded")
                return False
            
            # Create local path (preserve subfolder structure)
            local_path = local_base / filename
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Download the file
            if self.download_file(target_item, local_path):
                # Update state
                rel_path = str(local_path.relative_to(Path.cwd()))
                new_hash = State.compute_file_hash(local_path)
                self.state.set_file_hash(rel_path, new_hash)
                # Record file source (remote iCloud path)
                # Always use folder_name/filename format, including for root
                remote_source = f"{folder_name}/{filename}"
                self.state.set_file_source(rel_path, remote_source)
                return True
            
            return False
            
        except Exception as e:
            logger.exception(f"Error syncing file '{filename}'")
            return False

    def download_file(self, remote_item, local_path: Path, max_retries: int = 3,
                       chunk_size: int = DEFAULT_CHUNK_SIZE) -> bool:
        """Download a file from iCloud with retry logic.
        
        Args:
            remote_item: Remote file item from pyicloud
            local_path: Local path to save file
            max_retries: Maximum number of retry attempts
            chunk_size: Size of chunks for streaming download
            
        Returns:
            True if download successful
        """
        for attempt in range(max_retries):
            try:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Download file with larger chunk size for better performance
                with open(local_path, 'wb') as f:
                    response = remote_item.open(stream=True)
                    # Use iter_content if available for better chunking
                    if hasattr(response, 'iter_content'):
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if chunk:
                                f.write(chunk)
                    else:
                        for chunk in response:
                            f.write(chunk)
                
                logger.debug(f"Successfully downloaded {remote_item.name}")
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Download failed for {remote_item.name}, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Error downloading {remote_item.name} after {max_retries} attempts: {e}")
                    print(f"Error downloading {remote_item.name}: {e}")
                    return False
        return False
    
    def upload_file(self, local_path: Path, remote_folder_name: str = "Documents", 
                   remote_subpath: str = "", max_retries: int = 3) -> bool:
        """Upload a file to iCloud with retry logic, overwriting existing file.
        
        Args:
            local_path: Local file path
            remote_folder_name: Remote folder name (e.g., "Documents", "root")
            remote_subpath: Subpath within the folder (e.g., "subfolder/another")
            max_retries: Maximum number of retry attempts
            
        Returns:
            True if upload successful
        """
        if not local_path.exists():
            logger.error(f"File not found for upload: {local_path}")
            return False
        
        filename = local_path.name
        
        for attempt in range(max_retries):
            try:
                drive = self.get_drive()
                root = drive.root
                
                # Navigate to target folder
                if remote_folder_name == "root":
                    target_folder = root
                else:
                    try:
                        target_folder = root[remote_folder_name]
                    except (KeyError, Exception):
                        # Create folder if it doesn't exist
                        logger.info(f"Creating folder: {remote_folder_name}")
                        target_folder = root.mkdir(remote_folder_name)
                
                # Navigate through subpath if specified
                if remote_subpath:
                    for subfolder_name in remote_subpath.split('/'):
                        if not subfolder_name:
                            continue
                        try:
                            target_folder = target_folder[subfolder_name]
                        except (KeyError, Exception):
                            # Create subfolder if it doesn't exist
                            logger.info(f"Creating subfolder: {subfolder_name}")
                            target_folder = target_folder.mkdir(subfolder_name)
                
                # Check if file already exists and delete it first (to allow overwrite)
                try:
                    children = target_folder.get_children()
                    for child in children:
                        child_name = getattr(child, 'name', str(child))
                        child_type = getattr(child, 'type', 'unknown')
                        if isinstance(child_type, str):
                            child_type = child_type.lower()
                        
                        if child_name == filename and child_type not in ('folder', 'app_library', 'app'):
                            logger.info(f"Deleting existing file for overwrite: {filename}")
                            try:
                                child.delete()
                                # Wait a moment for deletion to propagate
                                time.sleep(0.5)
                            except Exception as del_e:
                                logger.warning(f"Failed to delete existing file: {del_e}")
                            break
                except Exception as e:
                    logger.warning(f"Could not check for existing file: {e}")
                
                # Upload file - pyicloud uses file_object.name as the remote filename
                with open(local_path, 'rb') as f:
                    target_folder.upload(f)
                
                logger.debug(f"Successfully uploaded {local_path}")
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Upload failed for {local_path}, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Error uploading {local_path} after {max_retries} attempts: {e}")
                    print(f"Error uploading {local_path}: {e}")
                    return False
        return False
    
    def sync_from_remote(self, folder_name: str = "Documents", 
                        local_base: Optional[Path] = None) -> Tuple[int, int]:
        """Sync files from iCloud to local with concurrent downloads.
        
        Args:
            folder_name: Remote folder name
            local_base: Local base directory. Defaults to current directory
            
        Returns:
            Tuple of (files_downloaded, conflicts_found)
        """
        if local_base is None:
            local_base = Path.cwd()
        
        local_base = Path(local_base)
        local_base.mkdir(parents=True, exist_ok=True)
        
        # Phase 1: Collect all files to download (including from subfolders)
        download_tasks = []
        conflicts_found = 0
        
        print(f"Scanning remote folder: {folder_name}...")
        import sys
        sys.stdout.flush()  # Ensure output is visible immediately
        conflicts_found = self._collect_download_tasks(
            folder_name, local_base, download_tasks
        )
        print(f"Scan complete. Found {len(download_tasks)} file(s) to process.")
        sys.stdout.flush()
        
        if not download_tasks:
            print("No new files to download.")
            self.state.update_last_sync()
            return 0, conflicts_found
        
        print(f"Found {len(download_tasks)} file(s) to download. Starting concurrent download...")
        
        # Phase 2: Concurrent download
        files_downloaded = 0
        failed_downloads = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all download tasks
            future_to_task = {
                executor.submit(
                    self._download_task,
                    task['item'],
                    task['local_path'],
                    task['rel_path'],
                    task['remote_source']
                ): task
                for task in download_tasks
            }
            
            # Process completed downloads
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    success = future.result()
                    if success:
                        files_downloaded += 1
                        print(f"Downloaded: {task['rel_path']}")
                    else:
                        failed_downloads += 1
                        print(f"Failed: {task['rel_path']}")
                except Exception as e:
                    failed_downloads += 1
                    logger.exception(f"Download exception for {task['rel_path']}")
                    print(f"Error: {task['rel_path']}: {e}")
        
        if failed_downloads > 0:
            print(f"Warning: {failed_downloads} file(s) failed to download.")
        
        self.state.update_last_sync()
        return files_downloaded, conflicts_found
    
    def _collect_download_tasks(self, folder_name: str, local_base: Path,
                                 download_tasks: List[Dict]) -> int:
        """Collect all files that need to be downloaded.
        
        Args:
            folder_name: Remote folder name
            local_base: Local base directory
            download_tasks: List to append download tasks to
            
        Returns:
            Number of conflicts found
        """
        import sys
        conflicts_found = 0
        print(f"  Listing files in '{folder_name}'...", end=" ", flush=True)
        remote_files = self.list_remote_files(folder_name)
        print(f"found {len(remote_files)} items.")
        sys.stdout.flush()
        
        for file_info in remote_files:
            file_type = file_info['type']
            
            # Skip app_library types (can't be downloaded)
            if file_type in ('app_library', 'app'):
                continue
            
            if file_type == 'folder':
                # Check if folder should be excluded
                if file_info['name'] in self.exclude_patterns:
                    print(f"  Skipping excluded folder: {file_info['name']}")
                    continue
                    
                # Recursively collect from subdirectories
                sub_local = local_base / file_info['name']
                folder_item = file_info.get('item')
                if folder_item:
                    sub_remote_path = f"{folder_name}/{file_info['name']}"
                    sub_conflicts = self._collect_folder_tasks_recursive(
                        folder_item, sub_local, sub_remote_path, download_tasks,
                        current_depth=1
                    )
                    conflicts_found += sub_conflicts
                continue
            
            local_path = local_base / file_info['name']
            rel_path = str(local_path.relative_to(Path.cwd()))
            remote_source = f"{folder_name}/{file_info['name']}"
            
            # Record file source mapping even if file exists
            if not self.state.get_file_source(rel_path):
                self.state.set_file_source(rel_path, remote_source)
            
            # Compute remote hash (simplified - use file size and name)
            remote_hash = f"{file_info['name']}_{file_info.get('size', 0)}"
            
            # Check if file exists locally
            if local_path.exists():
                local_hash = State.compute_file_hash(local_path)
                stored_hash = self.state.get_file_hash(rel_path)
                
                # Check for conflicts
                if (stored_hash and local_hash != stored_hash and 
                    self.resolver.detect_conflict(local_path, b"", local_hash, remote_hash)):
                    self.state.add_conflict(rel_path, local_hash, remote_hash)
                    conflicts_found += 1
                    print(f"Conflict detected: {rel_path}")
                continue
            
            # Add to download tasks
            download_tasks.append({
                'item': file_info['item'],
                'local_path': local_path,
                'rel_path': rel_path,
                'remote_source': remote_source
            })
        
        return conflicts_found
    
    def _collect_folder_tasks_recursive(self, folder_node, local_base: Path,
                                         remote_path_prefix: str,
                                         download_tasks: List[Dict],
                                         current_depth: int = 0) -> int:
        """Recursively collect download tasks from a folder.
        
        Args:
            folder_node: DriveNode folder object
            local_base: Local base directory
            remote_path_prefix: Remote path prefix for tracking file sources
            download_tasks: List to append download tasks to
            current_depth: Current recursion depth
            
        Returns:
            Number of conflicts found
        """
        # Check max depth
        if self.max_depth > 0 and current_depth > self.max_depth:
            folder_name = getattr(folder_node, 'name', 'unknown')
            print(f"  Max depth reached, skipping: {folder_name}")
            return 0
        
        local_base.mkdir(parents=True, exist_ok=True)
        conflicts_found = 0
        
        try:
            # Show folder being scanned
            folder_name = getattr(folder_node, 'name', 'unknown')
            print(f"  Scanning subfolder: {folder_name}...", end=" ", flush=True)
            children = folder_node.get_children()
            children_list = list(children)  # Convert to list to get count
            print(f"found {len(children_list)} items.")
        except Exception as e:
            logger.error(f"Error getting children of folder: {e}")
            print(f"error: {e}")
            return 0
        
        for item in children_list:
            item_name = getattr(item, 'name', str(item))
            item_type = getattr(item, 'type', 'unknown')
            if isinstance(item_type, str):
                item_type = item_type.lower()
            
            # Skip app_library types
            if item_type in ('app_library', 'app'):
                continue
            
            if item_type == 'folder':
                # Check if folder should be excluded
                if item_name in self.exclude_patterns:
                    print(f"  Skipping excluded folder: {item_name}")
                    continue
                    
                # Recursively collect from subdirectory
                sub_local = local_base / item_name
                sub_remote_path = f"{remote_path_prefix}/{item_name}"
                sub_conflicts = self._collect_folder_tasks_recursive(
                    item, sub_local, sub_remote_path, download_tasks,
                    current_depth=current_depth + 1
                )
                conflicts_found += sub_conflicts
                continue
            
            # It's a file
            local_path = local_base / item_name
            try:
                rel_path = str(local_path.relative_to(Path.cwd()))
            except ValueError:
                rel_path = str(local_path)
            
            # Record file source mapping
            remote_source = f"{remote_path_prefix}/{item_name}"
            if not self.state.get_file_source(rel_path):
                self.state.set_file_source(rel_path, remote_source)
            
            # Compute remote hash
            item_size = getattr(item, 'size', 0)
            remote_hash = f"{item_name}_{item_size}"
            
            # Check if file exists locally
            if local_path.exists():
                local_hash = State.compute_file_hash(local_path)
                stored_hash = self.state.get_file_hash(rel_path)
                
                if (stored_hash and local_hash != stored_hash and 
                    self.resolver.detect_conflict(local_path, b"", local_hash, remote_hash)):
                    self.state.add_conflict(rel_path, local_hash, remote_hash)
                    conflicts_found += 1
                    print(f"Conflict detected: {rel_path}")
                continue
            
            # Add to download tasks
            download_tasks.append({
                'item': item,
                'local_path': local_path,
                'rel_path': rel_path,
                'remote_source': remote_source
            })
        
        return conflicts_found
    
    def _download_task(self, remote_item, local_path: Path, 
                       rel_path: str, remote_source: str) -> bool:
        """Execute a single download task (thread-safe).
        
        Args:
            remote_item: Remote file item
            local_path: Local path to save file
            rel_path: Relative path for state tracking
            remote_source: Remote source path
            
        Returns:
            True if download successful
        """
        try:
            if self.download_file(remote_item, local_path):
                # Thread-safe state update
                with self._state_lock:
                    new_hash = State.compute_file_hash(local_path)
                    self.state.set_file_hash(rel_path, new_hash)
                    self.state.set_file_source(rel_path, remote_source)
                return True
            return False
        except Exception as e:
            logger.exception(f"Download task failed for {rel_path}")
            return False
    
    def sync_to_remote(self, folder_name: str = "Documents",
                     local_base: Optional[Path] = None) -> int:
        """Sync opened files from local to iCloud with concurrent uploads.
        
        Args:
            folder_name: Remote folder name (used as fallback if no source recorded)
            local_base: Local base directory. Defaults to current directory
            
        Returns:
            Number of files uploaded
        """
        if local_base is None:
            local_base = Path.cwd()
        
        local_base = Path(local_base)
        opened_files = self.state.get_opened_files()
        
        if not opened_files:
            return 0
        
        # Prepare upload tasks
        upload_tasks = []
        skipped_files = []
        
        for rel_path in opened_files:
            local_path = local_base / rel_path
            
            if not local_path.exists():
                print(f"File not found: {rel_path}")
                skipped_files.append(rel_path)
                continue
            
            # Check if file is in a conflict state
            if rel_path in self.state.get_conflicts():
                print(f"Skipping conflicted file: {rel_path}")
                skipped_files.append(rel_path)
                continue
            
            # Get original remote path from file source
            file_source = self.state.get_file_source(rel_path)
            if file_source:
                source_parts = file_source.split('/')
                if len(source_parts) > 1:
                    target_folder = source_parts[0]
                    remote_subpath = '/'.join(source_parts[1:-1])
                else:
                    target_folder = folder_name
                    remote_subpath = ""
            else:
                target_folder = folder_name
                path_parts = Path(rel_path).parts
                if len(path_parts) > 1:
                    remote_subpath = '/'.join(path_parts[:-1])
                else:
                    remote_subpath = ""
            
            upload_tasks.append({
                'rel_path': rel_path,
                'local_path': local_path,
                'target_folder': target_folder,
                'remote_subpath': remote_subpath
            })
        
        if not upload_tasks:
            return 0
        
        print(f"Uploading {len(upload_tasks)} file(s) concurrently...")
        
        files_uploaded = 0
        failed_uploads = 0
        
        # Use fewer workers for uploads to avoid overwhelming the server
        upload_workers = min(self.max_workers, 4)
        
        with ThreadPoolExecutor(max_workers=upload_workers) as executor:
            future_to_task = {
                executor.submit(
                    self._upload_task,
                    task['local_path'],
                    task['rel_path'],
                    task['target_folder'],
                    task['remote_subpath']
                ): task
                for task in upload_tasks
            }
            
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    success, dest = future.result()
                    if success:
                        files_uploaded += 1
                        print(f"Uploaded: {task['rel_path']} -> {dest}")
                    else:
                        failed_uploads += 1
                        print(f"Failed: {task['rel_path']}")
                except Exception as e:
                    failed_uploads += 1
                    logger.exception(f"Upload exception for {task['rel_path']}")
                    print(f"Error: {task['rel_path']}: {e}")
        
        if failed_uploads > 0:
            print(f"Warning: {failed_uploads} file(s) failed to upload.")
        
        return files_uploaded
    
    def _upload_task(self, local_path: Path, rel_path: str,
                     target_folder: str, remote_subpath: str) -> Tuple[bool, str]:
        """Execute a single upload task (thread-safe).
        
        Args:
            local_path: Local file path
            rel_path: Relative path for state tracking
            target_folder: Target folder name
            remote_subpath: Remote subpath
            
        Returns:
            Tuple of (success, destination_path)
        """
        dest = f"{target_folder}/{remote_subpath}/{local_path.name}" if remote_subpath else f"{target_folder}/{local_path.name}"
        try:
            if self.upload_file(local_path, target_folder, remote_subpath):
                # Thread-safe state update
                with self._state_lock:
                    new_hash = State.compute_file_hash(local_path)
                    self.state.set_file_hash(rel_path, new_hash)
                    self.state.remove_opened_file(rel_path)
                return True, dest
            return False, dest
        except Exception as e:
            logger.exception(f"Upload task failed for {rel_path}")
            return False, dest
    
    def upload_single_file(self, rel_path: str, folder_name: str = "Documents",
                           local_base: Optional[Path] = None) -> bool:
        """Upload a single file to iCloud.
        
        Args:
            rel_path: Relative path to the file
            folder_name: Remote folder name (used as fallback if no source recorded)
            local_base: Local base directory. Defaults to current directory
            
        Returns:
            True if upload successful
        """
        if local_base is None:
            local_base = Path.cwd()
        
        local_path = local_base / rel_path
        
        if not local_path.exists():
            logger.error(f"File not found: {rel_path}")
            return False
        
        # Get original remote path from file source
        file_source = self.state.get_file_source(rel_path)
        if file_source:
            # Parse the source path (e.g., "Documents/subfolder/file.txt")
            source_parts = file_source.split('/')
            if len(source_parts) > 1:
                target_folder = source_parts[0]
                remote_subpath = '/'.join(source_parts[1:-1])
            else:
                target_folder = folder_name
                remote_subpath = ""
        else:
            # Fallback: use folder_name and local path structure
            target_folder = folder_name
            path_parts = Path(rel_path).parts
            if len(path_parts) > 1:
                remote_subpath = '/'.join(path_parts[:-1])
            else:
                remote_subpath = ""
        
        try:
            if self.upload_file(local_path, target_folder, remote_subpath):
                # Update state
                new_hash = State.compute_file_hash(local_path)
                self.state.set_file_hash(rel_path, new_hash)
                dest = f"{target_folder}/{remote_subpath}/{local_path.name}" if remote_subpath else f"{target_folder}/{local_path.name}"
                print(f"Destination: {dest}")
                return True
            return False
        except Exception as e:
            logger.exception(f"Failed to upload {rel_path}")
            return False

    def reconcile_local_changes(self, base_dir: Optional[Path] = None) -> int:
        """Scan local directory for changes and mark as opened.
        
        Args:
            base_dir: Base directory to scan. Defaults to current directory
            
        Returns:
            Number of files marked as opened
        """
        if base_dir is None:
            base_dir = Path.cwd()
        
        base_dir = Path(base_dir)
        tracked_folders = self.config.get_tracked_folders()
        files_opened = 0
        
        # Scan all files in base directory
        for file_path in base_dir.rglob('*'):
            if not file_path.is_file():
                continue
            
            # Skip .icloud directory
            if '.icloud' in file_path.parts:
                continue
            
            rel_path = str(file_path.relative_to(base_dir))
            
            # Skip if already opened
            if rel_path in self.state.get_opened_files():
                continue
            
            # Skip if in conflict
            if rel_path in self.state.get_conflicts():
                continue
            
            # Check if file has changed
            current_hash = State.compute_file_hash(file_path)
            stored_hash = self.state.get_file_hash(rel_path)
            
            if stored_hash and current_hash != stored_hash:
                # File has been modified
                self.state.add_opened_file(rel_path)
                files_opened += 1
                print(f"Marked as opened: {rel_path}")
            elif not stored_hash:
                # New file
                self.state.add_opened_file(rel_path)
                files_opened += 1
                print(f"Marked as opened (new): {rel_path}")
        
        return files_opened

