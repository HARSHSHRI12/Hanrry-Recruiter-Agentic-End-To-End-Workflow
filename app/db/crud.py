"""
CRUD operations for all database models.
"""
import json
from datetime import datetime
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import JobDescription, Candidate, InterviewSession, CandidateStatus, InterviewStatus
from app.core.logger import get_logger

log = get_logger(__name__)


# ─────────────────────────── JobDescription ──────────────────────────────────

async def create_job(db: AsyncSession, id: str, title: str, company: str, jd_text: str) -> JobDescription:
    job = JobDescription(id=id, title=title, company=company, jd_text=jd_text)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_job(db: AsyncSession, job_id: str) -> Optional[JobDescription]:
    result = await db.execute(select(JobDescription).where(JobDescription.id == job_id))
    return result.scalar_one_or_none()


# ─────────────────────────── Candidate ───────────────────────────────────────

async def create_candidate(db: AsyncSession, **kwargs) -> Candidate:
    candidate = Candidate(**kwargs)
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)
    return candidate


async def get_candidate(db: AsyncSession, candidate_id: str) -> Optional[Candidate]:
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    return result.scalar_one_or_none()


async def get_candidate_by_token(db: AsyncSession, token: str) -> Optional[Candidate]:
    result = await db.execute(select(Candidate).where(Candidate.schedule_token == token))
    return result.scalar_one_or_none()


async def get_candidates_by_job(db: AsyncSession, job_id: str) -> List[Candidate]:
    result = await db.execute(select(Candidate).where(Candidate.job_id == job_id))
    return result.scalars().all()


async def update_candidate_status(db: AsyncSession, candidate_id: str, status: CandidateStatus):
    await db.execute(
        update(Candidate).where(Candidate.id == candidate_id).values(status=status)
    )
    await db.commit()


async def set_candidate_interview_time(db: AsyncSession, candidate_id: str, dt: datetime):
    await db.execute(
        update(Candidate).where(Candidate.id == candidate_id).values(
            interview_dt=dt, status=CandidateStatus.SCHEDULED
        )
    )
    await db.commit()


# ─────────────────────────── InterviewSession ─────────────────────────────────

async def create_interview_session(
    db: AsyncSession,
    id: str,
    candidate_id: str,
    job_id: str = None,
    job_title: str = None,
    company: str = None,
    jd_text: str = None,
    scheduled_at=None,
) -> InterviewSession:
    session = InterviewSession(
        id=id,
        candidate_id=candidate_id,
        job_id=job_id,
        job_title=job_title,
        company=company,
        jd_text=jd_text,
        scheduled_at=scheduled_at,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_interview_session(db: AsyncSession, session_id: str) -> Optional[InterviewSession]:
    result = await db.execute(select(InterviewSession).where(InterviewSession.id == session_id))
    return result.scalar_one_or_none()


async def update_interview_session(db: AsyncSession, session_id: str, **kwargs):
    await db.execute(
        update(InterviewSession).where(InterviewSession.id == session_id).values(**kwargs)
    )
    await db.commit()


async def save_transcript_and_analysis(
    db: AsyncSession,
    session_id: str,
    transcript: str,
    analysis: dict,
    score: float,
    recommendation: str,
):
    await db.execute(
        update(InterviewSession)
        .where(InterviewSession.id == session_id)
        .values(
            transcript=transcript,
            analysis_json=json.dumps(analysis),
            score=score,
            recommendation=recommendation,
            status=InterviewStatus.COMPLETED,
            ended_at=datetime.utcnow(),
        )
    )
    await db.commit()
