# Hanrry AI Screening Recruiter

End-to-end production-grade AI recruitment pipeline:

**Resume Upload → JD Filter → Schedule Email → AI Call → Analysis → Report**

## Quick Start

### 1. Clone & Setup
```bash
cd hanrry-screening-recruiter-agent
python -m venv env
env\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Configure .env
```bash
copy .env.example .env
# Fill in: GOOGLE_API_KEY, VIDEOSDK_AUTH_TOKEN, SMTP_USER, SMTP_PASSWORD, RECRUITER_EMAIL
```

### 3. Run API Server
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Run Calling Agent (separate terminal)
```bash
python -m app.agents.calling_agent
```

Open **http://localhost:8000/docs** for the interactive API docs.

---

## End-to-End Flow

```
1. POST /api/jd/create-job          → Register JD, get job_id
2. POST /api/resumes/upload         → Upload PDFs (multipart), get candidate IDs
3. POST /api/jd/filter              → Score resumes vs JD → emails sent to candidates
4. Candidate opens link             → GET /api/schedule/confirm?token=<token>
5. Candidate picks slot             → POST /api/schedule/confirm (form submit)
6. APScheduler fires at slot time   → AI calls candidate via VideoSDK
7. Call ends → transcript posted    → POST /api/schedule/webhook/transcript
8. LangGraph analysis runs          → scores + strengths/weaknesses
9. PDF report generated             → emailed to RECRUITER_EMAIL
10. GET /api/reports/{session_id}   → view JSON analysis
11. GET /api/reports/{session_id}/pdf → download PDF report
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/jd/create-job` | Register a new job description |
| POST | `/api/resumes/upload` | Batch upload resumes (PDF/DOCX) |
| POST | `/api/jd/filter` | Filter candidates against JD |
| GET | `/api/schedule/confirm?token=X` | Candidate scheduling page |
| POST | `/api/schedule/confirm` | Save interview slot |
| POST | `/api/schedule/webhook/transcript` | Agent posts transcript |
| GET | `/api/reports/{id}` | Get analysis JSON |
| GET | `/api/reports/{id}/pdf` | Download PDF report |
| POST | `/api/reports/{id}/resend` | Resend report to recruiter |
| GET | `/api/reports/job/{job_id}` | All reports for a job |
| GET | `/health` | Health check |

---

## Project Structure

```
hanrry-screening-recruiter-agent/
├── app/
│   ├── api/            # FastAPI routers
│   ├── agents/         # LangGraph + VideoSDK agents
│   ├── services/       # Business logic
│   ├── db/             # SQLAlchemy ORM + CRUD
│   ├── models/         # Pydantic schemas
│   ├── tasks/          # Background tasks
│   └── core/           # Config, logging, exceptions
├── main.py             # FastAPI entry point
├── requirements.txt
└── .env
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | ✅ | Gemini API key |
| `VIDEOSDK_AUTH_TOKEN` | ✅ | VideoSDK token |
| `SMTP_USER` | ✅ | Gmail address |
| `SMTP_PASSWORD` | ✅ | Gmail App Password |
| `RECRUITER_EMAIL` | ✅ | Where reports are sent |
| `DATABASE_URL` | ✅ | SQLite or PostgreSQL |
| `SCHEDULER_TIMEZONE` | ✅ | e.g. `Asia/Kolkata` |

> **Gmail App Password**: Google Account → Security → 2FA enabled → App Passwords → Generate
