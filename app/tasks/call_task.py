"""
Background Task: Trigger AI Interview Call
Runs at the scheduled datetime, initiates VideoSDK call,
then runs LangGraph analysis and sends recruiter report.
"""
import asyncio
import json
import os
from datetime import datetime

from app.core.logger import get_logger
from app.core.config import settings
from app.db.database import AsyncSessionLocal, InterviewStatus, CandidateStatus
from app.db import crud
from app.agents.analysis_agent import run_analysis
from app.services.report_generator import generate_report
from app.services.email_service import send_report_email

log = get_logger(__name__)

# Absolute path to reports/ dir so it works regardless of CWD
_REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reports")


async def run_post_call_pipeline(
    session_id: str,
    transcript: str,
) -> None:
    """
    Run the full post-call pipeline for a completed interview session:
      1. Load candidate + job data from DB
      2. Run LangGraph analysis
      3. Save analysis to DB
      4. Generate PDF report
      5. Email report to recruiter

    Called from:
      - trigger_interview_call() after polling for transcript
      - receive_transcript() webhook directly (preferred path)
    """
    import traceback
    log.info(f"{'='*60}")
    log.info(f"🔬 [POST-CALL PIPELINE] Starting for session={session_id}")
    log.info(f"   Transcript length: {len(transcript)} chars")
    log.info(f"{'='*60}")

    try:
        async with AsyncSessionLocal() as db:
            session = await crud.get_interview_session(db, session_id)
            if not session:
                log.error(f"❌ Session {session_id} not found in DB — cannot run pipeline")
                return

            candidate = await crud.get_candidate(db, session.candidate_id)
            if not candidate:
                log.error(f"❌ Candidate not found for session {session_id}")
                return

            # ── Resolve job metadata ──────────────────────────────────────
            resolved_job_title = getattr(session, "job_title", None)
            resolved_company   = getattr(session, "company", None)
            resolved_jd_text   = getattr(session, "jd_text", None)

            resolved_job_id = getattr(session, "job_id", None) or getattr(candidate, "job_id", None)
            if resolved_job_id and not (resolved_job_title and resolved_jd_text):
                job = await crud.get_job(db, resolved_job_id)
                if job:
                    resolved_job_title = resolved_job_title or job.title
                    resolved_company   = resolved_company   or job.company
                    resolved_jd_text   = resolved_jd_text   or job.jd_text

            resolved_job_title = resolved_job_title or "Software Engineer"
            resolved_company   = resolved_company   or "our company"
            resolved_jd_text   = resolved_jd_text   or ""

            log.info(f"📂 Candidate: {candidate.name} | Job: {resolved_job_title} @ {resolved_company}")

            # ── Step 1: LangGraph Analysis ────────────────────────────────
            log.info(f"🧠 Running LangGraph analysis...")
            analysis_result = await run_analysis(
                session_id=session_id,
                candidate_name=candidate.name or "Candidate",
                job_title=resolved_job_title,
                jd_text=resolved_jd_text,
                transcript=transcript,
            )
            log.info(f"✅ Analysis complete — Score: {analysis_result.get('total_score', 'N/A')}")

            # ── Step 2: Save analysis to DB ───────────────────────────────
            log.info(f"💾 Saving analysis to DB...")
            await crud.save_transcript_and_analysis(
                db,
                session_id=session_id,
                transcript=transcript,
                analysis={
                    "question_breakdown": analysis_result["scored_pairs"],
                    "strengths": analysis_result["strengths"],
                    "weaknesses": analysis_result["weaknesses"],
                },
                score=analysis_result["total_score"],
                recommendation=analysis_result["recommendation"],
            )
            log.info(f"✅ Analysis saved")

            # ── Step 3: Generate PDF Report ───────────────────────────────
            log.info(f"📄 Generating PDF report...")
            report_path = generate_report(
                output_dir=_REPORTS_DIR,
                session_id=session_id,
                candidate_name=candidate.name or "Candidate",
                candidate_email=candidate.email or "N/A",
                candidate_phone=candidate.phone or "N/A",
                job_title=resolved_job_title,
                company=resolved_company,
                interview_date=datetime.utcnow().strftime("%B %d, %Y %H:%M UTC"),
                total_score=analysis_result["total_score"],
                recommendation=analysis_result["recommendation"],
                strengths=analysis_result["strengths"],
                weaknesses=analysis_result["weaknesses"],
                summary=analysis_result["summary"],
                transcript=transcript,
                analysis_json=json.dumps({"question_breakdown": analysis_result["scored_pairs"]}),
            )
            await crud.update_interview_session(db, session_id, report_path=report_path)
            log.info(f"✅ PDF report generated: {report_path}")

            # ── Step 4: Email Recruiter ───────────────────────────────────
            log.info(f"📧 Sending report email to recruiter...")
            send_report_email(
                candidate_name=candidate.name or "Candidate",
                candidate_email=candidate.email or "N/A",
                candidate_phone=candidate.phone or "N/A",
                job_title=resolved_job_title,
                interview_date=datetime.utcnow().strftime("%B %d, %Y %H:%M UTC"),
                total_score=analysis_result["total_score"],
                recommendation=analysis_result["recommendation"],
                summary=analysis_result["summary"],
                pdf_path=report_path,
            )
            await crud.update_interview_session(db, session_id, report_sent=True)
            log.info(f"✅ Email sent")

            log.info(f"")
            log.info(f"{'='*60}")
            log.info(f"🎉 [POST-CALL PIPELINE COMPLETE] session={session_id}")
            log.info(f"   Candidate: {candidate.name}")
            log.info(f"   Score: {analysis_result['total_score']} | Rec: {analysis_result['recommendation']}")
            log.info(f"   Report: {report_path}")
            log.info(f"{'='*60}")

    except Exception as e:
        log.error(f"")
        log.error(f"{'='*60}")
        log.error(f"❌ [POST-CALL PIPELINE FAILED] session={session_id}")
        log.error(f"   {type(e).__name__}: {e}")
        log.error(traceback.format_exc())
        log.error(f"{'='*60}")
        try:
            async with AsyncSessionLocal() as db:
                await crud.update_interview_session(db, session_id, status=InterviewStatus.FAILED)
        except Exception:
            pass


async def trigger_interview_call(
    candidate_id: str,
    session_id: str,
    job_id: str,
):
    """
    Main background task called by APScheduler at interview time.
    Steps:
      1. Load candidate + job data
      2. Mark session as IN_CALL
      3. Initiate VideoSDK call (via REST API trigger)
      4. Wait for transcript (polled from DB or webhook)
      5. Run LangGraph analysis
      6. Generate PDF report
      7. Email report to recruiter
    """
    import traceback
    log.info(f"")
    log.info(f"{'='*80}")
    log.info(f"🎤 [INTERVIEW CALL TRIGGERED] Session: {session_id}")
    log.info(f"   Candidate: {candidate_id}")
    log.info(f"   Job: {job_id}")
    log.info(f"{'='*80}")
    
    try:
        async with AsyncSessionLocal() as db:
            # ── Step 1: Load data ─────────────────────────────────────────────
            log.info(f"📂 Loading data from database...")
            candidate = await crud.get_candidate(db, candidate_id)
            session   = await crud.get_interview_session(db, session_id)

            if not candidate or not session:
                log.error(f"❌ FATAL: Missing data")
                log.error(f"   Candidate found: {bool(candidate)}")
                log.error(f"   Session found: {bool(session)}")
                return

            # ── Resolve job data: session denormalized > DB > candidate.job_id ──
            # Try denormalized fields in session first (set at scheduling time)
            resolved_job_title = getattr(session, "job_title", None)
            resolved_company   = getattr(session, "company", None)
            resolved_jd_text   = getattr(session, "jd_text", None)

            # If missing, fetch from jobs table
            resolved_job_id = getattr(session, "job_id", None) or job_id or getattr(candidate, "job_id", None)
            if resolved_job_id and not (resolved_job_title and resolved_jd_text):
                job = await crud.get_job(db, resolved_job_id)
                if job:
                    resolved_job_title = resolved_job_title or job.title
                    resolved_company   = resolved_company   or job.company
                    resolved_jd_text   = resolved_jd_text   or job.jd_text

            # Final fallbacks
            resolved_job_title = resolved_job_title or "Software Engineer"
            resolved_company   = resolved_company   or "our company"
            resolved_jd_text   = resolved_jd_text   or ""

            log.info(f"✅ Data loaded successfully")
            log.info(f"   Candidate: {candidate.name} ({candidate.email}) | Phone: {candidate.phone}")
            log.info(f"   Job: {resolved_job_title} @ {resolved_company}")

            # ── Step 2: Mark IN_CALL 
            log.info(f"📍 Marking session as IN_CALL...")
            await crud.update_interview_session(db, session_id,
                status=InterviewStatus.IN_CALL,
                started_at=datetime.utcnow()
            )
            await crud.update_candidate_status(db, candidate_id, CandidateStatus.INTERVIEWED)
            log.info(f"✅ Session marked as IN_CALL")

            # Step 3: Trigger VideoSDK Call via REST API
            log.info(f"📞 Initiating VideoSDK call to {candidate.phone}...")
            await _initiate_videosdk_call(
                phone=candidate.phone,
                candidate_name=candidate.name or "Candidate",
                job_title=resolved_job_title,
                company=resolved_company,
                caller_id=settings.TWILIO_PHONE_NUMBER,
                jd_text=resolved_jd_text,
                session_id=session_id,
            )
            log.info(f"✅ VideoSDK call initiated")

            # ── Step 4: Poll for transcript ───────────────────────────────────
            # NOTE: The transcript webhook (receive_transcript) will usually
            # trigger run_post_call_pipeline FIRST (faster path).
            # This polling is a fallback safety net.
            log.info(f"⏳ Waiting for transcript (timeout: 1200s)...")
            transcript = await _poll_for_transcript(db, session_id, timeout_seconds=1200)

            if not transcript:
                log.warning(f"⚠️  No transcript received, using placeholder")
                transcript = "[Transcript not captured - please check VideoSDK logs]"
            else:
                log.info(f"✅ Transcript received ({len(transcript)} chars)")

            # ── Step 5-8: Analysis → PDF → Email ─────────────────────────────
            # Delegate to shared pipeline function (same as webhook path)
            log.info(f"🔬 Handing off to post-call pipeline...")

    except Exception as e:
        import traceback
        log.error(f"")
        log.error(f"{'='*80}")
        log.error(f"❌ [INTERVIEW FAILED] Session: {session_id}")
        log.error(f"   Exception: {type(e).__name__}: {str(e)}")
        log.error(f"   Traceback:\n{traceback.format_exc()}")
        log.error(f"{'='*80}")
        log.error(f"")
        try:
            async with AsyncSessionLocal() as db:
                await crud.update_interview_session(
                    db, session_id, status=InterviewStatus.FAILED
                )
        except Exception:
            pass

    # Run pipeline OUTSIDE the db context to avoid nested session issues
    await run_post_call_pipeline(session_id=session_id, transcript=transcript)


async def _initiate_videosdk_call(
    phone: str,
    candidate_name: str,
    job_title: str,
    company: str,
    jd_text: str,
    caller_id: str,
    session_id: str,
):
    """
    Trigger an outbound SIP call via VideoSDK API directly.
    This avoids the need to talk to the calling_agent's local HTTP server,
    which may not always be reachable.
    VideoSDK will route the connected call to our registered WorkerJob agent.
    """
    import httpx
    import sys

    VIDEOSDK_SIP_CALL_URL = "https://api.videosdk.live/v2/sip/call"
    routing_rule_id = settings.VIDEOSDK_ROUTING_RULE_ID

    if not routing_rule_id:
        log.error("❌ VIDEOSDK_ROUTING_RULE_ID not set — cannot make outbound call!")
        return

    # Get auth token
    auth_token = settings.VIDEOSDK_AUTH_TOKEN
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from app.core.videosdk_token import get_videosdk_token
        auth_token = get_videosdk_token()
    except Exception as e:
        log.warning(f"Token generator failed ({e}), using env token")

    if not auth_token:
        log.error("❌ No VideoSDK auth token available")
        return

    payload = {
        "sipCallFrom":   caller_id or "",
        "sipCallTo":     phone,
        "routingRuleId": routing_rule_id,
        "agentMetadata": {"session_id": session_id},
    }

    log.info(f"📡 Calling VideoSDK SIP API directly...")
    log.info(f"   sipCallFrom:   {caller_id}")
    log.info(f"   sipCallTo:     {phone}")
    log.info(f"   routingRuleId: {routing_rule_id}")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                VIDEOSDK_SIP_CALL_URL,
                json=payload,
                headers={
                    "Authorization": auth_token,
                    "Content-Type":  "application/json",
                },
            )
            log.info(f"   SIP API response: {resp.status_code}")
            if resp.status_code != 200:
                log.error(f"   SIP API error: {resp.text}")
            resp.raise_for_status()
            result = resp.json()
            log.info(f"✅ VideoSDK SIP call initiated: {result}")
    except Exception as e:
        log.error(f"❌ Failed to trigger VideoSDK call: {e}")
        # Don't raise – transcript polling will handle timeout gracefully


async def _poll_for_transcript(db, session_id: str, timeout_seconds: int = 1200) -> str:
    """
    Poll the DB every 30 seconds for a transcript from the agent's callback.
    Returns transcript string or empty string on timeout.
    """
    import asyncio
    elapsed = 0
    interval = 30

    while elapsed < timeout_seconds:
        session = await crud.get_interview_session(db, session_id)
        if session and session.transcript:
            log.info(f"Transcript received after {elapsed}s for session={session_id}")
            return session.transcript

        await asyncio.sleep(interval)
        elapsed += interval

    log.warning(f"Transcript poll timed out after {timeout_seconds}s")
    return ""
