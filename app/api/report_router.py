"""
Report Router
GET /api/reports/{session_id}         – get analysis report JSON
GET /api/reports/{session_id}/pdf     – download PDF report
POST /api/reports/{session_id}/resend – resend report email to recruiter
GET /api/reports/job/{job_id}         – list all reports for a job
"""
import os
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db, get_interview_session, update_interview_session, get_candidates_by_job
from app.db import crud
from app.models import InterviewAnalysis, QuestionAnalysis, RecommendationEnum, ReportResponse
from app.services.email_service import send_report_email
from app.core.config import settings
from app.core.logger import get_logger

import json
from datetime import datetime
from typing import List

log = get_logger(__name__)

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.get(
    "/{session_id}",
    response_model=InterviewAnalysis,
    summary="Get full interview analysis for a session",
)
async def get_report(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await get_interview_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    candidate = await crud.get_candidate(db, session.candidate_id)
    job       = await crud.get_job(db, candidate.job_id) if candidate else None

    # Parse analysis JSON
    analysis = {}
    if session.analysis_json:
        try:
            analysis = json.loads(session.analysis_json)
        except Exception:
            pass

    breakdown = []
    for qa in analysis.get("question_breakdown", []):
        try:
            breakdown.append(QuestionAnalysis(
                question=qa.get("question", ""),
                answer=qa.get("answer", ""),
                score=float(qa.get("score", 5.0)),
                feedback=qa.get("feedback", ""),
            ))
        except Exception:
            pass

    return InterviewAnalysis(
        session_id=session_id,
        candidate_name=candidate.name if candidate else None,
        job_title=job.title if job else "Unknown",
        total_score=session.score or 0.0,
        recommendation=RecommendationEnum(session.recommendation or "MAYBE"),
        strengths=analysis.get("strengths", []),
        weaknesses=analysis.get("weaknesses", []),
        question_breakdown=breakdown,
        summary=analysis.get("summary", "No summary available."),
        interviewed_at=session.ended_at or session.created_at,
    )


@router.get(
    "/{session_id}/pdf",
    summary="Download PDF report for a session",
)
async def download_pdf_report(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await get_interview_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    if not session.report_path or not os.path.exists(session.report_path):
        raise HTTPException(
            status_code=404,
            detail="PDF report not yet generated. Interview may still be in progress.",
        )

    return FileResponse(
        path=session.report_path,
        media_type="application/pdf",
        filename=os.path.basename(session.report_path),
    )


@router.post(
    "/{session_id}/resend",
    response_model=ReportResponse,
    summary="Resend report email to recruiter",
)
async def resend_report(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await get_interview_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    candidate = await crud.get_candidate(db, session.candidate_id)
    job       = await crud.get_job(db, candidate.job_id) if candidate else None

    if not session.report_path or not os.path.exists(session.report_path):
        raise HTTPException(
            status_code=400,
            detail="PDF report not available. Cannot resend.",
        )

    analysis = json.loads(session.analysis_json or "{}")

    send_report_email(
        candidate_name=candidate.name or "Candidate",
        candidate_email=candidate.email or "N/A",
        candidate_phone=candidate.phone or "N/A",
        job_title=job.title if job else "Unknown",
        interview_date=session.ended_at.strftime("%B %d, %Y %H:%M UTC") if session.ended_at else "N/A",
        total_score=session.score or 0.0,
        recommendation=session.recommendation or "MAYBE",
        summary=analysis.get("summary", ""),
        pdf_path=session.report_path,
    )

    await update_interview_session(db, session_id, report_sent=True)
    log.info(f"Report resent for session={session_id}")

    return ReportResponse(
        session_id=session_id,
        report_path=session.report_path,
        report_sent_to=settings.RECRUITER_EMAIL,
        message="Report successfully resent to recruiter.",
    )


@router.get(
    "/job/{job_id}",
    summary="List all interview reports for a job",
)
async def list_job_reports(job_id: str, db: AsyncSession = Depends(get_db)):
    """Returns a summary list of all completed interviews for a job."""
    from sqlalchemy import select
    from app.db.database import InterviewSession, Candidate

    result = await db.execute(
        select(InterviewSession, Candidate)
        .join(Candidate, InterviewSession.candidate_id == Candidate.id)
        .where(Candidate.job_id == job_id)
    )
    rows = result.all()

    reports = []
    for session, candidate in rows:
        reports.append({
            "session_id": session.id,
            "candidate_name": candidate.name,
            "candidate_email": candidate.email,
            "score": session.score,
            "recommendation": session.recommendation,
            "status": session.status,
            "report_available": bool(session.report_path and os.path.exists(session.report_path or "")),
            "report_sent": session.report_sent,
            "interviewed_at": session.ended_at,
        })

    return {"job_id": job_id, "total": len(reports), "reports": reports}
