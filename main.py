"""
Hanrry AI Screening Recruiter — FastAPI Application Entry Point
"""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logger import get_logger
from app.db.database import init_db
from app.services.scheduler import start_scheduler, shutdown_scheduler
from app.api.resume_router import router as resume_router
from app.api.jd_router import router as jd_router
from app.api.schedule_router import router as schedule_router
from app.api.report_router import router as report_router
from app.api.system_router import router as system_router

log = get_logger("hanrry.main")


#  Lifespan (startup / shutdown) 

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(" Hanrry AI Recruiter starting up...")

    # Create upload and report directories
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    # Initialize database tables
    await init_db()
    log.info(" Database initialized.")

    # Start APScheduler
    start_scheduler()
    log.info(" Scheduler started.")

    yield  # App is running

    # Graceful shutdown
    shutdown_scheduler()
    log.info(" Hanrry AI Recruiter shut down.")


# FastAPI App 

app = FastAPI(
    title="Hanrry AI Screening Recruiter",
    description=(
        "End-to-end production-grade AI recruiter: "
        "resume upload → JD filtering → AI telephonic interview → analysis → report"
    ),
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"Unhandled error on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again later."},
    )


# Routers 
app.include_router(resume_router)
app.include_router(jd_router)
app.include_router(schedule_router)
app.include_router(report_router)
app.include_router(system_router)


# Health Check
@app.get("/health", tags=["System"])
async def health():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@app.get("/", tags=["System"])
async def root():
    return {
        "message": "Welcome to Hanrry AI Screening Recruiter API",
        "docs": "/docs",
        "health": "/health",
    }
