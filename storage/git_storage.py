"""Git-based storage backend for BookChat."""

import json
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path
import uuid
import subprocess
import traceback

from storage import StorageBackend
from git_manager import GitManager

# Get logger for this module
logger = logging.getLogger(__name__)

class GitStorage(StorageBackend):
    """Storage backend that uses Git repository for message storage."""
    
    def __init__(self, repo_path: str):
        """Initialize the Git storage backend.
        
        Args:
            repo_path: Path to the Git repository
        """
        logger.info(f"Initializing GitStorage with repo_path: {repo_path}")
        self.repo_path = Path(repo_path)
        self.messages_dir = self.repo_path / 'messages'
        self.git_manager = GitManager(str(repo_path))
        logger.debug(f"Messages directory: {self.messages_dir}")
        
        # Check if messages directory exists
        if not self.messages_dir.exists():
            logger.warning(f"Messages directory does not exist: {self.messages_dir}")
        else:
            logger.debug(f"Messages directory exists and contains: {list(self.messages_dir.glob('*'))}")
        
        # Check Git repository status
        try:
            result = subprocess.run(
                ['git', 'status'],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True
            )
            logger.debug(f"Git status output: {result.stdout}")
            if result.stderr:
                logger.warning(f"Git status stderr: {result.stderr}")
        except Exception as e:
            logger.error(f"Failed to check Git status: {e}")
        
    def init_storage(self) -> bool:
        """Initialize the storage by creating necessary directories."""
        try:
            # Create messages directory if it doesn't exist
            logger.debug(f"Ensuring messages directory exists: {self.messages_dir}")
            os.makedirs(self.messages_dir, exist_ok=True)
            
            # Check if directory was created successfully
            if not self.messages_dir.exists():
                logger.error("Failed to create messages directory")
                return False
            
            # Check directory permissions
            logger.debug(f"Messages directory permissions: {oct(os.stat(self.messages_dir).st_mode)}")
            
            # List directory contents
            logger.debug(f"Messages directory contents: {list(self.messages_dir.glob('*'))}")
            
            logger.info("Storage initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize storage: {e}\n{traceback.format_exc()}")
            return False
    
    def save_message(self, user: str, content: str, timestamp: datetime) -> bool:
        """Save a new message to the Git repository.
        
        Args:
            user: Username of the message sender
            content: Message content
            timestamp: Message timestamp
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Saving message from user: {user}")
            
            # Format filename like existing messages: YYYYMMDD_HHMMSS_username.txt
            filename = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{user}.txt"
            message_path = self.messages_dir / filename
            logger.debug(f"Message will be saved to: {message_path}")
            
            # Check if messages directory exists
            if not self.messages_dir.exists():
                logger.error(f"Messages directory does not exist: {self.messages_dir}")
                return False
            
            # Check directory permissions
            logger.debug(f"Messages directory permissions: {oct(os.stat(self.messages_dir).st_mode)}")
            
            # Format message content
            message_data = {
                'user': user,
                'content': content,
                'timestamp': timestamp.isoformat()
            }
            logger.debug(f"Message data: {message_data}")
            
            # Write message to file
            logger.info(f"Writing message to: {message_path}")
            try:
                with open(message_path, 'w') as f:
                    json.dump(message_data, f, indent=2)
                logger.debug(f"Successfully wrote message to file: {message_path}")
                logger.debug(f"File exists after write: {message_path.exists()}")
                logger.debug(f"File contents after write: {message_path.read_text() if message_path.exists() else 'FILE NOT FOUND'}")
            except Exception as e:
                logger.error(f"Failed to write message file: {e}\n{traceback.format_exc()}")
                return False
            
            # Stage and commit the file
            logger.info("Committing message to Git repository")
            try:
                # Get relative path from repo root
                relative_path = message_path.relative_to(self.repo_path)
                logger.debug(f"Relative path for Git: {relative_path}")
                
                # Stage the file
                logger.debug("Running git add...")
                result = subprocess.run(
                    ['git', 'add', str(relative_path)],
                    cwd=str(self.repo_path),
                    check=True,
                    capture_output=True,
                    text=True
                )
                logger.debug(f"Git add output: {result.stdout}")
                if result.stderr:
                    logger.warning(f"Git add stderr: {result.stderr}")
                
                # Commit the file
                commit_msg = f'Add message from {user}'
                logger.debug(f"Running git commit with message: {commit_msg}")
                result = subprocess.run(
                    ['git', 'commit', '-m', commit_msg],
                    cwd=str(self.repo_path),
                    check=True,
                    capture_output=True,
                    text=True,
                    env={**os.environ, 'GIT_AUTHOR_NAME': user, 'GIT_AUTHOR_EMAIL': f'{user}@bookchat.local'}
                )
                logger.debug(f"Git commit output: {result.stdout}")
                if result.stderr:
                    logger.warning(f"Git commit stderr: {result.stderr}")
                
                # Try to sync to GitHub if enabled
                if os.getenv('SYNC_TO_GITHUB', '').lower() == 'true':
                    logger.debug("Attempting to sync to GitHub...")
                    try:
                        self.git_manager.sync_changes_to_github(str(message_path), user)
                        logger.debug("Successfully synced to GitHub")
                    except Exception as e:
                        logger.warning(f"Failed to sync to GitHub: {e}")
                        # Don't fail the save operation if GitHub sync fails
                
                logger.info("Message saved successfully")
                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"Git operation failed: {e.stdout}\n{e.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to save message: {e}\n{traceback.format_exc()}")
            return False
    
    def get_messages(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve messages from the Git repository.
        
        Args:
            limit: Optional maximum number of messages to retrieve
        
        Returns:
            List of message dictionaries
        """
        messages = []
        try:
            logger.debug(f"Getting messages with limit: {limit}")
            message_files = sorted(
                self.messages_dir.glob('*.txt'),
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            logger.debug(f"Found {len(message_files)} message files")
            
            if limit is not None:
                message_files = message_files[:limit]
            
            for file_path in message_files:
                try:
                    with open(file_path) as f:
                        message = json.load(f)
                        messages.append(message)
                except Exception as e:
                    logger.error(f"Failed to read message file {file_path}: {e}")
            
            logger.debug(f"Returning {len(messages)} messages")
            return messages
        except Exception as e:
            logger.error(f"Failed to retrieve messages: {e}\n{traceback.format_exc()}")
            return []
    
    def get_message_by_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific message by ID.
        
        Args:
            message_id: ID of the message to retrieve
        
        Returns:
            Message dictionary if found, None otherwise
        """
        try:
            logger.debug(f"Getting message by ID: {message_id}")
            message_path = self.messages_dir / f"{message_id}.txt"
            if message_path.exists():
                with open(message_path) as f:
                    message = json.load(f)
                    logger.debug(f"Found message: {message}")
                    return message
            logger.debug(f"Message not found: {message_id}")
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve message by ID: {e}\n{traceback.format_exc()}")
            return None