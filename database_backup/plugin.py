"""
Dispatcharr Database Backup Manager with Scheduling
Enhanced version with automatic scheduled backups

Version: 1.0.0
Author: Community Plugin
License: CC BY-NC-SA 4.0
"""

import os
import subprocess
import gzip
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django_celery_beat.models import PeriodicTask, CrontabSchedule

logger = logging.getLogger(__name__)


class Plugin:
    """Database Backup Manager with Scheduling Support"""
    
    name = "Database Backup Manager"
    version = "0.1.4"
    description = "Database backup with scheduled automation and retention management"
    author = "Community Plugin"
    
    # Configuration
    BACKUP_DIR = "/data/backups"
    SETTINGS_FILE = "/data/backup_plugin_settings.json"
    TASK_PREFIX = "db_backup_scheduled_"
    
    fields = [
        {
            "id": "retention_days",
            "label": "Retention Period (Days)",
            "type": "number",
            "default": 30,
            "description": "Number of days to keep backups before auto-deletion"
        },
        {
            "id": "max_backups",
            "label": "Maximum Backups",
            "type": "number",
            "default": 14,
            "description": "Maximum number of backups to keep (oldest deleted first)"
        },
        {
            "id": "timezone",
            "label": "Timezone",
            "type": "string",
            "default": "America/Chicago",
            "description": "Timezone for scheduled backups and backup timestamp display (e.g., America/New_York, Europe/London, UTC)"
        },
        {
            "id": "scheduled_times",
            "label": "Scheduled Backup Times (Cron Format)",
            "type": "string",
            "default": "",
            "description": "Use cron format for scheduling. Examples: '0 2 * * *' (daily at 2:00 AM), '0 2,14 * * *' (daily at 2:00 AM and 2:00 PM), '0 */6 * * *' (every 6 hours). Leave blank to disable. See: https://crontab.guru"
        }
    ]
    
    actions = [
        {
            "id": "update_schedule",
            "label": "📅 Update Schedule",
            "description": "Save settings and activate scheduled backup times"
        },
        {
            "id": "create_backup",
            "label": "➕ Create Backup Now",
            "description": "Create a compressed database backup immediately"
        },
        {
            "id": "delete_all",
            "label": "🗑 Delete All Backups",
            "description": "Permanently delete all backup files"
        },
        {
            "id": "cleanup_orphaned_tasks",
            "label": "🧹 Delete Backup Schedule",
            "description": "Remove all scheduled backup tasks (manual backups will still work)"
        }
    ]
    
    def __init__(self):
        """Initialize the plugin and ensure backup directory exists"""
        os.makedirs(self.BACKUP_DIR, exist_ok=True)
    
    def run(self, action: str, params: dict, context: dict):
        """
        Main entry point for plugin actions
        
        Args:
            action: The action ID being executed
            params: Additional parameters from the UI
            context: Context including settings and logger
        """
        settings = context.get("settings", {})
        ctx_logger = context.get("logger", logger)
        
        # Save settings on every action
        self.save_settings(settings)
        
        # Handle dynamic restore actions
        if action.startswith("restore_"):
            backup_filename = action.replace("restore_", "")
            return self._handle_restore(backup_filename, ctx_logger)
        
        # Handle static actions
        if action == "update_schedule":
            return self._handle_update_schedule(settings, ctx_logger)
        
        elif action == "create_backup":
            return self._handle_create_backup(settings, ctx_logger)
        
        elif action == "delete_all":
            return self._handle_delete_all(ctx_logger)
        
        elif action == "cleanup_orphaned_tasks":
            return self._handle_cleanup_orphaned_tasks(ctx_logger)
        
        else:
            return {
                "success": False,
                "message": f"Unknown action: {action}"
            }
    
    # ========================================================================
    # Action Handlers
    # ========================================================================
    
    def _handle_update_schedule(self, settings, logger):
        """Handle the update_schedule action"""
        if self.update_schedule(settings, logger):
            scheduled_times = settings.get('scheduled_times', '')
            timezone = settings.get('timezone', 'America/Chicago')
            
            if scheduled_times:
                logger.info(f"Schedule updated successfully for times: {scheduled_times} ({timezone})")
                return {
                    "success": True,
                    "message": f"Backup schedule updated. Times: {scheduled_times} ({timezone})"
                }
            else:
                logger.info("Scheduled backups disabled (no times configured)")
                return {
                    "success": True,
                    "message": "Scheduled backups disabled (no times configured)"
                }
        else:
            return {
                "success": False,
                "message": "Failed to update schedule. Check logs for details."
            }
    
    def _handle_create_backup(self, settings, logger):
        """Handle the create_backup action"""
        try:
            logger.info("Starting manual database backup...")
            backup_file = self.create_backup(logger)
            
            if backup_file:
                # Apply retention policy
                self.apply_retention(settings, logger)
                
                size_mb = os.path.getsize(backup_file) / (1024 * 1024)
                logger.info(f"Backup created successfully: {os.path.basename(backup_file)} ({size_mb:.2f} MB)")
                
                return {
                    "success": True,
                    "message": f"Backup created: {os.path.basename(backup_file)} ({size_mb:.2f} MB)"
                }
            else:
                return {
                    "success": False,
                    "message": "Backup failed. Check logs for details."
                }
        
        except Exception as e:
            logger.error(f"Backup creation failed: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Backup failed: {str(e)}"
            }
    
    def _handle_restore(self, backup_filename, logger):
        """Handle restore action for a specific backup"""
        try:
            backup_path = os.path.join(self.BACKUP_DIR, backup_filename)
            
            if not os.path.exists(backup_path):
                return {
                    "success": False,
                    "message": f"Backup file not found: {backup_filename}"
                }
            
            logger.info(f"Starting restore from: {backup_filename}")
            
            if self.restore_backup(backup_path, logger):
                logger.info(f"Restore completed successfully from: {backup_filename}")
                return {
                    "success": True,
                    "message": f"✅ Restore completed. Please restart Dispatcharr: docker restart dispatcharr"
                }
            else:
                return {
                    "success": False,
                    "message": "Restore failed. Check logs for details."
                }
        
        except Exception as e:
            logger.error(f"Restore failed: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Restore failed: {str(e)}"
            }
    
    def _handle_delete_all(self, logger):
        """Handle the delete_all action"""
        try:
            count = 0
            for file in os.listdir(self.BACKUP_DIR):
                if file.startswith("dispatcharr_backup_") and file.endswith(".sql.gz"):
                    os.remove(os.path.join(self.BACKUP_DIR, file))
                    count += 1
            
            logger.info(f"Deleted {count} backup file(s)")
            return {
                "success": True,
                "message": f"Deleted {count} backup file(s)"
            }
        
        except Exception as e:
            logger.error(f"Delete all failed: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Delete failed: {str(e)}"
            }
    
    def _handle_cleanup_orphaned_tasks(self, logger):
        """Handle cleanup of scheduled backup tasks"""
        try:
            deleted_count, _ = PeriodicTask.objects.filter(
                name__startswith=self.TASK_PREFIX
            ).delete()
            logger.info(f"Deleted {deleted_count} scheduled backup task(s)")
            return {
                "success": True,
                "message": f"Deleted {deleted_count} scheduled backup task(s). Manual backups still work."
            }
        except Exception as e:
            logger.error(f"Delete schedule failed: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Delete schedule failed: {str(e)}"
            }
    
    # ========================================================================
    # Backup Operations
    # ========================================================================
    
    def create_backup(self, logger):
        """
        Create a compressed database backup using pg_dump
        
        Returns:
            str: Path to created backup file, or None if failed
        """
        try:
            # Get database credentials from environment
            db_host = os.getenv('POSTGRES_HOST', 'localhost')
            db_port = os.getenv('POSTGRES_PORT', '5432')
            db_user = os.getenv('POSTGRES_USER', 'dispatcharr')
            db_name = os.getenv('POSTGRES_DB', 'dispatcharr')
            db_password = os.getenv('POSTGRES_PASSWORD', '')
            
            # Generate backup filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"dispatcharr_backup_{timestamp}.sql.gz"
            backup_path = os.path.join(self.BACKUP_DIR, backup_filename)
            
            logger.info(f"Creating backup: {backup_filename}")
            
            # Build pg_dump command
            dump_cmd = [
                'pg_dump',
                '-h', db_host,
                '-p', db_port,
                '-U', db_user,
                '-d', db_name,
                '-Fp',  # Plain text format
                '-v'    # Verbose
            ]
            
            # Set password environment variable
            env = os.environ.copy()
            env['PGPASSWORD'] = db_password
            
            # Run pg_dump and pipe to gzip
            with gzip.open(backup_path, 'wb', compresslevel=9) as gz_file:
                result = subprocess.run(
                    dump_cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True
                )
                gz_file.write(result.stdout)
            
            logger.info(f"Backup created successfully: {backup_path}")
            return backup_path
            
        except subprocess.CalledProcessError as e:
            logger.error(f"pg_dump failed: {e.stderr.decode()}")
            return None
        except Exception as e:
            logger.error(f"Backup creation failed: {e}", exc_info=True)
            return None
    
    def restore_backup(self, backup_path, logger):
        """
        Restore database from a compressed backup file
        
        Args:
            backup_path: Path to the backup file
            logger: Logger instance
        
        Returns:
            bool: True if successful
        """
        try:
            # Get database credentials
            db_host = os.getenv('POSTGRES_HOST', 'localhost')
            db_port = os.getenv('POSTGRES_PORT', '5432')
            db_user = os.getenv('POSTGRES_USER', 'dispatcharr')
            db_name = os.getenv('POSTGRES_DB', 'dispatcharr')
            db_password = os.getenv('POSTGRES_PASSWORD', '')
            
            env = os.environ.copy()
            env['PGPASSWORD'] = db_password
            
            logger.info(f"Restoring from: {backup_path}")
            
            # Step 1: Terminate all connections to the database
            logger.info("Terminating database connections...")
            terminate_cmd = [
                'psql',
                '-h', db_host,
                '-p', db_port,
                '-U', db_user,
                '-d', 'postgres',  # Connect to postgres db
                '-c', f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();"
            ]
            subprocess.run(terminate_cmd, env=env, check=True, capture_output=True)
            
            # Step 2: Drop and recreate database
            logger.info("Dropping and recreating database...")
            drop_cmd = [
                'psql',
                '-h', db_host,
                '-p', db_port,
                '-U', db_user,
                '-d', 'postgres',
                '-c', f'DROP DATABASE IF EXISTS "{db_name}";'
            ]
            subprocess.run(drop_cmd, env=env, check=True, capture_output=True)
            
            create_cmd = [
                'psql',
                '-h', db_host,
                '-p', db_port,
                '-U', db_user,
                '-d', 'postgres',
                '-c', f'CREATE DATABASE "{db_name}";'
            ]
            subprocess.run(create_cmd, env=env, check=True, capture_output=True)
            
            # Step 3: Restore from backup
            logger.info("Restoring data...")
            with gzip.open(backup_path, 'rb') as gz_file:
                restore_cmd = [
                    'psql',
                    '-h', db_host,
                    '-p', db_port,
                    '-U', db_user,
                    '-d', db_name,
                    '-v', 'ON_ERROR_STOP=1'
                ]
                result = subprocess.run(
                    restore_cmd,
                    env=env,
                    stdin=gz_file,
                    capture_output=True,
                    check=True
                )
            
            logger.info("Database restored successfully")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Restore command failed: {e.stderr.decode()}")
            return False
        except Exception as e:
            logger.error(f"Restore failed: {e}", exc_info=True)
            return False
    
    def apply_retention(self, settings, logger):
        """
        Apply retention policy to remove old backups
        
        Args:
            settings: Plugin settings
            logger: Logger instance
        """
        try:
            retention_days = int(settings.get('retention_days', 30))
            max_backups = int(settings.get('max_backups', 14))
            
            backups = []
            for file in os.listdir(self.BACKUP_DIR):
                if file.startswith("dispatcharr_backup_") and file.endswith(".sql.gz"):
                    file_path = os.path.join(self.BACKUP_DIR, file)
                    stat = os.stat(file_path)
                    backups.append({
                        'path': file_path,
                        'name': file,
                        'mtime': stat.st_mtime
                    })
            
            # Sort by modification time (oldest first)
            backups.sort(key=lambda x: x['mtime'])
            
            removed_count = 0
            cutoff_time = datetime.now().timestamp() - (retention_days * 24 * 3600)
            
            # Remove backups older than retention period
            for backup in backups:
                if backup['mtime'] < cutoff_time:
                    os.remove(backup['path'])
                    logger.info(f"Removed old backup: {backup['name']}")
                    removed_count += 1
            
            # Update list after age-based deletion
            backups = [b for b in backups if b['mtime'] >= cutoff_time]
            
            # Remove excess backups if over max count
            if len(backups) > max_backups:
                excess = len(backups) - max_backups
                for backup in backups[:excess]:
                    os.remove(backup['path'])
                    logger.info(f"Removed excess backup: {backup['name']}")
                    removed_count += 1
            
            if removed_count > 0:
                logger.info(f"Retention policy removed {removed_count} backup(s)")
            
        except Exception as e:
            logger.error(f"Retention policy failed: {e}", exc_info=True)
    
    def get_backup_list(self):
        """
        Get list of all backups with metadata
        
        Returns:
            list: List of backup dictionaries
        """
        backups = []
        
        try:
            # Load settings to get user's timezone
            settings = self.load_settings()
            timezone_str = settings.get('timezone', 'America/Chicago')
            
            # Get timezone object
            try:
                user_tz = ZoneInfo(timezone_str)
            except Exception as e:
                logger.warning(f"Invalid timezone '{timezone_str}', using America/Chicago: {e}")
                user_tz = ZoneInfo('America/Chicago')
            
            for file in sorted(os.listdir(self.BACKUP_DIR), reverse=True):
                if file.startswith("dispatcharr_backup_") and file.endswith(".sql.gz"):
                    file_path = os.path.join(self.BACKUP_DIR, file)
                    stat = os.stat(file_path)
                    
                    # Convert UTC timestamp to user's timezone
                    created_utc = datetime.fromtimestamp(stat.st_mtime, tz=ZoneInfo('UTC'))
                    created_local = created_utc.astimezone(user_tz)
                    age_delta = datetime.now(tz=user_tz) - created_local
                    
                    # Format age
                    if age_delta.days > 0:
                        age_str = f"{age_delta.days}d ago"
                    else:
                        hours = age_delta.seconds // 3600
                        age_str = f"{hours}h ago"
                    
                    backups.append({
                        'filename': file,
                        'size_mb': stat.st_size / (1024 * 1024),
                        'created': created_local.strftime('%Y-%m-%d %I:%M:%S %p'),
                        'age': age_str
                    })
        
        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
        
        return backups
    
    # ========================================================================
    # Dynamic Actions for Restore
    # ========================================================================
    
    @property
    def actions(self):
        """
        Generate dynamic actions including restore buttons for each backup
        """
        static_actions = [
            {
                "id": "update_schedule",
                "label": "📅 Update Schedule",
                "description": "Save settings and activate scheduled backup times"
            },
            {
                "id": "create_backup",
                "label": "➕ Create Backup Now",
                "description": "Create a compressed database backup immediately"
            },
            {
                "id": "delete_all",
                "label": "🗑 Delete All Backups",
                "description": "Permanently delete all backup files"
            },
            {
                "id": "cleanup_orphaned_tasks",
                "label": "🧹 Delete Backup Schedule",
                "description": "Remove all scheduled backup tasks (manual backups will still work)"
            }
        ]
        
        # Add restore action for each backup
        backups = self.get_backup_list()
        for backup in backups:
            static_actions.append({
                "id": f"restore_{backup['filename']}",
                "label": f"↻ Restore: {backup['filename']}",
                "description": f"Created: {backup['created']} | Size: {backup['size_mb']:.2f} MB | {backup['age']}"
            })
        
        return static_actions
    
    # ========================================================================
    # Settings Management
    # ========================================================================
    
    def save_settings(self, plugin_settings):
        """Save plugin settings to a JSON file"""
        try:
            os.makedirs(os.path.dirname(self.SETTINGS_FILE), exist_ok=True)
            with open(self.SETTINGS_FILE, 'w') as f:
                json.dump(plugin_settings, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            return False
    
    def load_settings(self):
        """Load plugin settings from JSON file"""
        try:
            if os.path.exists(self.SETTINGS_FILE):
                with open(self.SETTINGS_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
        return {}
    
    # ========================================================================
    # Scheduling Functions
    # ========================================================================
    
    def parse_cron_schedule(self, cron_str):
        """
        Parse cron format string into schedule components
        
        Args:
            cron_str: Cron format string like "0 2 * * *" or "0 2,14 * * *"
        
        Returns:
            dict with minute, hour, day_of_week, day_of_month, month_of_year
            or None if invalid
        """
        if not cron_str or not cron_str.strip():
            return None
        
        cron_str = cron_str.strip()
        parts = cron_str.split()
        
        # Cron format: minute hour day_of_month month day_of_week
        if len(parts) != 5:
            logger.warning(f"Invalid cron format: {cron_str}. Expected 5 fields (minute hour day month weekday)")
            return None
        
        try:
            return {
                'minute': parts[0],
                'hour': parts[1],
                'day_of_month': parts[2],
                'month_of_year': parts[3],
                'day_of_week': parts[4]
            }
        except Exception as e:
            logger.error(f"Error parsing cron format '{cron_str}': {e}")
            return None
    
    def create_or_update_schedule(self, cron_schedule, timezone_str, task_name):
        """
        Create or update a Celery Beat periodic task with cron schedule
        
        Args:
            cron_schedule: Dict with minute, hour, day_of_month, month_of_year, day_of_week
            timezone_str: Timezone string
            task_name: Unique name for this scheduled task
        
        Returns:
            bool: True if successful
        """
        try:
            # Create or get the crontab schedule
            schedule, created = CrontabSchedule.objects.get_or_create(
                minute=cron_schedule['minute'],
                hour=cron_schedule['hour'],
                day_of_week=cron_schedule['day_of_week'],
                day_of_month=cron_schedule['day_of_month'],
                month_of_year=cron_schedule['month_of_year'],
                timezone=timezone_str
            )
            
            # Create or update the periodic task
            task, created = PeriodicTask.objects.update_or_create(
                name=task_name,
                defaults={
                    'task': 'database_backup.scheduled_backup',
                    'crontab': schedule,
                    'enabled': True,
                }
            )
            
            action = "Created" if created else "Updated"
            cron_str = f"{cron_schedule['minute']} {cron_schedule['hour']} {cron_schedule['day_of_month']} {cron_schedule['month_of_year']} {cron_schedule['day_of_week']}"
            logger.info(f"{action} scheduled task: {task_name} with cron '{cron_str}' ({timezone_str})")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to create/update schedule '{task_name}': {e}")
            return False
    
    def remove_all_scheduled_tasks(self):
        """Remove all scheduled backup tasks for this plugin"""
        try:
            deleted_count, _ = PeriodicTask.objects.filter(
                name__startswith=self.TASK_PREFIX
            ).delete()
            
            logger.info(f"Removed {deleted_count} scheduled backup task(s)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove scheduled tasks: {e}")
            return False
    
    def update_schedule(self, settings, ctx_logger):
        """
        Update the backup schedule based on settings
        
        Args:
            settings: Plugin settings dictionary
            ctx_logger: Logger instance
        
        Returns:
            bool: True if successful
        """
        timezone_str = settings.get('timezone', 'America/Chicago')
        cron_str = settings.get('scheduled_times', '')
        
        # Validate timezone
        try:
            ZoneInfo(timezone_str)
        except Exception as e:
            ctx_logger.error(f"Invalid timezone '{timezone_str}': {e}")
            return False
        
        # Remove existing scheduled tasks
        self.remove_all_scheduled_tasks()
        
        # Parse cron schedule
        cron_schedule = self.parse_cron_schedule(cron_str)
        
        if not cron_schedule:
            if cron_str.strip():  # Only log if user entered something
                ctx_logger.warning(f"Invalid or empty cron format. Automatic backups disabled.")
            else:
                ctx_logger.info("No scheduled times configured. Automatic backups disabled.")
            return True
        
        # Create single scheduled task with the cron pattern
        task_name = f"{self.TASK_PREFIX}main"
        if self.create_or_update_schedule(cron_schedule, timezone_str, task_name):
            ctx_logger.info(f"Successfully configured backup schedule with cron pattern: {cron_str}")
            return True
        else:
            ctx_logger.error("Failed to create scheduled backup task")
            return False


# ============================================================================
# Celery Task for Scheduled Backups
# ============================================================================

from celery import shared_task

@shared_task(name='database_backup.scheduled_backup')
def scheduled_backup_task():
    """
    Celery task that runs on schedule to perform database backups
    """
    try:
        logger.info("Starting scheduled database backup...")
        
        # Initialize plugin
        plugin = Plugin()
        
        # Load settings
        settings = plugin.load_settings()
        
        # Create backup
        backup_file = plugin.create_backup(logger)
        
        if backup_file:
            logger.info(f"Scheduled backup completed successfully: {os.path.basename(backup_file)}")
            
            # Apply retention policy
            plugin.apply_retention(settings, logger)
        else:
            logger.error("Scheduled backup failed")
        
    except Exception as e:
        logger.error(f"Scheduled backup task failed: {e}", exc_info=True)
        raise
