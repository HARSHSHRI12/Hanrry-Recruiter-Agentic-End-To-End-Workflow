"""
Report Generator Service
Generates a professional PDF interview report using ReportLab.
"""
import os
import json
from datetime import datetime
from typing import Optional

from app.core.logger import get_logger
from app.core.exceptions import ReportGenerationError

log = get_logger(__name__)


def generate_report(
    output_dir: str,
    session_id: str,
    candidate_name: str,
    candidate_email: str,
    candidate_phone: str,
    job_title: str,
    company: str,
    interview_date: str,
    total_score: float,
    recommendation: str,
    strengths: list,
    weaknesses: list,
    summary: str,
    transcript: str,
    analysis_json: Optional[str] = None,
) -> str:
    """
    Generate a PDF report and return the file path.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    except ImportError:
        raise ReportGenerationError("reportlab not installed. Run: pip install reportlab")

    os.makedirs(output_dir, exist_ok=True)
    filename = f"report_{session_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
    filepath = os.path.join(output_dir, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    styles = getSampleStyleSheet()

    # ── Custom Styles ──────────────────────────────────────────────────────────
    DARK = colors.HexColor("#1a1a2e")
    ACCENT = colors.HexColor("#e94560")
    LIGHT_GRAY = colors.HexColor("#f7fafc")
    MED_GRAY = colors.HexColor("#4a5568")

    title_style = ParagraphStyle("title", parent=styles["Heading1"],
                                  textColor=DARK, fontSize=22, spaceAfter=4)
    subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"],
                                     textColor=ACCENT, fontSize=11, spaceAfter=12)
    section_style = ParagraphStyle("section", parent=styles["Heading2"],
                                    textColor=DARK, fontSize=13, spaceBefore=14, spaceAfter=6,
                                    borderPad=4)
    body_style = ParagraphStyle("body", parent=styles["Normal"],
                                 textColor=MED_GRAY, fontSize=10, leading=14)
    bullet_style = ParagraphStyle("bullet", parent=body_style, bulletIndent=10,
                                   leftIndent=20)

    def section_header(text: str):
        return [
            Paragraph(text, section_style),
            HRFlowable(width="100%", thickness=1.5, color=ACCENT, spaceAfter=6),
        ]

    # ── Recommendation Color ───────────────────────────────────────────────────
    rec_color = {
        "HIRE": colors.HexColor("#276749"),
        "MAYBE": colors.HexColor("#744210"),
        "REJECT": colors.HexColor("#742a2a"),
    }.get(recommendation, DARK)

    rec_bg = {
        "HIRE": colors.HexColor("#c6f6d5"),
        "MAYBE": colors.HexColor("#fefcbf"),
        "REJECT": colors.HexColor("#fed7d7"),
    }.get(recommendation, LIGHT_GRAY)

    # ── Build Story ────────────────────────────────────────────────────────────
    story = []

    # Header
    story.append(Paragraph("INTERVIEW SCREENING REPORT", title_style))
    story.append(Paragraph("Powered by Hanrry AI Recruiter", subtitle_style))
    story.append(Spacer(1, 0.3*cm))

    # Candidate info table
    info_data = [
        ["Candidate Name", candidate_name or "N/A"],
        ["Email", candidate_email or "N/A"],
        ["Phone", candidate_phone or "N/A"],
        ["Position Applied", job_title],
        ["Company", company or "N/A"],
        ["Interview Date", interview_date],
        ["Session ID", session_id],
    ]
    info_table = Table(info_data, colWidths=[5*cm, 12*cm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_GRAY),
        ("TEXTCOLOR", (0, 0), (0, -1), DARK),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(KeepTogether([*section_header("📋 Candidate Information"), info_table]))
    story.append(Spacer(1, 0.4*cm))

    # Score & Recommendation
    score_data = [
        ["Overall Score", f"{round(total_score, 1)} / 10"],
        ["Recommendation", recommendation],
    ]
    score_table = Table(score_data, colWidths=[5*cm, 12*cm])
    score_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_GRAY),
        ("BACKGROUND", (1, 1), (1, 1), rec_bg),
        ("TEXTCOLOR", (1, 1), (1, 1), rec_color),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 1), (1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(KeepTogether([*section_header("🎯 Score & Recommendation"), score_table]))
    story.append(Spacer(1, 0.4*cm))

    # Summary
    story.extend(section_header("💡 AI Summary"))
    story.append(Paragraph(summary or "No summary available.", body_style))
    story.append(Spacer(1, 0.4*cm))

    # Strengths
    story.extend(section_header("✅ Strengths"))
    for s in (strengths or ["None noted."]):
        story.append(Paragraph(f"• {s}", bullet_style))
    story.append(Spacer(1, 0.3*cm))

    # Weaknesses
    story.extend(section_header("⚠️ Areas for Improvement"))
    for w in (weaknesses or ["None noted."]):
        story.append(Paragraph(f"• {w}", bullet_style))
    story.append(Spacer(1, 0.4*cm))

    # Question Analysis
    if analysis_json:
        try:
            analysis = json.loads(analysis_json)
            breakdown = analysis.get("question_breakdown", [])
            if breakdown:
                story.extend(section_header("📝 Question-by-Question Analysis"))
                for i, qa in enumerate(breakdown, 1):
                    story.append(Paragraph(
                        f"<b>Q{i}:</b> {qa.get('question', '')}", body_style
                    ))
                    story.append(Paragraph(
                        f"<b>Answer:</b> {qa.get('answer', '')}", body_style
                    ))
                    story.append(Paragraph(
                        f"<b>Score:</b> {qa.get('score', 'N/A')}/10 — {qa.get('feedback', '')}",
                        ParagraphStyle("qscore", parent=body_style, textColor=ACCENT)
                    ))
                    story.append(Spacer(1, 0.2*cm))
        except Exception:
            pass

    # Transcript
    if transcript:
        story.extend(section_header("🎙️ Call Transcript (Excerpt)"))
        excerpt = transcript[:2000] + ("..." if len(transcript) > 2000 else "")
        story.append(Paragraph(
            excerpt.replace("\n", "<br/>"),
            ParagraphStyle("transcript", parent=body_style, fontSize=9,
                           backColor=LIGHT_GRAY, borderPad=8)
        ))

    # Footer
    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
    story.append(Paragraph(
        f"Generated by Hanrry AI Recruiter · {datetime.utcnow().strftime('%B %d, %Y %H:%M UTC')}",
        ParagraphStyle("footer", parent=styles["Normal"], fontSize=8,
                       textColor=colors.HexColor("#a0aec0"), alignment=TA_CENTER)
    ))

    doc.build(story)
    log.info(f"PDF report generated: {filepath}")
    return filepath
