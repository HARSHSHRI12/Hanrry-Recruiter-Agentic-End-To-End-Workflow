"""
Schedule Router
GET  /api/schedule/confirm        – candidate opens scheduling page (serves HTML form)
POST /api/schedule/confirm        – candidate submits chosen datetime
POST /api/schedule/webhook/transcript – VideoSDK agent POSTs transcript after call ends
"""
import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    get_db, get_candidate_by_token, set_candidate_interview_time,
    create_interview_session, update_interview_session,
    InterviewStatus
)
from app.db import crud
from app.models import ScheduleInterviewResponse
from app.services.scheduler import schedule_call
from app.tasks.call_task import trigger_interview_call
from app.core.logger import get_logger
from pydantic import BaseModel

log = get_logger(__name__)

router = APIRouter(prefix="/api/schedule", tags=["Scheduling"])


#  Scheduling Page (HTML) 

_SCHEDULE_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Schedule Your Interview | Hanrry AI</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Inter',sans-serif;background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);
       min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
  .card{{background:rgba(255,255,255,0.05);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.1);
         border-radius:20px;padding:48px 40px;max-width:480px;width:100%;box-shadow:0 25px 50px rgba(0,0,0,0.4)}}
  .logo{{text-align:center;margin-bottom:32px}}
  .logo h1{{color:#e94560;font-size:28px;font-weight:700;letter-spacing:-0.5px}}
  .logo p{{color:#a0aec0;font-size:14px;margin-top:6px}}
  h2{{color:#fff;font-size:20px;font-weight:600;margin-bottom:8px}}
  .subtitle{{color:#a0aec0;font-size:14px;margin-bottom:28px;line-height:1.6}}
  label{{display:block;color:#e2e8f0;font-size:13px;font-weight:500;margin-bottom:8px}}
  input[type="datetime-local"]{{
    width:100%;padding:14px 16px;background:rgba(255,255,255,0.08);
    border:1px solid rgba(255,255,255,0.15);border-radius:10px;color:#fff;
    font-size:15px;outline:none;transition:.2s}}
  input[type="datetime-local"]:focus{{border-color:#e94560;background:rgba(233,69,96,0.08)}}
  input[type="datetime-local"]::-webkit-calendar-picker-indicator{{filter:invert(1);opacity:.6}}
  .btn{{width:100%;padding:15px;margin-top:24px;
        background:linear-gradient(135deg,#e94560,#c62a47);color:#fff;
        border:none;border-radius:10px;font-size:16px;font-weight:600;
        cursor:pointer;letter-spacing:.3px;transition:.2s}}
  .btn:hover{{transform:translateY(-1px);box-shadow:0 8px 20px rgba(233,69,96,0.4)}}
  .note{{color:#718096;font-size:12px;text-align:center;margin-top:18px;line-height:1.6}}
  .success{{color:#68d391;background:rgba(104,211,145,0.1);border:1px solid rgba(104,211,145,0.2);
            padding:16px;border-radius:10px;text-align:center;display:none}}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <h1>Hanrry AI</h1>
    <p>Intelligent Recruitment Platform</p>
  </div>
  <h2>Schedule Your Interview</h2>
  <p class="subtitle">
    Choose a date and time that works best for you.<br/>
    Our AI recruiter will call you at exactly that time.
  </p>
  <form id="schedForm" method="POST" action="/api/schedule/confirm">
    <input type="hidden" name="token" value="{token}"/>
    <div>
      <label for="dt">Select Date & Time</label>
      <input type="datetime-local" id="dt" name="interview_datetime" required
             min="{min_dt}" style="color-scheme:dark"/>
    </div>
    <button class="btn" type="submit">Confirm My Interview Slot →</button>
  </form>
  <div class="success" id="successMsg">
    ✅ Interview scheduled! You'll receive a call at the selected time.
  </div>
  <p class="note">
    Please ensure your phone is available at the scheduled time.<br/>
    The call will come from our AI recruiter Hanrry.
  </p>
</div>
</body>
</html>
"""


@router.get(
    "/confirm/{token}",
    response_class=HTMLResponse,
    summary="Candidate scheduling page (token in path)",
)
@router.get(
    "/confirm",
    response_class=HTMLResponse,
    summary="Candidate scheduling page (token in query)",
)
async def schedule_page(token: str, db: AsyncSession = Depends(get_db)):
    """Serve the scheduling HTML form to the candidate."""
    candidate = await get_candidate_by_token(db, token)
    if not candidate:
        raise HTTPException(status_code=404, detail="Invalid or expired scheduling link.")

    from datetime import timezone, timedelta
    min_dt = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    return _SCHEDULE_PAGE.format(token=token, min_dt=min_dt)


@router.post(
    "/confirm/{token}",
    response_model=ScheduleInterviewResponse,
    summary="Confirm interview datetime (token in path)",
)
@router.post(
    "/confirm",
    response_model=ScheduleInterviewResponse,
    summary="Confirm interview datetime (token in body)",
)
async def confirm_schedule(
    request: Request,
    token: str = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts form data OR JSON with token + interview_datetime.
    Creates interview session and schedules the call.
    """
    content_type = request.headers.get("content-type", "")
    print("CONTENT TYPE =", content_type)

    try:
        if "json" in content_type.lower():
            data = await request.json()
        else:
            data = await request.form()

        if not token:
            token = data.get("token")
        raw_dt = data.get("interview_datetime")
        interview_dt = datetime.fromisoformat(raw_dt) if raw_dt else None

    except Exception as e:
        raise HTTPException(
        status_code=400,
        detail=f"Unable to parse request: {str(e)}"
    )
    if not token or not interview_dt:
        raise HTTPException(status_code=400, detail="token and interview_datetime are required.")

    # ── Validate candidate ────────────────────────────────────────────────────
    candidate = await get_candidate_by_token(db, token)
    if not candidate:
        raise HTTPException(status_code=404, detail="Invalid scheduling token.")

    if interview_dt <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Interview time must be in the future.")

    # ── Save interview time ───────────────────────────────────────────────────
    await set_candidate_interview_time(db, candidate.id, interview_dt)

    # ── Create interview session ──────────────────────────────────────────────
    session_id = str(uuid.uuid4())

    # Load job info for denormalization into session
    job = await crud.get_job(db, candidate.job_id) if candidate.job_id else None

    await create_interview_session(
        db,
        id=session_id,
        candidate_id=candidate.id,
        job_id=candidate.job_id,
        job_title=job.title if job else None,
        company=job.company if job else None,
        jd_text=job.jd_text if job else None,
        scheduled_at=interview_dt,
    )

    # ── Schedule the call via APScheduler ────────────────────────────────────
    schedule_call(
        job_id_str=f"call_{session_id}",
        run_datetime=interview_dt,
        call_func=trigger_interview_call,
        kwargs={
            "candidate_id": candidate.id,
            "session_id": session_id,
            "job_id": candidate.job_id,
        },
    )

    log.info(
        f"Interview scheduled: candidate={candidate.id}, session={session_id}, "
        f"at={interview_dt}"
    )

    return ScheduleInterviewResponse(
        message="Interview scheduled successfully! You will receive a call at the chosen time.",
        candidate_id=candidate.id,
        interview_datetime=interview_dt,
    )


# ─────────────────────── Transcript Webhook ────────────────────────────────────

class TranscriptWebhook(BaseModel):
    session_id: str
    transcript: str
    call_duration_seconds: int = 0


@router.post(
    "/webhook/transcript",
    summary="VideoSDK agent posts call transcript after interview ends",
    status_code=status.HTTP_200_OK,
)
async def receive_transcript(
    body: TranscriptWebhook,
    db: AsyncSession = Depends(get_db),
):
    """
    Called by the VideoSDK calling agent once the call ends.
    1. Saves transcript to DB
    2. Immediately fires the post-call pipeline in the background
       (analysis → PDF report → email)
    """
    from app.tasks.call_task import run_post_call_pipeline

    session = await crud.get_interview_session(db, body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {body.session_id} not found.")

    await update_interview_session(
        db,
        body.session_id,
        transcript=body.transcript,
        status=InterviewStatus.COMPLETED,
    )

    log.info(
        f"Transcript received via webhook: session={body.session_id}, "
        f"length={len(body.transcript)} chars"
    )

    # 🚀 Fire post-call pipeline immediately (don't await — return 200 fast)
    asyncio.create_task(
        run_post_call_pipeline(
            session_id=body.session_id,
            transcript=body.transcript,
        )
    )
    log.info(f"🔬 Post-call pipeline triggered for session={body.session_id}")

    return {"message": "Transcript saved. Analysis pipeline started.", "session_id": body.session_id}
