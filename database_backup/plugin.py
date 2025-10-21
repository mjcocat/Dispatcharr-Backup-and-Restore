"""
Dispatcharr Database Backup Plugin - plugin.py
Provides automated and on-demand database backups with retention management and restore capabilities.
"""

import os
import subprocess
import json
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
import glob
from django.conf import settings as django_settings

class Plugin:
    """Database Backup Plugin for Dispatcharr"""
    
    id = "database_backup"
    name = "Database Backup Manager"
    version = "0.1.0"
    description = "Automated database backups with retention management and restore capabilities"
    author = "Your Name"
    
    def __init__(self):
        """Initialize the plugin"""
        self.backup_path = "/data/backups"
        self.compression_enabled = True
    
    # Settings fields rendered by the UI and persisted by the backend
    fields = [
        {
            "id": "retention_days",
            "label": "Retention Period (Days)",
            "type": "number",
            "default": 30,
            "help": "Number of days to keep backups before automatic deletion"
        },
        {
            "id": "max_backups",
            "label": "Maximum Backups",
            "type": "number",
            "default": 14,
            "help": "Maximum number of backups to keep (oldest will be deleted first)"
        }
    ]
    
    @property
    def actions(self):
        """Generate actions dynamically including one for each backup"""
        base_actions = [
            {
                "id": "create_backup",
                "label": "➕ Create Backup Now",
                "description": "Create a new database backup",
                "confirm": False
            },
            {
                "id": "delete_all_backups",
                "label": "🗑 Delete All Backups",
                "description": "Permanently delete all backup files",
                "confirm": {
                    "required": True,
                    "title": "⚠️ WARNING: Delete ALL Backups?",
                    "message": "This will permanently delete ALL backup files!\n\nThis action cannot be undone.\n\nAre you absolutely sure?"
                }
            }
        ]
        
        # Get all backups and create actions for each
        backups = self._get_all_backups()
        
        if backups:
            for backup in backups:
                # Add restore action with all backup info
                base_actions.append({
                    "id": f"restore_{backup['filename']}",
                    "label": f"↻ Restore: {backup['filename']}",
                    "description": f"Created: {backup['created']} | Size: {backup['size_mb']} MB | {backup['age_display']}",
                    "confirm": {
                        "required": True,
                        "title": "⚠️ WARNING: Overwrite Database?",
                        "message": f"This will replace ALL current data with the backup from:\n{backup['filename']}\n\nCreated: {backup['created']}\nSize: {backup['size_mb']} MB\n\nAre you absolutely sure?"
                    }
                })
        
        return base_actions
    
    def run(self, action, params, context):
        """Execute plugin actions"""
        logger = context.get("logger")
        settings = context.get("settings", {})
        
        logger.info(f"Running action: {action}")
        
        try:
            if action == "create_backup":
                result = self._create_backup(settings, logger)
                result["reload"] = True  # Signal to reload the plugin
                return result
            elif action == "delete_all_backups":
                result = self._delete_all_backups(settings, logger)
                result["reload"] = True  # Signal to reload the plugin
                return result
            elif action.startswith("restore_"):
                filename = action.replace("restore_", "")
                return self._restore_backup(filename, settings, logger)
            else:
                # Disabled or header actions
                return {"success": True, "message": "No action required"}
                
        except Exception as e:
            logger.error(f"Error executing action {action}: {str(e)}")
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def _get_db_credentials(self):
        """Get database credentials from Django settings"""
        db_settings = django_settings.DATABASES.get('default', {})
        
        # Get regular database credentials
        creds = {
            "host": db_settings.get("HOST", "localhost"),
            "port": str(db_settings.get("PORT", "5432")),
            "name": db_settings.get("NAME", "dispatcharr"),
            "user": db_settings.get("USER", "dispatch"),
            "password": db_settings.get("PASSWORD", "")
        }
        
        # Try to get superuser credentials from environment for restore operations
        # These are typically the POSTGRES_USER from docker-compose
        creds["superuser"] = os.getenv("POSTGRES_USER", creds["user"])
        creds["superuser_password"] = os.getenv("POSTGRES_PASSWORD", creds["password"])
        
        return creds
    
    def _ensure_backup_directory(self):
        """Ensure backup directory exists"""
        Path(self.backup_path).mkdir(parents=True, exist_ok=True)
    
    def _get_backup_filename(self):
        """Generate backup filename with timestamp"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"dispatcharr_backup_{timestamp}.sql.gz"
    
    def _get_all_backups(self):
        """Get list of all backup files with metadata"""
        if not os.path.exists(self.backup_path):
            return []
        
        # Find all backup files
        backup_files = []
        for pattern in ["dispatcharr_backup_*.sql", "dispatcharr_backup_*.sql.gz"]:
            backup_files.extend(glob.glob(os.path.join(self.backup_path, pattern)))
        
        # Sort by modification time (newest first)
        backup_files.sort(key=os.path.getmtime, reverse=True)
        
        # Get local timezone offset
        now = datetime.now()
        local_tz = now.astimezone().tzinfo
        
        # Format backup info
        backups_info = []
        for backup_file in backup_files:
            stat = os.stat(backup_file)
            # Convert UTC timestamp to local timezone
            created_utc = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            created_local = created_utc.astimezone(local_tz)
            size_mb = stat.st_size / (1024 * 1024)
            
            # Calculate age in hours or days
            age_delta = now - created_local.replace(tzinfo=None)
            age_hours = age_delta.total_seconds() / 3600
            if age_hours < 24:
                age_display = f"{int(age_hours)}h ago"
            else:
                age_days = int(age_hours / 24)
                age_display = f"{age_days}d ago"
            
            backups_info.append({
                "filename": os.path.basename(backup_file),
                "full_path": backup_file,
                "created": created_local.strftime("%Y-%m-%d %I:%M:%S %p"),  # Local time with AM/PM
                "created_timestamp": stat.st_mtime,
                "size_mb": round(size_mb, 2),
                "age_display": age_display
            })
        
        return backups_info
    
    def _create_backup(self, settings, logger):
        """Create a database backup"""
        self._ensure_backup_directory()
        
        db_creds = self._get_db_credentials()
        backup_file = os.path.join(self.backup_path, self._get_backup_filename())
        
        logger.info(f"Creating backup: {backup_file}")
        
        # Build pg_dump command
        env = os.environ.copy()
        env["PGPASSWORD"] = db_creds["password"]
        
        cmd = [
            "pg_dump",
            "-h", db_creds["host"],
            "-p", db_creds["port"],
            "-U", db_creds["user"],
            "-d", db_creds["name"],
            "--format=plain",
            "--no-owner",
            "--no-privileges"
        ]
        
        try:
            # Execute pg_dump
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Write output to compressed file
            import gzip
            with gzip.open(backup_file, 'wt', encoding='utf-8') as f:
                f.write(result.stdout)
            
            # Get file size
            file_size = os.path.getsize(backup_file)
            size_mb = file_size / (1024 * 1024)
            
            logger.info(f"Backup created successfully: {backup_file} ({size_mb:.2f} MB)")
            
            # Clean up old backups automatically
            self._cleanup_old_backups(settings, logger)
            
            return {
                "success": True,
                "message": f"✅ Backup created successfully!\n\n📁 {os.path.basename(backup_file)}\n💾 Size: {size_mb:.2f} MB",
                "reload": True
            }
            
        except subprocess.CalledProcessError as e:
            logger.error(f"pg_dump failed: {e.stderr}")
            return {
                "success": False,
                "message": f"❌ Backup failed: {e.stderr}"
            }
    
    def _cleanup_old_backups(self, settings, logger):
        """Remove old backups based on retention settings"""
        retention_days = settings.get("retention_days", 30)
        max_backups = settings.get("max_backups", 14)
        
        if not os.path.exists(self.backup_path):
            return {
                "success": True,
                "message": "No cleanup needed (no backup directory)"
            }
        
        # Find all backup files
        backup_files = []
        for pattern in ["dispatcharr_backup_*.sql", "dispatcharr_backup_*.sql.gz"]:
            backup_files.extend(glob.glob(os.path.join(self.backup_path, pattern)))
        
        if not backup_files:
            return {
                "success": True,
                "message": "No backups to clean up"
            }
        
        # Sort by modification time (oldest first for deletion)
        backup_files.sort(key=os.path.getmtime)
        
        deleted_count = 0
        deleted_size = 0
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        # Delete backups older than retention period
        for backup_file in backup_files:
            stat = os.stat(backup_file)
            created = datetime.fromtimestamp(stat.st_mtime)
            
            if created < cutoff_date:
                logger.info(f"Deleting old backup: {backup_file}")
                deleted_size += stat.st_size
                os.remove(backup_file)
                deleted_count += 1
        
        # If still over max_backups, delete oldest ones
        remaining_backups = [f for f in backup_files if os.path.exists(f)]
        remaining_backups.sort(key=os.path.getmtime)
        
        while len(remaining_backups) > max_backups:
            oldest_backup = remaining_backups.pop(0)
            stat = os.stat(oldest_backup)
            logger.info(f"Deleting excess backup: {oldest_backup}")
            deleted_size += stat.st_size
            os.remove(oldest_backup)
            deleted_count += 1
        
        deleted_size_mb = deleted_size / (1024 * 1024)
        
        if deleted_count > 0:
            message = f"🧹 Cleaned up {deleted_count} old backup(s)\n💾 Freed {deleted_size_mb:.2f} MB of disk space"
        else:
            message = "✅ No old backups to clean up"
        
        logger.info(message)
        
        return {
            "success": True,
            "message": message,
            "deleted_count": deleted_count,
            "freed_mb": round(deleted_size_mb, 2),
            "reload": True
        }
    
    def _delete_all_backups(self, settings, logger):
        """Delete all backup files"""
        if not os.path.exists(self.backup_path):
            return {
                "success": True,
                "message": "No backups to delete (backup directory doesn't exist)"
            }
        
        # Find all backup files
        backup_files = []
        for pattern in ["dispatcharr_backup_*.sql", "dispatcharr_backup_*.sql.gz"]:
            backup_files.extend(glob.glob(os.path.join(self.backup_path, pattern)))
        
        if not backup_files:
            return {
                "success": True,
                "message": "📭 No backups to delete"
            }
        
        # Delete all backups
        deleted_count = 0
        deleted_size = 0
        
        for backup_file in backup_files:
            try:
                stat = os.stat(backup_file)
                deleted_size += stat.st_size
                os.remove(backup_file)
                deleted_count += 1
                logger.info(f"Deleted backup: {backup_file}")
            except Exception as e:
                logger.error(f"Failed to delete {backup_file}: {str(e)}")
        
        deleted_size_mb = deleted_size / (1024 * 1024)
        
        logger.warning(f"Deleted all {deleted_count} backups, freed {deleted_size_mb:.2f} MB")
        
        return {
            "success": True,
            "message": f"✅ All backups deleted!\n\n🗑️ Deleted: {deleted_count} backup(s)\n💾 Freed: {deleted_size_mb:.2f} MB",
            "reload": True
        }
    
    def _restore_backup(self, filename, settings, logger):
        """Restore database from a backup file"""
        backup_file = os.path.join(self.backup_path, filename)
        
        if not os.path.exists(backup_file):
            return {
                "success": False,
                "message": f"❌ Backup file not found: {filename}"
            }
        
        logger.warning(f"Starting database restore from: {backup_file}")
        
        db_creds = self._get_db_credentials()
        
        # Try multiple superuser options in order of preference
        superuser_options = [
            (db_creds["superuser"], db_creds["superuser_password"]),  # POSTGRES_USER from env
            ("postgres", db_creds["superuser_password"]),  # Standard postgres superuser
            ("postgres", ""),  # Try no password
        ]
        
        drop_success = False
        admin_user = None
        admin_password = None
        
        # Try each superuser option until one works
        for su_user, su_pass in superuser_options:
            env = os.environ.copy()
            env["PGPASSWORD"] = su_pass
            
            logger.info(f"Attempting to use superuser: {su_user}")
            
            try:
                # Step 1: Terminate all connections to the database
                logger.info("Terminating existing database connections...")
                terminate_sql = f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = '{db_creds["name"]}'
                AND pid <> pg_backend_pid();
                """
                
                terminate_cmd = [
                    "psql",
                    "-h", db_creds["host"],
                    "-p", db_creds["port"],
                    "-U", su_user,
                    "-d", "postgres",
                    "-c", terminate_sql
                ]
                
                subprocess.run(
                    terminate_cmd,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False  # Don't fail if no connections to terminate
                )
                
                # Step 2: Drop the database
                logger.info(f"Dropping database: {db_creds['name']}")
                drop_cmd = [
                    "psql",
                    "-h", db_creds["host"],
                    "-p", db_creds["port"],
                    "-U", su_user,
                    "-d", "postgres",
                    "-c", f"DROP DATABASE IF EXISTS {db_creds['name']};"
                ]
                
                result = subprocess.run(
                    drop_cmd,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                # If we got here, drop succeeded
                drop_success = True
                admin_user = su_user
                admin_password = su_pass
                logger.info(f"Successfully authenticated as superuser: {su_user}")
                break
                
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed with user {su_user}: {e.stderr}")
                continue
        
        if not drop_success:
            return {
                "success": False,
                "message": f"❌ Restore failed: Unable to drop database.\n\nNo superuser credentials worked. Please ensure POSTGRES_PASSWORD environment variable is set correctly.\n\nTried users: {', '.join([opt[0] for opt in superuser_options])}"
            }
        
        try:
            # Step 3: Create a fresh database with correct owner
            logger.info(f"Creating fresh database: {db_creds['name']}")
            env = os.environ.copy()
            env["PGPASSWORD"] = admin_password
            
            create_cmd = [
                "psql",
                "-h", db_creds["host"],
                "-p", db_creds["port"],
                "-U", admin_user,
                "-d", "postgres",
                "-c", f"CREATE DATABASE {db_creds['name']} OWNER {db_creds['user']};"
            ]
            
            result = subprocess.run(
                create_cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Step 4: Read backup file
            logger.info(f"Reading backup file: {backup_file}")
            if backup_file.endswith('.gz'):
                import gzip
                with gzip.open(backup_file, 'rt', encoding='utf-8') as f:
                    sql_content = f.read()
            else:
                with open(backup_file, 'r', encoding='utf-8') as f:
                    sql_content = f.read()
            
            # Step 5: Restore the backup into the fresh database (use regular user)
            logger.info("Restoring backup data...")
            restore_env = os.environ.copy()
            restore_env["PGPASSWORD"] = db_creds["password"]
            
            restore_cmd = [
                "psql",
                "-h", db_creds["host"],
                "-p", db_creds["port"],
                "-U", db_creds["user"],
                "-d", db_creds["name"]
            ]
            
            result = subprocess.run(
                restore_cmd,
                input=sql_content,
                env=restore_env,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"Database restored successfully from: {backup_file}")
            
            return {
                "success": True,
                "message": f"✅ Database restored successfully!\n\n📁 From: {filename}\n\n⚠️ CRITICAL: You MUST restart Dispatcharr now!\n\nRun: docker restart dispatcharr\n\nThe database has been completely replaced."
            }
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Database restore failed: {e.stderr}")
            return {
                "success": False,
                "message": f"❌ Restore failed:\n\n{e.stderr}\n\n⚠️ Database may be in an inconsistent state. Please check logs and restore manually if needed."
            }
        except Exception as e:
            logger.error(f"Restore error: {str(e)}")
            return {
                "success": False,
                "message": f"❌ Restore error: {str(e)}"
            }
    
    def _delete_backup(self, filename, settings, logger):
        """Delete a backup file"""
        backup_file = os.path.join(self.backup_path, filename)
        
        if not os.path.exists(backup_file):
            return {
                "success": False,
                "message": f"❌ Backup file not found: {filename}"
            }
        
        try:
            # Get file size before deletion
            size_mb = os.path.getsize(backup_file) / (1024 * 1024)
            
            # Delete the file
            os.remove(backup_file)
            
            logger.info(f"Deleted backup: {backup_file}")
            
            return {
                "success": True,
                "message": f"✅ Backup deleted successfully!\n\n🗑️ {filename}\n💾 Freed {size_mb:.2f} MB",
                "reload": True
            }
            
        except Exception as e:
            logger.error(f"Error deleting backup: {str(e)}")
            return {
                "success": False,
                "message": f"❌ Error deleting backup: {str(e)}"
            }
