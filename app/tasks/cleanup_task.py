import os
import time
from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)

# Paths
_REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reports")
_UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), settings.UPLOAD_DIR)


async def run_storage_cleanup(days_old: int = 7):
    """
    Deletes files in reports/ and uploads/ that are older than `days_old`.
    """
    log.info(f"🧹 Starting storage cleanup for files older than {days_old} days.")
    
    current_time = time.time()
    age_in_seconds = days_old * 86400  # 24 * 60 * 60
    
    deleted_count = 0
    
    for directory in [_REPORTS_DIR, _UPLOADS_DIR]:
        if not os.path.exists(directory):
            continue
            
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                
                # Check file age based on modification time
                if os.path.isfile(file_path):
                    file_age = current_time - os.path.getmtime(file_path)
                    if file_age > age_in_seconds:
                        try:
                            os.remove(file_path)
                            log.debug(f"Deleted old file: {file_path}")
                            deleted_count += 1
                        except Exception as e:
                            log.error(f"Failed to delete {file_path}: {e}")
                            
    log.info(f"✅ Storage cleanup complete. Deleted {deleted_count} files.")
    return deleted_count
