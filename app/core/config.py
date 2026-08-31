"""
Core configuration - loads all settings from .env
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────
    APP_NAME: str = "Hanrry AI Recruiter"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ── LLM ──────────────────────────────────────────────
    GOOGLE_API_KEY: str
    OPENAI_API_KEY: Optional[str] = None

    # ── VideoSDK ─────────────────────────────────────────
    VIDEOSDK_AUTH_TOKEN: str
    VIDEOSDK_API_KEY: Optional[str] = None
    VIDEOSDK_SECRET: Optional[str] = None
    VIDEOSDK_ROUTING_RULE_ID: Optional[str] = None   # Required for outbound SIP calls

    # ── Pinecone ─────────────────────────────────────────
    PINECONE_API_KEY: Optional[str] = None
    PINECONE_INDEX_NAME: str = "hanrry-resumes"
    PINECONE_ENV: str = "us-east-1"

    # ── Database ─────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./hanrry.db"

    # ── Email (Resend / SMTP) ─────────────────────────────
    RESEND_API_KEY: Optional[str] = None
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    RECRUITER_EMAIL: str = ""

    # ── Telephony ────────────────────────────────────────
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_PHONE_NUMBER: Optional[str] = None
    VIDEOSDK_AGENT_HOST: str = "localhost"
    VIDEOSDK_AGENT_PORT: int = 8081

    # ── Public Base URL (used in emails) ─────────────────
    BASE_URL: str = "http://localhost:8000"  # Override with ngrok/production URL in .env

    # ── Scheduling ───────────────────────────────────────
    SCHEDULER_TIMEZONE: str = "Asia/Kolkata"

    # ── File Upload ──────────────────────────────────────
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
