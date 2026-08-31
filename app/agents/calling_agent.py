"""
Hanrry AI Calling Agent (VideoSDK)
Dynamically built from job description for each interview session.

Architecture:
  1. This process runs as a persistent VideoSDK WorkerJob (registered agent).
  2. When a call is needed, call_task.py calls POST /trigger-call here.
  3. This endpoint calls VideoSDK SIP API (POST /v2/sip/call) to dial the
     candidate's phone number via the configured SIP outbound gateway.
  4. VideoSDK routes the ringing call to this registered agent via routing rule.
  5. Agent joins the session, greets candidate, conducts interview.
"""
from __future__ import annotations
import os
import traceback
import logging
import asyncio
from typing import Optional
from google.genai import types

from dotenv import load_dotenv
from videosdk.agents import (
    Agent, AgentSession, Pipeline, JobContext,
    RoomOptions, WorkerJob, Options, ExecutorType, InterruptConfig
)
from videosdk.plugins.google import GeminiRealtime, GeminiLiveConfig
from google.genai.types import (
    RealtimeInputConfig,
    AutomaticActivityDetection,
    StartSensitivity,
    EndSensitivity,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hanrry.calling_agent")

# VideoSDK SIP outbound call endpoint 
VIDEOSDK_SIP_CALL_URL = "https://api.videosdk.live/v2/sip/call"


class HanrryInterviewAgent(Agent):
    """
    Dynamic AI recruiter agent that conducts a JD-specific screening interview.
    """

    def __init__(
        self,
        candidate_name: str = "Candidate",
        job_title: str = "Software Engineer",
        company: str = "our company",
        jd_summary: str = "",
        session_id: str = "",
        on_transcript_callback=None,
    ):
        self.candidate_name = candidate_name
        self.job_title = job_title
        self.company = company
        self.session_id = session_id
        self.on_transcript_callback = on_transcript_callback
        self._transcript_lines = []

        instructions = self._build_instructions(candidate_name, job_title, company, jd_summary)
        super().__init__(instructions=instructions)

    @staticmethod
    def _build_instructions(
        candidate_name: str,
        job_title: str,
        company: str,
        jd_summary: str,
    ) -> str:
        # Critical for realtime S2S pipeline 
        # DO NOT use session.say() in on_enter for a Gemini Live pipeline.
        # session.say() routes through a separate TTS path; Gemini Live never
        # receives that audio as part of its conversation context, so it goes
        # silent after the greeting and never continues the interview.
        # Instead, we embed the exact opening line in the system prompt and
        # instruct Gemini to speak it IMMEDIATELY when the session starts.
        opening_line = (
            f"Hello! Am I speaking with {candidate_name}? "
            f"Hi! I'm Hanrry, calling from the talent acquisition team at {company}. "
            f"I'm reaching out regarding your application for the {job_title} position. "
            f"Is this a good time to talk for about 10 to 15 minutes?"
        )
        return f"""You are Hanrry, a warm, professional, and experienced AI recruiter at {company}.
You are conducting a live telephonic screening call with {candidate_name} for the {job_title} role.

## !! CRITICAL — START SPEAKING IMMEDIATELY !!
The moment this session begins, you MUST speak first. Do NOT wait for the user.
Begin with EXACTLY this opening (word for word):
"{opening_line}"

After that, listen for the candidate's response and follow the interview flow below.

## YOUR PERSONALITY
- Sound like a real, warm, human recruiter — never robotic.
- Use natural filler words: "Great!", "I see", "That makes sense", "Absolutely".
- Keep YOUR turns short: 1-2 sentences max. One question at a time.
- Mirror the candidate's energy. Be empathetic and encouraging.
- If the candidate says they are busy, apologize warmly and offer to reschedule.

## JOB DETAILS
{jd_summary or f'This is a {job_title} role at {company}.'}

## INTERVIEW FLOW (natural, not scripted — follow in order)

STEP 1 — CONFIRM IDENTITY & TIME CHECK (your opening line does this)
  After they confirm identity: "Wonderful, great to connect with you! I'll take just 10-15 minutes of your time today."
  If they say they are busy: "No worries at all! When would be a better time to connect?"

STEP 2 — CURRENT ROLE
  "Could you tell me a little about your current role and what you're working on these days?"

STEP 3 — RELEVANT SKILLS (tailor to the JD)
  Reference a specific skill from the job context and ask for hands-on experience.
  "The {job_title} role focuses on [key skill from JD]. Can you walk me through your experience with that?"

STEP 4 — SITUATIONAL
  "Can you share a challenging problem you solved recently — and walk me through how you approached it?"

STEP 5 — MOTIVATION
  "What excites you most about this opportunity at {company}?"

STEP 6 — LOGISTICS
  "Just a couple of quick logistics — what's your current notice period, and are you comfortable with the work arrangement for this role?"

STEP 7 — WARM CLOSE
  "This has been really helpful, {candidate_name}. Our hiring team will review your profile and we'll be in touch within 2-3 business days. Thank you so much for your time — have a great day!"

## RULES
- Always ask ONE question per turn. Never stack questions.
- Wait for the candidate to finish answering before asking the next question.
- If they go off-topic: "That's interesting! Let me circle back to our discussion..."
- NEVER make hiring promises or decisions on the call.
- NEVER hallucinate role or company details not in the JD context.
"""

    async def on_enter(self) -> None:
        # In a full-S2S pipeline, we use session.reply() instead of session.say().
        # session.reply() sends a text prompt directly into the Gemini Live context,
        # forcing it to speak immediately and ensuring it remembers what it said.
        greeting_prompt = (
            f"Please introduce yourself now exactly like this: "
            f"'Hello! Am I speaking with {self.candidate_name}? "
            f"Hi! I'm Hanrry, calling from the talent acquisition team at {self.company}. "
            f"I'm reaching out regarding your application for the {self.job_title} position. "
            f"Is this a good time to talk for about 10 to 15 minutes?'"
        )
        self._transcript_lines.append(f"[System: Triggered greeting]")
        await self.session.reply(greeting_prompt, interruptible=False)

    async def on_exit(self) -> None:
        closing_prompt = (
            f"Please conclude the interview exactly like this: "
            f"'Thank you so much for your time today, {self.candidate_name}. "
            f"It was really great speaking with you. Our team will review your profile and "
            f"we'll get back to you within 2 to 3 business days with the next steps. "
            f"Have a wonderful day — take care, bye!'"
        )
        self._transcript_lines.append(f"[System: Triggered closing]")
        await self.session.reply(closing_prompt, interruptible=False)

        # Fire callback with full transcript
        if self.on_transcript_callback and self._transcript_lines:
            transcript = "\n".join(self._transcript_lines)
            await self.on_transcript_callback(self.session_id, transcript)

        # Post transcript to main server webhook so report generation triggers
        if self.session_id and self._transcript_lines:
            try:
                import httpx as _httpx
                _transcript_text = "\n".join(self._transcript_lines)
                _main_host = os.getenv("MAIN_SERVER_HOST", "localhost")
                _main_port = os.getenv("MAIN_SERVER_PORT", "8000")
                async with _httpx.AsyncClient(timeout=10) as _client:
                    await _client.post(
                        f"http://{_main_host}:{_main_port}/api/schedule/webhook/transcript",
                        json={"session_id": self.session_id, "transcript": _transcript_text, "call_duration_seconds": 0},
                    )
                log.info(f"✅ Transcript webhook sent for session={self.session_id}")
            except Exception as _e:
                log.warning(f"⚠️ Transcript webhook failed (non-fatal): {_e}")

    def record_utterance(self, speaker: str, text: str):
        """Called externally to log transcript lines."""
        self._transcript_lines.append(f"{speaker}: {text}")


def build_gemini_pipeline() -> Pipeline:
    """
    Build Gemini Realtime pipeline.
    Uses gemini-3.1-flash-live-preview — the plugin's own default model,
    fully supported on v1alpha (which is now hardcoded in the plugin source).
    """
    # Use GeminiLiveConfig defaults for realtime_input_config (fast VAD):
    # - end_of_speech_sensitivity=HIGH, silence_duration_ms=400 — fast turn detection
    # - NOT passing realtime_input_config=None which would disable fast VAD
    #   and fall back to Gemini server defaults (1.5-2s silence wait = voice breaks)
    model = GeminiRealtime(
        model="gemini-3.1-flash-live-preview",
        api_key=os.getenv("GOOGLE_API_KEY"),
        config=GeminiLiveConfig(
            voice="Aoede",
            response_modalities=["AUDIO"],
            realtime_input_config=RealtimeInputConfig(
                automatic_activity_detection=AutomaticActivityDetection(
                    start_of_speech_sensitivity=StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=300,
                    silence_duration_ms=800,
                )
            ),
        ),
    )
    return Pipeline(
        llm=model,
        interrupt_config=InterruptConfig(
    mode="STT_ONLY",              # only actual transcribed words on interrupt, raw audio-VAD not on  (echo-resistant)
    interrupt_min_duration=1.5,   
    interrupt_min_words=2,
    interrupt_min_confidence=0.6,  # 0.0 increase — weak/noisy echo signals reject karega
),
    )


def build_groq_pipeline() -> Pipeline:
    log.warning("Falling back to Groq Pipeline (Requires DEEPGRAM, GROQ, and CARTESIA API keys)")
    from videosdk.plugins.llm.groq import GroqLLM
    from videosdk.plugins.stt.deepgram import DeepgramSTT
    from videosdk.plugins.tts.cartesia import CartesiaTTS
    
    stt = DeepgramSTT(api_key=os.getenv("DEEPGRAM_API_KEY", "MISSING_KEY"))
    llm = GroqLLM(model="llama-3.1-8b-instant", api_key=os.getenv("GROQ_API_KEY", "MISSING_KEY"))
    tts = CartesiaTTS(api_key=os.getenv("CARTESIA_API_KEY", "MISSING_KEY"), voice_id="a0e99841-438c-4a64-b679-ae501e7d6091")
    
    return Pipeline(stt=stt, llm=llm, tts=tts)


async def run_interview_session(
    context: JobContext,    
    candidate_name: str,
    job_title: str,
    company: str,
    jd_summary: str,
    session_id: str,
    on_transcript_callback=None,
):
    """Start an interview session for a specific candidate."""
    agent = HanrryInterviewAgent(
        candidate_name=candidate_name,
        job_title=job_title,
        company=company,
        jd_summary=jd_summary,
        session_id=session_id,
        on_transcript_callback=on_transcript_callback,
    )

    log.info("Starting session with Gemini 3.1 Flash Live Pipeline...")
    pipeline = build_gemini_pipeline()

    @pipeline.on("user_turn_start")
    async def on_user_turn_start(transcript: str):
        if transcript.strip():
            log.info(f"[Transcript Hook] User said: {transcript}")
            agent.record_utterance("Candidate", transcript)

    @pipeline.on("llm")
    async def on_llm(data: dict):
        text = data.get("text", "")
        if text.strip():
            log.info(f"[Transcript Hook] Agent said: {text}")
            agent.record_utterance("Hanrry", text)

    session = AgentSession(agent=agent, pipeline=pipeline)
    await session.start(wait_for_participant=True, run_until_shutdown=True)


# Standalone Agent Runner (for VideoSDK WorkerJob)
if __name__ == "__main__":
    """
    Run as a persistent VideoSDK agent worker.
    - Registers this process with VideoSDK as "HanrryInterviewAgent"
    - VideoSDK routes the connected call here.
    """
    # ── Context store: session_id -> call params (for agent entrypoint) ────────
    _pending_sessions: dict = {}

    # ── Agent entrypoint: called by VideoSDK when call connects ───────────────
    async def _session_entry(context: JobContext):
        """
        VideoSDK calls this when an incoming/routed call is dispatched to
        this agent. We look up the session context and start the interview.
        """
        # Try to get session_id from room metadata
        session_id = None
        try:
            meta = getattr(context, "metadata", {}) or {}
            session_id = meta.get("session_id")
        except Exception:
            pass

        if not session_id and _pending_sessions:
            # Fallback: use the most recently added session
            session_id = list(_pending_sessions.keys())[-1]
            log.warning(f"No session_id in context metadata, using fallback: {session_id}")

        params = _pending_sessions.pop(session_id, {})
        
        # If params not found in memory cache, fetch from DB
        if not params and session_id:
            try:
                import sys
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)
                from app.db.database import AsyncSessionLocal
                from app.db import crud

                async with AsyncSessionLocal() as db:
                    db_session = await crud.get_interview_session(db, session_id)
                    if db_session:
                        candidate = await crud.get_candidate(db, db_session.candidate_id)
                        if candidate:
                            params["candidate_name"] = candidate.name
                            
                            # Resolve job data
                            resolved_job_title = getattr(db_session, "job_title", None)
                            resolved_company = getattr(db_session, "company", None)
                            resolved_jd_text = getattr(db_session, "jd_text", None)
                            resolved_job_id = getattr(db_session, "job_id", None) or getattr(candidate, "job_id", None)
                            
                            if resolved_job_id and not (resolved_job_title and resolved_jd_text):
                                job = await crud.get_job(db, resolved_job_id)
                                if job:
                                    resolved_job_title = resolved_job_title or job.title
                                    resolved_company = resolved_company or job.company
                                    resolved_jd_text = resolved_jd_text or job.jd_text

                            params["job_title"] = resolved_job_title or "Software Engineer"
                            params["company"] = resolved_company or "our company"
                            params["jd_summary"] = resolved_jd_text or ""
            except Exception as e:
                log.error(f"Failed to fetch session params from DB: {e}")

        log.info(f"Agent session starting for session_id={session_id}, params={list(params.keys())}")

        await run_interview_session(
            context=context,
            candidate_name=params.get("candidate_name", "Candidate"),
            job_title=params.get("job_title", "Software Engineer"),
            company=params.get("company", "our company"),
            jd_summary=params.get("jd_summary", ""),
            session_id=session_id or "",
        )

    def make_context() -> JobContext:
        return JobContext(room_options=RoomOptions())

    # ── Run Servers ───────────────────────────────────────────────────────────
    # Run agent worker in MAIN thread
    log.info("Starting Hanrry agent worker in main thread...")
    try:
        # Properly initialize uvloop if available (videosdk uses it)
        try:
            import uvloop
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        except ImportError:
            pass
            
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        options = Options(
            agent_id="MyTelephonyAgent",  # Must EXACTLY match Routing Rule Agent ID
            register=True,
            max_processes=1,  # Set to 1 to avoid Out Of Memory (512MB limit on Render)
            target_idle_processes=0,  # Do not spawn idle background processes (saves RAM)
            executor_type=ExecutorType.THREAD,  # Use threads instead of full process forks
            host="localhost",
            port=8081,
        )
        job = WorkerJob(entrypoint=_session_entry, jobctx=make_context, options=options)
        job.start()
    except Exception:
        traceback.print_exc()

