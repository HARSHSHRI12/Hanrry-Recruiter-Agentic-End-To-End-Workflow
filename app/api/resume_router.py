"""
Resume Upload Router
POST /api/resumes/upload
 - Accepts batch PDF/DOCX resume uploads
 - Parses text, extracts contacts, saves to DB
 - Returns list of created candidate IDs
"""
import uuid
import os
from typing import List

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db, create_candidate, CandidateStatus
from app.models import ResumeUploadResponse
from app.services import parse_resume, save_resume_file, extract_contacts
from app.core.config import settings
from app.core.logger import get_logger
from app.core.exceptions import ResumeParseError

log = get_logger(__name__)

router = APIRouter(prefix="/api/resumes", tags=["Resumes"])


@router.post(
    "/upload",
    response_model=ResumeUploadResponse,
    summary="Upload batch resumes for a job",
    status_code=status.HTTP_201_CREATED,
)
async def upload_resumes(
    job_id: str = Form(..., description="Job ID to associate resumes with"),
    files: List[UploadFile] = File(..., description="PDF / DOCX / TXT resume files"),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload one or more resumes (PDF/DOCX/TXT).
    Parses text and extracts phone/email for each candidate.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    created_ids = []
    upload_dir = os.path.join(settings.UPLOAD_DIR, job_id)

    for file in files:
        # ── Size guard ────────────────────────────────────────────────────────
        content = await file.read()
        size_mb = len(content) / (1024 * 1024)
        if size_mb > settings.MAX_UPLOAD_SIZE_MB:
            log.warning(f"Skipping {file.filename}: too large ({size_mb:.1f} MB)")
            continue

        # ── Parse text ────────────────────────────────────────────────────────
        try:
            resume_text = parse_resume(content, file.filename)
        except ResumeParseError as e:
            log.warning(f"Skipping {file.filename}: {e}")
            continue

        if not resume_text.strip():
            log.warning(f"Skipping {file.filename}: empty text after parse")
            continue

        # ── Extract contacts ──────────────────────────────────────────────────
        phone, email = await extract_contacts(resume_text)

        # ── Save file to disk ─────────────────────────────────────────────────
        safe_name = f"{uuid.uuid4().hex}_{file.filename}"
        saved_path = await save_resume_file(content, safe_name, upload_dir)

        # ── Persist to DB ─────────────────────────────────────────────────────
        candidate_id = str(uuid.uuid4())
        schedule_token = str(uuid.uuid4())

        await create_candidate(
            db,
            id=candidate_id,
            job_id=job_id,
            name=None,                    # name extracted during filter step
            email=email,
            phone=phone,
            resume_path=saved_path,
            resume_text=resume_text,
            status=CandidateStatus.UPLOADED,
            schedule_token=schedule_token,
        )
        created_ids.append(candidate_id)
        log.info(f"Candidate created: {candidate_id} | email={email} | phone={phone}")

    if not created_ids:
        raise HTTPException(
            status_code=422,
            detail="No valid resumes could be processed. Check file formats and sizes.",
        )

    return ResumeUploadResponse(
        message=f"Successfully processed {len(created_ids)} resume(s).",
        job_id=job_id,
        total_uploaded=len(created_ids),
        candidates=created_ids,
    )
