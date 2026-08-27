"""
Pydantic schemas for Resume, Candidate, Interview, and Report.
"""
from __future__ import annotations
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ─────────────────────── Enums ────────────────────────────────────────────────

class CandidateStatusEnum(str, Enum):
    UPLOADED    = "uploaded"
    SELECTED    = "selected"     # legacy/backwards compatibility
    FILTERED    = "filtered"
    REJECTED    = "rejected"
    CONTACTED   = "contacted"
    SCHEDULED   = "scheduled"
    INTERVIEWED = "interviewed"


class RecommendationEnum(str, Enum):
    HIRE   = "HIRE"
    MAYBE  = "MAYBE"
    REJECT = "REJECT"


# ─────────────────────── Resume Upload ────────────────────────────────────────

class ResumeUploadResponse(BaseModel):
    message: str
    job_id: str
    total_uploaded: int
    candidates: List[str]  # list of candidate IDs


# ─────────────────────── JD / Filter ─────────────────────────────────────────

class JDFilterRequest(BaseModel):
    job_id: str
    jd_text: str
    job_title: str
    company: str = ""
    min_score: float = Field(default=0.6, ge=0.0, le=1.0)


class FilteredCandidate(BaseModel):
    candidate_id: str
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    match_score: float
    status: CandidateStatusEnum


class JDFilterResponse(BaseModel):
    job_id: str
    total_candidates: int
    filtered_count: int
    candidates: List[FilteredCandidate]


# ─────────────────────── Schedule ─────────────────────────────────────────────

class ScheduleInterviewRequest(BaseModel):
    token: str
    interview_datetime: datetime  # ISO 8601 from candidate's response


class ScheduleInterviewResponse(BaseModel):
    message: str
    candidate_id: str
    interview_datetime: datetime


# ─────────────────────── Analysis ─────────────────────────────────────────────

class QuestionAnalysis(BaseModel):
    question: str
    answer: str
    score: float = Field(ge=0.0, le=10.0)
    feedback: str


class InterviewAnalysis(BaseModel):
    session_id: str
    candidate_name: Optional[str]
    job_title: str
    total_score: float
    recommendation: RecommendationEnum
    strengths: List[str]
    weaknesses: List[str]
    question_breakdown: List[QuestionAnalysis]
    summary: str
    interviewed_at: datetime


# ─────────────────────── Report ───────────────────────────────────────────────

class ReportResponse(BaseModel):
    session_id: str
    report_path: str
    report_sent_to: str
    message: str
