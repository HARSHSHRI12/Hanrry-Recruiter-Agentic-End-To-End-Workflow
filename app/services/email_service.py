"""
Email Service
Handles:
 1. Candidate scheduling invitation email
 2. Recruiter post-interview report email (with PDF attachment)
"""
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime

from app.core.config import settings
from app.core.logger import get_logger
from app.core.exceptions import EmailSendError

log = get_logger(__name__)


def _build_smtp_connection():
    """Create and return an authenticated SMTP connection.
    Uses SSL on port 465 (works on cloud platforms like Render that block port 587).
    """
    try:
        import ssl
        context = ssl.create_default_context()
        smtp = smtplib.SMTP_SSL(settings.SMTP_HOST, 465, context=context)
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        return smtp
    except Exception as e:
        raise EmailSendError(f"SMTP connection failed: {e}")


def _send(msg: MIMEMultipart, to_email: str):
    """Send a pre-built MIME message."""
    smtp = _build_smtp_connection()
    try:
        smtp.sendmail(settings.SMTP_USER, to_email, msg.as_string())
        log.info(f"Email sent → {to_email}")
    finally:
        smtp.quit()


# ─────────────────────── Candidate Scheduling Email ───────────────────────────

SCHEDULE_SUBJECT = "📅 AI Interview Invitation – {company} | {job_title}"

SCHEDULE_HTML = """
<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background:#f4f7fb; margin:0; padding:0; }}
  .container {{ max-width:600px; margin:40px auto; background:#ffffff; border-radius:12px;
               box-shadow:0 4px 20px rgba(0,0,0,.08); overflow:hidden; }}
  .header {{ background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);
             padding:40px 32px; text-align:center; }}
  .header h1 {{ color:#e94560; margin:0; font-size:28px; letter-spacing:1px; }}
  .header p {{ color:#a0aec0; margin:8px 0 0; }}
  .body {{ padding:36px 32px; }}
  .body h2 {{ color:#1a1a2e; font-size:20px; margin-top:0; }}
  .body p {{ color:#4a5568; line-height:1.7; }}
  .btn {{ display:inline-block; margin:24px 0; padding:14px 36px;
          background:linear-gradient(135deg,#e94560,#c62a47); color:#fff;
          text-decoration:none; border-radius:8px; font-weight:600;
          font-size:16px; letter-spacing:.5px; }}
  .info-box {{ background:#f7fafc; border-left:4px solid #e94560; padding:16px 20px;
               border-radius:0 8px 8px 0; margin:20px 0; }}
  .footer {{ background:#f4f7fb; padding:20px 32px; text-align:center;
             color:#a0aec0; font-size:13px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Hanrry AI Recruiter</h1>
    <p>Automated Candidate Screening Platform</p>
  </div>
  <div class="body">
    <h2>Hello {candidate_name},</h2>
    <p>Congratulations! After reviewing your profile, we'd like to invite you for an
    <strong>AI-powered telephonic screening interview</strong> for the role of
    <strong>{job_title}</strong> at <strong>{company}</strong>.</p>

    <div class="info-box">
      <strong>How it works:</strong><br/>
      Our AI recruiter <em>Hanrry</em> will call you at your registered phone number
      at the time you select. The call will be a short 10–15 minute conversational
      interview based on your experience and the role requirements.
    </div>

    <p>Please click the button below to <strong>choose your preferred date and time</strong>
    for the interview:</p>

    <center><a class="btn" href="{schedule_link}">📅 Pick Your Interview Slot</a></center>

    <p style="color:#718096; font-size:14px;">
      If the button doesn't work, copy this link:<br/>
      <a href="{schedule_link}" style="color:#e94560;">{schedule_link}</a>
    </p>

    <p>If you have any questions, feel free to reply to this email.</p>
    <p>Best regards,<br/><strong>Hanrry – AI Recruitment Team</strong></p>
  </div>
  <div class="footer">
    This is an automated message from Hanrry AI Recruiter. Please do not reply directly.
  </div>
</div>
</body>
</html>
"""


def send_schedule_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company: str,
    schedule_link: str,
):
    """Send interview scheduling invitation to a candidate."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = SCHEDULE_SUBJECT.format(company=company, job_title=job_title)
    msg["From"] = f"Hanrry AI Recruiter <{settings.SMTP_USER}>"
    msg["To"] = to_email

    html = SCHEDULE_HTML.format(
        candidate_name=candidate_name or "Candidate",
        job_title=job_title,
        company=company,
        schedule_link=schedule_link,
    )
    msg.attach(MIMEText(html, "html"))

    try:
        _send(msg, to_email)
    except EmailSendError:
        raise
    except Exception as e:
        raise EmailSendError(f"Failed to send schedule email: {e}")


# ─────────────────────── Recruiter Report Email ────────────────────────────────

REPORT_SUBJECT = "📊 Interview Report – {candidate_name} | {job_title}"

REPORT_HTML = """
<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background:#f4f7fb; margin:0; padding:0; }}
  .container {{ max-width:600px; margin:40px auto; background:#fff; border-radius:12px;
               box-shadow:0 4px 20px rgba(0,0,0,.08); overflow:hidden; }}
  .header {{ background:linear-gradient(135deg,#1a1a2e,#0f3460); padding:36px; text-align:center; }}
  .header h1 {{ color:#e94560; margin:0; font-size:26px; }}
  .header p {{ color:#a0aec0; margin:6px 0 0; }}
  .body {{ padding:32px; }}
  .score-badge {{ display:inline-block; padding:10px 24px; border-radius:50px;
                 font-size:22px; font-weight:700; margin:12px 0; }}
  .HIRE   {{ background:#c6f6d5; color:#276749; }}
  .MAYBE  {{ background:#fefcbf; color:#744210; }}
  .REJECT {{ background:#fed7d7; color:#742a2a; }}
  .section {{ margin:20px 0; }}
  .section h3 {{ color:#2d3748; border-bottom:2px solid #e94560; padding-bottom:6px; }}
  .stat {{ display:flex; justify-content:space-between; padding:8px 0;
           border-bottom:1px solid #f0f0f0; color:#4a5568; }}
  .footer {{ background:#f4f7fb; padding:16px 32px; text-align:center;
             color:#a0aec0; font-size:13px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Interview Report</h1>
    <p>Hanrry AI Screening Platform</p>
  </div>
  <div class="body">
    <p>Dear Recruiter,</p>
    <p>The AI screening interview for <strong>{candidate_name}</strong> applying for
    <strong>{job_title}</strong> has been completed. Here is the summary:</p>

    <div class="section">
      <h3>📋 Candidate Overview</h3>
      <div class="stat"><span>Name</span><strong>{candidate_name}</strong></div>
      <div class="stat"><span>Email</span><strong>{candidate_email}</strong></div>
      <div class="stat"><span>Phone</span><strong>{candidate_phone}</strong></div>
      <div class="stat"><span>Role Applied</span><strong>{job_title}</strong></div>
      <div class="stat"><span>Interview Date</span><strong>{interview_date}</strong></div>
    </div>

    <div class="section">
      <h3>🎯 Score &amp; Recommendation</h3>
      <div class="stat"><span>Total Score</span><strong>{total_score}/10</strong></div>
      <p>Recommendation: <span class="score-badge {recommendation}">{recommendation}</span></p>
    </div>

    <div class="section">
      <h3>💡 Summary</h3>
      <p>{summary}</p>
    </div>

    <p>The full detailed PDF report is attached to this email.</p>
    <p>Best,<br/><strong>Hanrry AI System</strong></p>
  </div>
  <div class="footer">Auto-generated by Hanrry AI Recruiter</div>
</div>
</body>
</html>
"""


def send_report_email(
    candidate_name: str,
    candidate_email: str,
    candidate_phone: str,
    job_title: str,
    interview_date: str,
    total_score: float,
    recommendation: str,
    summary: str,
    pdf_path: str,
):
    """Send interview report (with PDF attachment) to the recruiter."""
    msg = MIMEMultipart("mixed")
    msg["Subject"] = REPORT_SUBJECT.format(
        candidate_name=candidate_name, job_title=job_title
    )
    msg["From"] = f"Hanrry AI <{settings.SMTP_USER}>"
    msg["To"] = settings.RECRUITER_EMAIL

    html = REPORT_HTML.format(
        candidate_name=candidate_name or "N/A",
        candidate_email=candidate_email or "N/A",
        candidate_phone=candidate_phone or "N/A",
        job_title=job_title,
        interview_date=interview_date,
        total_score=round(total_score, 1),
        recommendation=recommendation,
        summary=summary,
    )
    msg.attach(MIMEText(html, "html"))

    # Attach PDF report
    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            pdf_attachment = MIMEApplication(f.read(), _subtype="pdf")
            pdf_attachment.add_header(
                "Content-Disposition",
                "attachment",
                filename=os.path.basename(pdf_path),
            )
            msg.attach(pdf_attachment)

    try:
        _send(msg, settings.RECRUITER_EMAIL)
    except EmailSendError:
        raise
    except Exception as e:
        raise EmailSendError(f"Failed to send report email: {e}")
