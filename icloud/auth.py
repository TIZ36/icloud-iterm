"""Authentication module for iCloud CLI."""

import os
import sys
import time
from pathlib import Path
from typing import Optional
from pyicloud import PyiCloudService
from pyicloud.exceptions import (
    PyiCloudFailedLoginException,
    PyiCloud2SARequiredException,
    PyiCloud2FARequiredException,
    PyiCloudNoStoredPasswordAvailableException,
)
from pyicloud.utils import get_password_from_keyring, store_password_in_keyring

from .config import Config
from .logger import logger


def get_cookie_directory() -> str:
    """Get the cookie directory for pyicloud session storage."""
    cookie_dir = Path.home() / ".pyicloud"
    cookie_dir.mkdir(parents=True, exist_ok=True)
    return str(cookie_dir)


def is_china_account(username: str) -> bool:
    """Check if the account is a China mainland iCloud account.
    
    China mainland accounts use @icloud.com domain and require
    the china_mainland=True flag for proper authentication.
    
    Args:
        username: Apple ID / email address
        
    Returns:
        True if account appears to be China mainland account
    """
    # Chinese iCloud accounts typically use @icloud.com
    # and may have Chinese characters or specific patterns
    # For now, we'll check common China iCloud domains
    china_domains = ['@icloud.com', '@icloud.com.cn', '@me.com', '@mac.com']
    username_lower = username.lower()
    
    # Check if it's a known China domain
    for domain in china_domains:
        if domain in username_lower:
            return True
    
    return False


class AuthManager:
    """Manages iCloud authentication."""
    
    def __init__(self, config: Optional[Config] = None):
        """Initialize auth manager.
        
        Args:
            config: Config instance. If None, creates a new one.
        """
        self.config = config or Config()
        self._service: Optional[PyiCloudService] = None
    
    def _try_login_with_region(self, username: str, password: str, cookie_dir: str, china_mainland: bool) -> Optional[PyiCloudService]:
        """Try to login with specified region setting.
        
        Args:
            username: Apple ID username
            password: Password
            cookie_dir: Cookie directory path
            china_mainland: Whether to use China mainland endpoint
            
        Returns:
            PyiCloudService instance if successful, None otherwise
        """
        region_name = "China mainland" if china_mainland else "International"
        try:
            logger.debug(f"Attempting {region_name} login for {username}")
            service = PyiCloudService(
                username,
                password,
                cookie_directory=cookie_dir,
                china_mainland=china_mainland
            )
            logger.info(f"{region_name} login service created successfully")
            return service
        except PyiCloudFailedLoginException as e:
            logger.debug(f"{region_name} login failed: {e}")
            return None
        except Exception as e:
            logger.debug(f"{region_name} login error: {e}")
            return None
    
    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Login to iCloud.
        
        Args:
            username: Apple ID username. If None, prompts user.
            password: Password. If None, prompts for password or uses keyring.
            
        Returns:
            True if login successful, False otherwise
        """
        if username is None:
            # Check if we have a saved username
            stored_username = self.config.get_username()
            if stored_username:
                use_stored = input(f"Apple ID [{stored_username}]: ").strip()
                username = use_stored if use_stored else stored_username
            else:
                username = input("Apple ID: ").strip()
        
        cookie_dir = get_cookie_directory()
        
        try:
            service = None
            need_password = True
            china_mainland_used = False  # Track which region succeeded
            
            # Check if we have a stored password in keyring
            stored_password = get_password_from_keyring(username)
            if stored_password and not password:
                logger.debug(f"Found stored password in keyring for {username}")
                password = stored_password
            
            # Try to create service with stored credentials first
            if password or stored_password:
                # Strategy: Try international first, then China mainland
                logger.info("Trying international login first...")
                service = self._try_login_with_region(username, password, cookie_dir, china_mainland=False)
                
                if service is None:
                    logger.info("International login failed, trying China mainland...")
                    service = self._try_login_with_region(username, password, cookie_dir, china_mainland=True)
                    if service is not None:
                        china_mainland_used = True
                
                if service is not None:
                    need_password = False
                    logger.info(f"Service created with password ({'China mainland' if china_mainland_used else 'International'})")
            
            # If no service yet, prompt for password
            if service is None:
                import getpass
                password = getpass.getpass("Password: ")
                
                # Strategy: Try international first, then China mainland
                logger.info("Trying international login first...")
                service = self._try_login_with_region(username, password, cookie_dir, china_mainland=False)
                
                if service is None:
                    logger.info("International login failed, trying China mainland...")
                    service = self._try_login_with_region(username, password, cookie_dir, china_mainland=True)
                    if service is not None:
                        china_mainland_used = True
                
                if service is None:
                    # Both failed, raise the last error
                    logger.error("Login failed for both international and China mainland endpoints")
                    print("Login failed: Unable to authenticate with both international and China mainland endpoints")
                    return False
                
                # Store password in keyring for future use
                try:
                    store_password_in_keyring(username, password)
                    logger.info("Password stored in keyring")
                except Exception as e:
                    logger.warning(f"Could not store password in keyring: {e}")
            
            # Save region preference for future use
            self.config.set_china_mainland(china_mainland_used)
            
            # Handle 2FA if required
            # First, try to detect if 2FA is needed by checking the service
            needs_2fa = False
            requires_2fa = False
            requires_2sa = False
            
            # Check requires_2fa and requires_2sa attributes
            try:
                if hasattr(service, 'requires_2fa'):
                    requires_2fa = service.requires_2fa
                if hasattr(service, 'requires_2sa'):
                    requires_2sa = service.requires_2sa
            except Exception as e:
                logger.debug(f"Error checking 2FA attributes: {e}")
            
            # If 2FA attributes don't indicate 2FA is needed, try to access drive
            # to see if we get an authentication error (which indicates 2FA is needed)
            if not requires_2fa and not requires_2sa:
                try:
                    # Try to access drive - if it fails with 421, we need 2FA
                    _ = service.drive
                except Exception as drive_error:
                    error_msg = str(drive_error)
                    if "421" in error_msg or "Authentication required" in error_msg:
                        # This indicates 2FA is needed
                        requires_2fa = True
                        logger.info("Detected 2FA requirement from drive access error")
            
            if requires_2fa or requires_2sa:
                needs_2fa = True
                print("\n" + "="*50)
                print("Two-factor authentication required!")
                print("Please check your trusted device for the verification code.")
                print("="*50)
                
                max_attempts = 3
                for attempt in range(max_attempts):
                    code = input(f"\nEnter the 6-digit verification code: ").strip()
                    
                    if not code:
                        print("Code cannot be empty. Please try again.")
                        continue
                    
                    try:
                        if requires_2fa and hasattr(service, 'validate_2fa_code'):
                            if service.validate_2fa_code(code):
                                service.trust_session()
                                print("\n✓ 2FA verification successful!")
                                break
                            else:
                                remaining = max_attempts - attempt - 1
                                if remaining > 0:
                                    print(f"Invalid code. {remaining} attempt(s) remaining.")
                                else:
                                    print("Invalid code. Maximum attempts reached.")
                                    return False
                        elif requires_2sa and hasattr(service, 'validate_2sa_code'):
                            if service.validate_2sa_code(code):
                                service.trust_session()
                                print("\n✓ 2SA verification successful!")
                                break
                            else:
                                remaining = max_attempts - attempt - 1
                                if remaining > 0:
                                    print(f"Invalid code. {remaining} attempt(s) remaining.")
                                else:
                                    print("Invalid code. Maximum attempts reached.")
                                    return False
                        else:
                            # Fallback: try to trust session directly
                            service.trust_session()
                            print("\n✓ Verification successful!")
                            break
                    except Exception as e:
                        remaining = max_attempts - attempt - 1
                        if remaining > 0:
                            print(f"Error validating code: {e}. {remaining} attempt(s) remaining.")
                        else:
                            logger.error(f"2FA validation failed after {max_attempts} attempts: {e}")
                            print("Verification failed. Please try logging in again.")
                            return False
                else:
                    print("Maximum verification attempts reached.")
                    return False
            
            # If 2FA was completed, consider authentication successful
            # Otherwise, verify authentication by trying to access a service
            if not needs_2fa:
                try:
                    if hasattr(service, 'drive'):
                        # Try to access drive to verify authentication
                        _ = service.drive
                    # If we get here without exception, authentication is successful
                except Exception as e:
                    logger.error(f"Authentication verification failed: {e}")
                    print("Authentication failed.")
                    return False
            
            # Save credentials and session
            self.config.set_username(username)
            self._service = service
            
            # pyicloud automatically saves session/token in its default location
            # Session has already been verified above, no need to verify again
            logger.info("Session saved successfully")
            
            print("Login successful! Session saved.")
            return True
            
        except PyiCloudFailedLoginException as e:
            logger.error(f"Login failed: {e}")
            print(f"Login failed: {e}")
            return False
        except (PyiCloud2SARequiredException, PyiCloud2FARequiredException):
            logger.warning("Two-factor authentication required")
            print("Two-factor authentication required.")
            print("Please use app-specific password or enable 2FA.")
            return False
        except Exception as e:
            logger.exception("Unexpected error during login")
            print(f"Unexpected error during login: {e}")
            return False
    
    def _verify_service(self, service: PyiCloudService) -> bool:
        """Verify that a service is valid and can access drive.
        
        Args:
            service: PyiCloudService instance to verify
            
        Returns:
            True if service is valid, False otherwise
        """
        # Check if 2FA is required (session expired or invalid)
        if hasattr(service, 'requires_2fa') and service.requires_2fa:
            logger.debug("2FA required, session expired or invalid")
            return False
        if hasattr(service, 'requires_2sa') and service.requires_2sa:
            logger.debug("2SA required, session expired or invalid")
            return False
        
        # Verify authentication by trying to access a service
        try:
            if hasattr(service, 'drive'):
                _ = service.drive
            return True
        except Exception as e:
            error_msg = str(e)
            if "421" in error_msg or "Authentication required" in error_msg:
                logger.debug("Session expired or authentication required")
            else:
                logger.debug(f"Service access failed: {e}")
            return False
    
    def get_service(self) -> Optional[PyiCloudService]:
        """Get authenticated PyiCloudService instance.
        
        Tries to reuse saved session/token. If session is invalid, returns None.
        Uses saved region preference, or tries international first then China mainland.
        
        Returns:
            PyiCloudService instance or None if not authenticated
        """
        # Return cached service if available
        if self._service is not None:
            # Verify cached service is still valid
            try:
                if hasattr(self._service, 'drive'):
                    _ = self._service.drive
                return self._service
            except Exception:
                # Cached service is invalid, clear it
                logger.warning("Cached service is invalid, clearing cache")
                self._service = None
        
        username = self.config.get_username()
        if not username:
            logger.debug("No username in config")
            return None
        
        cookie_dir = get_cookie_directory()
        
        try:
            # Try to get password from keyring
            stored_password = get_password_from_keyring(username)
            if not stored_password:
                logger.info("No stored password in keyring, need to re-authenticate")
                return None
            
            # Check for saved region preference
            saved_china_mainland = self.config.get_china_mainland()
            
            service = None
            tried_international = False
            tried_china = False
            
            # Try saved region preference first (if available)
            if saved_china_mainland is not None:
                region_name = 'China mainland' if saved_china_mainland else 'International'
                logger.debug(f"Trying saved region preference: {region_name}")
                service = self._try_login_with_region(username, stored_password, cookie_dir, saved_china_mainland)
                if service and self._verify_service(service):
                    logger.info(f"Successfully reused saved session with {region_name} endpoint")
                    self._service = service
                    return service
                # Mark which region we've tried
                if saved_china_mainland:
                    tried_china = True
                else:
                    tried_international = True
                service = None
            
            # Strategy: Try international first (if not already tried), then China mainland
            if not tried_international:
                logger.debug("Trying international endpoint...")
                service = self._try_login_with_region(username, stored_password, cookie_dir, china_mainland=False)
                if service and self._verify_service(service):
                    logger.info("Successfully reused saved session with International endpoint")
                    self.config.set_china_mainland(False)
                    self._service = service
                    return service
            
            if not tried_china:
                logger.debug("Trying China mainland endpoint...")
                service = self._try_login_with_region(username, stored_password, cookie_dir, china_mainland=True)
                if service and self._verify_service(service):
                    logger.info("Successfully reused saved session with China mainland endpoint")
                    self.config.set_china_mainland(True)
                    self._service = service
                    return service
            
            logger.info("Both endpoints failed, need to re-authenticate")
            return None
                
        except PyiCloudFailedLoginException:
            logger.info("Saved session invalid, need to re-authenticate")
            return None
        except (PyiCloud2SARequiredException, PyiCloud2FARequiredException):
            logger.info("2FA required, need to re-authenticate")
            return None
        except Exception as e:
            logger.exception("Error getting iCloud service with saved session")
            return None
    
    def is_authenticated(self) -> bool:
        """Check if user is authenticated.
        
        Returns:
            True if authenticated, False otherwise
        """
        service = self.get_service()
        if service is None:
            return False
        
        # Verify by trying to access drive service
        try:
            if hasattr(service, 'drive'):
                _ = service.drive
            return True
        except Exception:
            return False
    
    def logout(self) -> None:
        """Logout and clear stored credentials and session."""
        username = self.config.get_username()
        self._service = None
        self.config.clear_auth()
        
        # Clear password from keyring
        if username:
            try:
                import keyring
                from pyicloud.utils import KEYRING_SYSTEM
                keyring.delete_password(KEYRING_SYSTEM, username)
                logger.info(f"Removed password from keyring for {username}")
            except Exception as e:
                logger.debug(f"Could not clear keyring password: {e}")
        
        # Clear pyicloud's saved session
        try:
            # pyicloud saves session in ~/.pyicloud/ or similar location
            # Try to find and remove session files
            if username:
                # Common locations for pyicloud session files
                cookie_dir = Path.home() / ".pyicloud"
                if cookie_dir.exists() and cookie_dir.is_dir():
                    # Remove all session files
                    for file in cookie_dir.glob("*"):
                        try:
                            if file.is_file():
                                file.unlink()
                                logger.debug(f"Removed session file: {file}")
                        except Exception as e:
                            logger.debug(f"Could not remove file {file}: {e}")
        except Exception as e:
            logger.debug(f"Could not clear pyicloud session files: {e}")
        
        print("Logged out successfully. Credentials and session cleared.")

