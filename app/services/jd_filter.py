"""
JD Filter Service
Scores resumes against a Job Description using LangChain + semantic similarity.
Uses Pinecone vector store when available, falls back to LLM scoring.
"""
from __future__ import annotations
from typing import List, Tuple

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from app.core.config import settings
from app.core.logger import get_logger
from app.core.exceptions import FilterError

log = get_logger(__name__)


# ─────────────────────── LLM Scoring ──────────────────────────────────────────

_SCORE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     """You are an expert technical recruiter AI.
Given the Job Description (JD) and a candidate's resume text, score the candidate
on a scale of 0.0 to 1.0 (two decimal places) based on:
- Skills match (40%)
- Experience relevance (30%)
- Education (15%)
- Overall fit (15%)

Respond ONLY with valid JSON in this exact format:
{{
  "score": 0.85,
  "skills_match": 0.9,
  "experience_match": 0.8,
  "education_match": 0.7,
  "overall_fit": 0.9,
  "candidate_name": "detected name or UNKNOWN",
  "reasoning": "brief 2-sentence explanation"
}}"""),
    ("human",
     "JOB DESCRIPTION:\n{jd_text}\n\n---\nRESUME:\n{resume_text}"),
])


async def score_resume_llm(jd_text: str, resume_text: str) -> dict:
    """Score a single resume against a JD using Gemini."""
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0,
    )
    parser = JsonOutputParser()
    chain = _SCORE_PROMPT | llm | parser

    try:
        result = await chain.ainvoke({
            "jd_text": jd_text[:4000],
            "resume_text": resume_text[:4000],
        })
        return result
    except Exception as e:
        log.error(f"LLM scoring failed: {e}")
        raise FilterError(f"LLM scoring error: {e}")


async def filter_candidates(
    jd_text: str,
    candidates: List[Tuple[str, str]],   # [(candidate_id, resume_text), ...]
    min_score: float = 0.6,
) -> List[Tuple[str, float, dict]]:
    """
    Score all candidates against the JD.
    Returns list of (candidate_id, score, full_result) for candidates >= min_score,
    sorted by score descending.
    """
    log.info(f"Filtering {len(candidates)} candidates (min_score={min_score})")
    results = []

    for cand_id, resume_text in candidates:
        try:
            result = await score_resume_llm(jd_text, resume_text)
            score = float(result.get("score", 0.0))
            log.info(f"  → {cand_id}: score={score}")
            results.append((cand_id, score, result))
        except Exception as e:
            log.warning(f"Skipping {cand_id} due to scoring error: {e}")

    # Filter and sort
    filtered = [(cid, s, r) for cid, s, r in results if s >= min_score]
    filtered.sort(key=lambda x: x[1], reverse=True)

    log.info(f"Filtered: {len(filtered)}/{len(candidates)} passed threshold")
    return filtered
