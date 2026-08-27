from fastapi import APIRouter, BackgroundTasks, status
from pydantic import BaseModel
from app.tasks.cleanup_task import run_storage_cleanup
from app.core.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/system", tags=["System"])


class CleanupRequest(BaseModel):
    days_old: int = 7


@router.post("/cleanup", status_code=status.HTTP_200_OK, summary="Manually trigger storage cleanup")
async def trigger_cleanup(request: CleanupRequest, background_tasks: BackgroundTasks):
    """
    Manually clean up old resumes and reports.
    Runs in the background.
    """
    background_tasks.add_task(run_storage_cleanup, request.days_old)
    log.info(f"Manual cleanup triggered for files older than {request.days_old} days.")
    return {"message": f"Cleanup task started for files older than {request.days_old} days."}
