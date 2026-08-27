"""
JD Filter Router
POST /api/jd/create-job   – register a new job description
POST /api/jd/filter       – filter uploaded candidates against a JD
"""
import uuid
from pydantic import BaseModel
from sqlalchemy import update

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    get_db, create_job, get_job,
    get_candidates_by_job, update_candidate_status,
    CandidateStatus,
)
from app.db import crud
from app.db.database import Candidate
from app.models import JDFilterRequest, JDFilterResponse, FilteredCandidate
from app.services import filter_candidates, send_schedule_email
from app.core.logger import get_logger
from app.core.config import settings

log = get_logger(__name__)

router = APIRouter(prefix="/api/jd", tags=["Job Description"])


# ─────────────────────── Create Job ───────────────────────────────────────────

class CreateJobBody(BaseModel):
    title: str
    company: str = ""
    jd_text: str


@router.post(
    "/create-job",
    summary="Register a new job description",
    status_code=status.HTTP_201_CREATED,
)
async def create_job_endpoint(
    body: CreateJobBody,
    db: AsyncSession = Depends(get_db),
):
    job_id = str(uuid.uuid4())
    await create_job(
        db, id=job_id,
        title=body.title,
        company=body.company,
        jd_text=body.jd_text,
    )
    log.info(f"Job created: {job_id} | {body.title}")
    return {"job_id": job_id, "title": body.title, "message": "Job description registered."}


# ─────────────────────── Filter Candidates ────────────────────────────────────

@router.post(
    "/filter",
    response_model=JDFilterResponse,
    summary="Filter uploaded resumes against a Job Description",
)
async def filter_candidates_endpoint(
    body: JDFilterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    1. Load all UPLOADED candidates for the job
    2. Score each resume against the JD using LLM
    3. Mark filtered candidates and extract name from LLM result
    4. Send scheduling emails to filtered candidates in background
    5. Return filtered list with scores
    """
    # ── Validate / auto-create job ────────────────────────────────────────────
    job = await get_job(db, body.job_id)
    if not job:
        await create_job(
            db, id=body.job_id,
            title=body.job_title,
            company=body.company,
            jd_text=body.jd_text,
        )

    # ── Load candidates ───────────────────────────────────────────────────────
    all_candidates = await get_candidates_by_job(db, body.job_id)
    if not all_candidates:
        raise HTTPException(
            status_code=404,
            detail=f"No candidates found for job_id={body.job_id}. Upload resumes first.",
        )

    to_score = [
        (c.id, c.resume_text)
        for c in all_candidates
        if c.status == CandidateStatus.UPLOADED and c.resume_text
    ]

    if not to_score:
        raise HTTPException(
            status_code=409,
            detail="All candidates for this job have already been filtered.",
        )

    # ── Score resumes via LLM ─────────────────────────────────────────────────
    scored = await filter_candidates(
        jd_text=body.jd_text,
        candidates=to_score,
        min_score=body.min_score,
    )

    # ── Mark rejected candidates ──────────────────────────────────────────────
    scored_ids = {cid for cid, _, _ in scored}
    for cid, _ in to_score:
        if cid not in scored_ids:
            await update_candidate_status(db, cid, CandidateStatus.REJECTED)

    # ── Update filtered candidates and send emails ────────────────────────────
    result_list = []
    for cand_id, score, llm_result in scored:
        detected_name = llm_result.get("candidate_name", "")
        clean_name = detected_name if detected_name and detected_name.upper() != "UNKNOWN" else None

        # Update name, score, and status cleanly using proper SQLAlchemy import
        await db.execute(
            update(Candidate)
            .where(Candidate.id == cand_id)
            .values(
                name=clean_name,
                match_score=score,
                status=CandidateStatus.FILTERED,
            )
        )
        await db.commit()

        # Reload candidate for email/phone info
        candidate = await crud.get_candidate(db, cand_id)

        # Build scheduling link
        schedule_link = (
            f"{settings.BASE_URL}/api/schedule/confirm?token={candidate.schedule_token}"
        )

        # Send scheduling email asynchronously if email exists
        if candidate.email:
            background_tasks.add_task(
                send_schedule_email,
                to_email=candidate.email,
                candidate_name=candidate.name or "Candidate",
                job_title=body.job_title,
                company=body.company,
                schedule_link=schedule_link,
            )
            await update_candidate_status(db, cand_id, CandidateStatus.CONTACTED)
            log.info(f"Scheduling email queued → {candidate.email}")

        result_list.append(FilteredCandidate(
            candidate_id=cand_id,
            name=candidate.name,
            email=candidate.email,
            phone=candidate.phone,
            match_score=round(score, 3),
            status=CandidateStatus.CONTACTED if candidate.email else CandidateStatus.FILTERED,
        ))

    return JDFilterResponse(
        job_id=body.job_id,
        total_candidates=len(to_score),
        filtered_count=len(result_list),
        candidates=result_list,
    )
