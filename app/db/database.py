"""
SQLAlchemy models and database engine setup.
"""
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text, Boolean, ForeignKey, Enum, event
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime
import enum

from app.core.config import settings

# Convert sync SQLite URL to async 
def _make_async_url(url: str) -> str:
    if url.startswith("sqlite+aiosqlite://"):
        return url          # already async — pass through as-is
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


ASYNC_DB_URL = _make_async_url(settings.DATABASE_URL)

_is_sqlite = ASYNC_DB_URL.startswith("sqlite")

from sqlalchemy.pool import NullPool

# For SQLite: use NullPool to ensure connections are closed and flushed to disk
if _is_sqlite:
    engine = create_async_engine(
        ASYNC_DB_URL,
        echo=settings.DEBUG,
        future=True,
        connect_args={
            "check_same_thread": False,
            "timeout": 30,          # 30s busy timeout
        },
        poolclass=NullPool,       # Ensure connection is closed after request, flushing to disk
    )
else:
    engine = create_async_engine(ASYNC_DB_URL, echo=settings.DEBUG, future=True)

# Standard pragmas for SQLite
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _):
    if _is_sqlite:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=DELETE;") # Avoid WAL across WSL/Windows boundary
        cursor.execute("PRAGMA synchronous=FULL;")
        cursor.execute("PRAGMA busy_timeout=30000;")  # 30s
        cursor.close()


AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


# Enums
class InterviewStatus(str, enum.Enum):
    PENDING    = "pending"
    SCHEDULED  = "scheduled"
    IN_CALL    = "in_call"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class CandidateStatus(str, enum.Enum):
    UPLOADED    = "uploaded"
    SELECTED    = "selected"     # legacy/backwards compatibility
    FILTERED    = "filtered"
    REJECTED    = "rejected"
    CONTACTED   = "contacted"
    SCHEDULED   = "scheduled"
    INTERVIEWED = "interviewed"


# ORM Models 
class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id          = Column(String, primary_key=True)
    title       = Column(String, nullable=False)
    company     = Column(String)
    jd_text     = Column(Text, nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

    candidates  = relationship("Candidate", back_populates="job")


class Candidate(Base):
    __tablename__ = "candidates"

    id              = Column(String, primary_key=True)
    job_id          = Column(String, ForeignKey("job_descriptions.id"), nullable=False)
    name            = Column(String)
    email           = Column(String)
    phone           = Column(String)
    resume_path     = Column(String)
    resume_text     = Column(Text)
    match_score     = Column(Float, default=0.0)
    status          = Column(Enum(CandidateStatus), default=CandidateStatus.UPLOADED)
    schedule_token  = Column(String, unique=True)          # UUID token for scheduling link
    interview_dt    = Column(DateTime, nullable=True)       # confirmed interview datetime
    created_at      = Column(DateTime, default=datetime.utcnow)

    job             = relationship("JobDescription", back_populates="candidates")
    interview       = relationship("InterviewSession", back_populates="candidate", uselist=False)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id              = Column(String, primary_key=True)
    candidate_id    = Column(String, ForeignKey("candidates.id"), nullable=False)
    job_id          = Column(String, ForeignKey("job_descriptions.id"), nullable=True)
    status          = Column(Enum(InterviewStatus), default=InterviewStatus.PENDING)
    call_room_id    = Column(String, nullable=True)
    scheduled_at    = Column(DateTime, nullable=True)      # when the call is scheduled
    job_title       = Column(String, nullable=True)        # denormalized for quick access
    company         = Column(String, nullable=True)        # denormalized for quick access
    jd_text         = Column(Text, nullable=True)          # denormalized JD for agent
    transcript      = Column(Text, nullable=True)
    analysis_json   = Column(Text, nullable=True)          # JSON blob from LangGraph
    score           = Column(Float, nullable=True)
    recommendation  = Column(String, nullable=True)        # "HIRE" | "MAYBE" | "REJECT"
    report_path     = Column(String, nullable=True)
    report_sent     = Column(Boolean, default=False)
    started_at      = Column(DateTime, nullable=True)
    ended_at        = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    candidate       = relationship("Candidate", back_populates="interview")


# Dependency 
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create all tables on startup. Handle corrupted databases gracefully."""
    global engine, AsyncSessionLocal
    import os
    import asyncio
    
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        # If database is corrupted, try to delete and recreate
        if "disk I/O error" in str(e) or "database disk image is malformed" in str(e):
            from app.core.logger import get_logger
            log = get_logger(__name__)
            
            log.warning(f"Database corrupted: {e}. Attempting to recreate...")
            
            # Dispose of all connections
            await engine.dispose()
            
            # Wait a moment for connections to close
            await asyncio.sleep(1)
            
            # Delete corrupted database files
            db_path = "./hanrry.db"
            for suffix in ["", "-journal", "-wal", "-shm"]:
                try:
                    if os.path.exists(db_path + suffix):
                        os.remove(db_path + suffix)
                        log.info(f"Deleted {db_path + suffix}")
                except Exception as delete_err:
                    log.warning(f"Could not delete {db_path + suffix}: {delete_err}")
            
            # Recreate the engine
            from sqlalchemy.ext.asyncio import create_async_engine
            from sqlalchemy.orm import sessionmaker
            
            engine = create_async_engine(ASYNC_DB_URL, echo=settings.DEBUG, future=True)
            AsyncSessionLocal = sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            
            # Try creating tables again
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                log.info("Database successfully recreated")
            except Exception as retry_err:
                log.error(f"Failed to recreate database: {retry_err}")
                raise
        else:
            raise
