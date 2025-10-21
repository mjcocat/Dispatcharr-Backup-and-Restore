# Database Backup Plugin for Dispatcharr

A simple and reliable database backup solution for Dispatcharr with automated retention management and one-click restore capabilities.

**Version:** v0.1.0  
**Author:** Community Plugin  
**License:** CC BY-NC-SA 4.0 (matching Dispatcharr)

---

## Features

✅ **One-Click Backups** - Create compressed database backups instantly  
✅ **One-Click Restore** - Restore any backup with a single click  
✅ **Automatic Retention** - Auto-cleanup based on age and count limits  
✅ **Compressed Storage** - Gzip compression saves ~80-90% disk space  
✅ **Clean Interface** - Simple, uncluttered UI with only essential actions  
✅ **Safe Restore** - Drops and recreates database for clean restoration  


---

## Installation

### Quick Install (Recommended)

1. **Download the Plugin**
   - Save the ZIP file to your computer

2. **Upload to Dispatcharr**
   - Navigate to **Settings → Plugins**
   - Click **Import Plugin**
   - Upload the ZIP file
   - Enable the plugin when prompted

3. **Restart Dispatcharr**
   ```bash
   docker restart dispatcharr
   ```


## Configuration

### Settings

Configure in **Settings → Plugins → Database Backup Manager → Settings**:

| Setting | Default | Description |
|---------|---------|-------------|
| **Retention Period (Days)** | `30` | Number of days to keep backups before auto-deletion |
| **Maximum Backups** | `14` | Maximum number of backups to keep (oldest deleted first) |

**Note:** The backup directory is fixed at `/data/backups` and compression is always enabled.


## Usage

### Creating a Backup

1. Navigate to **Settings → Plugins → Database Backup Manager**
2. Click **Run** next to **➕ Create Backup Now**
3. Wait for the success notification
4. The backup is automatically saved as: `dispatcharr_backup_YYYYMMDD_HHMMSS.sql.gz`

### Restoring a Backup

⚠️ **WARNING**: Restoring will completely replace your current database!

1. Navigate to **Settings → Plugins → Database Backup Manager**
2. Find the backup you want to restore in the list
3. Click **Run** next to **↻ Restore: [filename]**
4. Read the warning carefully and confirm
5. Wait for completion
6. **Restart Dispatcharr** (required):
   ```bash
   docker restart dispatcharr
   ```

### Deleting All Backups

1. Navigate to **Settings → Plugins → Database Backup Manager**
2. Click **Run** next to **🗑 Delete All Backups**
3. Confirm the deletion
4. All backup files will be permanently removed

---

## How It Works

### Backup Process

1. Connects to PostgreSQL database using Dispatcharr's credentials
2. Runs `pg_dump` to export all database data
3. Compresses the export using gzip (~80-90% size reduction)
4. Saves to `/data/backups/dispatcharr_backup_YYYYMMDD_HHMMSS.sql.gz`
5. Automatically cleans up old backups based on retention settings

### Restore Process

1. Terminates all active database connections
2. Drops the existing database completely
3. Creates a fresh empty database
4. Restores all data from the backup file
5. Requires a Dispatcharr restart to reconnect

**Why drop the database?** This ensures a clean restore without conflicts, constraint errors, or orphaned data.

### Automatic Cleanup

The plugin automatically maintains your backup retention by:
- Deleting backups older than the retention period
- Keeping only the maximum number of backups (deleting oldest first)
- Running cleanup after each new backup is created

---

## Backup Information

Each backup displays:
- **Filename** - `dispatcharr_backup_YYYYMMDD_HHMMSS.sql.gz`
- **Created** - Local timestamp when backup was created
- **Size** - Compressed file size in MB
- **Age** - Time since creation (hours if <24h, otherwise days)

Example:
```
↻ Restore: dispatcharr_backup_20251021_135132.sql.gz
    Created: 2025-10-21 01:51:35 PM | Size: 7.13 MB | 2h ago
```

---

## Troubleshooting

### "pg_dump command not found"

**Problem:** PostgreSQL client tools not installed in container.

**Solution:** The Dispatcharr container should include `postgresql-client` by default. If not, you may need to rebuild the container or use a different image.

### "Permission denied" on backup directory

**Problem:** Backup directory doesn't have proper permissions.

**Solution:**
```bash
docker exec dispatcharr chmod 755 /data/backups
```

### Restore fails with "must be owner of database"

**Problem:** The plugin couldn't authenticate with superuser privileges.

**Solution:** This is handled automatically by trying multiple superuser accounts. If it still fails, ensure `POSTGRES_PASSWORD` environment variable is set correctly in your docker-compose.yml.

### Timestamps showing wrong timezone

**Problem:** Server timezone doesn't match your local timezone.

**Solution:** Set the `TZ` environment variable in your docker-compose.yml:
```yaml
environment:
  - TZ=America/New_York  # Your timezone
```

### Backups are very large

**Problem:** Database contains a lot of data.

**Solution:** This is normal. The plugin uses gzip compression which typically reduces size by 80-90%. If backups are still too large, consider:
- Reducing retention period to keep fewer backups
- Reducing maximum backup count
- Adding external storage for the backup directory

---

## Best Practices

### 1. Regular Backups
- Create a backup before any major changes
- Create a backup before updating Dispatcharr
- Set a reasonable retention period (14-30 days recommended)

### 2. Test Your Backups
- Periodically test restoring to a test environment
- Verify backup files aren't corrupted
- Ensure the restore process works as expected

### 3. Off-Site Storage
- Copy important backups to another location
- Use cloud storage or external drives
- Keep at least one backup outside the server

### 4. Monitor Disk Space
- Check backup directory size regularly
- Adjust retention settings if needed
- Clean old backups if running low on space

### 5. Document Your Backups
- Keep track of important backup dates
- Document what changes were made before each backup
- Note which backups are known-good restore points

---


## File Locations

| Item | Location |
|------|----------|
| Backups | `/data/backups/` (inside container) |
| Plugin Code | `/data/plugins/database_backup/plugin.py` |
| Backup Format | `dispatcharr_backup_YYYYMMDD_HHMMSS.sql.gz` |

---

## Security Considerations

⚠️ **Important Security Notes:**

- Backup files contain your **entire database** including sensitive information
- Store backups in a **secure location** with proper access controls
- Consider **encrypting backups** for additional security
- **Limit access** to the backup directory
- **Never expose** backups via web server or public shares
- Use **strong database passwords** (backups inherit database security)

---

## Limitations

- **PostgreSQL Only** - Only works with PostgreSQL databases (Dispatcharr's default)
- **Single Database** - Backs up only the Dispatcharr database
- **No Incremental Backups** - Each backup is a full database dump
- **No Built-in Encryption** - Backups are not encrypted (compress only)
- **Manual Download** - No built-in download feature (use docker cp or volume mapping)
- **Same-Server Restore** - Cannot restore to a different server directly

---

## Frequently Asked Questions

### Q: How long does a backup take?
**A:** Typically 1-5 seconds for small databases, 10-30 seconds for larger ones. Depends on database size.

### Q: How much disk space do backups use?
**A:** With compression, usually 5-15 MB per backup. Actual size depends on your data.

### Q: Can I restore to a different Dispatcharr instance?
**A:** Yes, but you must manually copy the backup file to the target server and restore there.

### Q: Will restoring delete my current data?
**A:** Yes! Restoring completely replaces your current database. Always create a fresh backup before restoring.

### Q: Can I keep backups forever?
**A:** Yes, set retention period to a very high number (e.g., 3650 days) and increase max backups accordingly.

### Q: What happens if I run out of disk space?
**A:** Backups will fail. Monitor disk space and adjust retention settings as needed.

### Q: Can I download backups?
**A:** Use docker cp: `docker cp dispatcharr:/data/backups/[filename] ./` or map the volume to your host.

### Q: Do backups include plugin data?
**A:** Yes, backups include everything in the Dispatcharr database, including plugin configurations.

---

## Changelog

### v0.1.0 (2025-10-21)
- Initial release
- Create compressed database backups
- One-click restore with automatic database recreation
- Automatic retention management
- Delete all backups functionality
- Local timezone support
- Clean, simple interface

---


## Contributing

Contributions are welcome! If you find bugs or have suggestions:

1. Test your changes thoroughly
2. Follow the existing code style
3. Document any new features
4. Submit issues or pull requests to the Dispatcharr repository

---

## License

This plugin is provided under the same license as Dispatcharr:  
**CC BY-NC-SA 4.0** (Creative Commons Attribution-NonCommercial-ShareAlike 4.0)

- ✅ Share and adapt the plugin
- ✅ Give appropriate credit
- ❌ No commercial use
- ✅ Share modifications under the same license

---

## Acknowledgments

- **Dispatcharr Team** - For creating an excellent IPTV management platform
- **Community Contributors** - For testing and feedback


---

**Made with ❤️ for the Dispatcharr community**

*Last Updated: October 21, 2025*
