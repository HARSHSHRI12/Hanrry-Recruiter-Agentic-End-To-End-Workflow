"""
LangGraph Post-Call Analysis Agent
State machine that:
  1. Parses raw transcript
  2. Extracts Q&A pairs
  3. Scores each answer
  4. Generates strengths/weaknesses
  5. Produces final recommendation
"""
from __future__ import annotations
import json
from typing import TypedDict, List, Optional, Annotated
import operator

from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)


# ─────────────────────── State ────────────────────────────────────────────────

class AnalysisState(TypedDict):
    session_id: str
    candidate_name: str
    job_title: str
    jd_text: str
    transcript: str

    # Intermediate
    qa_pairs: List[dict]                        # [{question, answer}, ...]
    scored_pairs: List[dict]                    # [{question, answer, score, feedback}, ...]

    # Output
    total_score: float
    recommendation: str                         # HIRE / MAYBE / REJECT
    strengths: List[str]
    weaknesses: List[str]
    summary: str
    error: Optional[str]


# ─────────────────────── LLM ──────────────────────────────────────────────────

def _get_llm(temperature: float = 0):
    return ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=temperature,
    )


# ─────────────────────── Node: Extract Q&A ────────────────────────────────────

_QA_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     """You are an expert at parsing interview transcripts.
Extract all question-answer pairs from the transcript below.
The interviewer is 'Hanrry' (AI). The candidate is the other speaker.
Return ONLY a valid JSON array:
[{{"question": "...", "answer": "..."}}, ...]
If no clear Q&A found, return an empty array [].
"""),
    ("human", "TRANSCRIPT:\n{transcript}"),
])


async def node_extract_qa(state: AnalysisState) -> AnalysisState:
    log.info(f"[{state['session_id']}] Extracting Q&A pairs from transcript")
    try:
        chain = _QA_PROMPT | _get_llm() | JsonOutputParser()
        qa_pairs = await chain.ainvoke({"transcript": state["transcript"][:6000]})
        state["qa_pairs"] = qa_pairs if isinstance(qa_pairs, list) else []
    except Exception as e:
        log.error(f"QA extraction failed: {e}")
        state["qa_pairs"] = []
        state["error"] = str(e)
    return state


# ─────────────────────── Node: Score Answers ──────────────────────────────────

_SCORE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     """You are a technical interviewer evaluating candidate answers.
Given the job role, a question, and the candidate's answer, score the answer from 0–10.
Return ONLY valid JSON:
{{"score": 7.5, "feedback": "brief one-sentence feedback"}}
"""),
    ("human",
     "Job Title: {job_title}\n\nQuestion: {question}\n\nAnswer: {answer}"),
])


async def node_score_answers(state: AnalysisState) -> AnalysisState:
    log.info(f"[{state['session_id']}] Scoring {len(state['qa_pairs'])} answers")
    chain = _SCORE_PROMPT | _get_llm() | JsonOutputParser()
    scored = []

    for qa in state["qa_pairs"]:
        try:
            result = await chain.ainvoke({
                "job_title": state["job_title"],
                "question": qa.get("question", ""),
                "answer": qa.get("answer", ""),
            })
            scored.append({
                "question": qa.get("question"),
                "answer": qa.get("answer"),
                "score": float(result.get("score", 5.0)),
                "feedback": result.get("feedback", ""),
            })
        except Exception as e:
            log.warning(f"Scoring failed for one Q&A: {e}")
            scored.append({**qa, "score": 5.0, "feedback": "Auto-scored due to error"})

    state["scored_pairs"] = scored
    return state


# ─────────────────────── Node: Aggregate ─────────────────────────────────────

async def node_aggregate(state: AnalysisState) -> AnalysisState:
    log.info(f"[{state['session_id']}] Aggregating scores")
    scores = [s["score"] for s in state["scored_pairs"]]
    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    state["total_score"] = avg

    if avg >= 7.5:
        state["recommendation"] = "HIRE"
    elif avg >= 5.0:
        state["recommendation"] = "MAYBE"
    else:
        state["recommendation"] = "REJECT"

    return state


# ─────────────────────── Node: Generate Insights ──────────────────────────────

_INSIGHTS_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     """You are a professional recruiter writing a post-interview analysis.
Given the interview transcript and scored Q&A data, produce:
- 3-5 key strengths of the candidate
- 3-5 areas for improvement
- A professional 3-sentence summary paragraph

Return ONLY valid JSON:
{{
  "strengths": ["...", "..."],
  "weaknesses": ["...", "..."],
  "summary": "..."
}}
"""),
    ("human",
     "Job Title: {job_title}\nOverall Score: {score}/10\nRecommendation: {rec}\n\n"
     "Scored Q&A:\n{scored_qa}\n\nTranscript Excerpt:\n{transcript}"),
])


async def node_generate_insights(state: AnalysisState) -> AnalysisState:
    log.info(f"[{state['session_id']}] Generating insights")
    try:
        chain = _INSIGHTS_PROMPT | _get_llm(temperature=0.3) | JsonOutputParser()
        result = await chain.ainvoke({
            "job_title": state["job_title"],
            "score": state["total_score"],
            "rec": state["recommendation"],
            "scored_qa": json.dumps(state["scored_pairs"][:8], indent=2),
            "transcript": state["transcript"][:3000],
        })
        state["strengths"] = result.get("strengths", [])
        state["weaknesses"] = result.get("weaknesses", [])
        state["summary"] = result.get("summary", "Interview completed.")
    except Exception as e:
        log.error(f"Insights generation failed: {e}")
        state["strengths"] = ["Unable to extract strengths"]
        state["weaknesses"] = ["Unable to extract weaknesses"]
        state["summary"] = "Interview analysis could not be fully completed."
    return state


# ─────────────────────── Build Graph ──────────────────────────────────────────

def build_analysis_graph() -> StateGraph:
    graph = StateGraph(AnalysisState)

    graph.add_node("extract_qa", node_extract_qa)
    graph.add_node("score_answers", node_score_answers)
    graph.add_node("aggregate", node_aggregate)
    graph.add_node("generate_insights", node_generate_insights)

    graph.set_entry_point("extract_qa")
    graph.add_edge("extract_qa", "score_answers")
    graph.add_edge("score_answers", "aggregate")
    graph.add_edge("aggregate", "generate_insights")
    graph.add_edge("generate_insights", END)

    return graph.compile()


# Singleton compiled graph
analysis_graph = build_analysis_graph()


async def run_analysis(
    session_id: str,
    candidate_name: str,
    job_title: str,
    jd_text: str,
    transcript: str,
) -> AnalysisState:
    """Entry point: run the full analysis graph and return final state."""
    log.info(f"Running LangGraph analysis for session={session_id}")
    initial_state: AnalysisState = {
        "session_id": session_id,
        "candidate_name": candidate_name,
        "job_title": job_title,
        "jd_text": jd_text,
        "transcript": transcript,
        "qa_pairs": [],
        "scored_pairs": [],
        "total_score": 0.0,
        "recommendation": "MAYBE",
        "strengths": [],
        "weaknesses": [],
        "summary": "",
        "error": None,
    }
    result = await analysis_graph.ainvoke(initial_state)
    log.info(
        f"Analysis complete: score={result['total_score']}, rec={result['recommendation']}"
    )
    return result
