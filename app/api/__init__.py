from app.api.resume_router import router as resume_router
from app.api.jd_router import router as jd_router
from app.api.schedule_router import router as schedule_router
from app.api.report_router import router as report_router

__all__ = ["resume_router", "jd_router", "schedule_router", "report_router"]
