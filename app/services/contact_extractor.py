"""
Contact Extractor Service
Extracts phone numbers and emails from raw resume text.
Uses regex as primary method with LLM fallback.
"""
import re
from typing import Tuple, Optional

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.core.logger import get_logger
from app.core.exceptions import ContactExtractionError

log = get_logger(__name__)

# Regex Patterns 

# Matches Indian (+91), US (+1) and generic international phone numbers
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-.]?)?"          # optional country code
    r"(?:\(?\d{2,4}\)?[\s\-.]?)?"       # optional area code
    r"\d{3,5}[\s\-.]?\d{4,6}",         # main number
    re.MULTILINE,
)

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.MULTILINE,
)


def _clean_phone(raw: str) -> str:
    """Remove all non-digit characters except leading +."""
    digits = re.sub(r"[^\d+]", "", raw)
    return digits


def extract_contacts_regex(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Primary extraction using regex.
    Returns (phone, email) – first match each.
    """
    phones = _PHONE_RE.findall(text)
    emails = _EMAIL_RE.findall(text)

    phone = _clean_phone(phones[0]) if phones else None
    email = emails[0].lower() if emails else None

    # Basic sanity: phone must have at least 10 digits
    if phone and len(re.sub(r"\D", "", phone)) < 10:
        phone = None

    return phone, email


async def extract_contacts_llm(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    LLM fallback when regex finds nothing.
    """
    log.info("Using LLM fallback for contact extraction.")
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0,
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a contact extraction assistant. Extract the phone number and email "
         "address from the following resume text. Respond ONLY in this format:\n"
         "phone: <phone or NONE>\nemail: <email or NONE>"),
        ("human", "{resume_text}"),
    ])
    chain = prompt | llm
    result = await chain.ainvoke({"resume_text": text[:3000]})
    content = result.content.strip()

    phone, email = None, None
    for line in content.splitlines():
        if line.lower().startswith("phone:"):
            val = line.split(":", 1)[1].strip()
            phone = val if val.upper() != "NONE" else None
        elif line.lower().startswith("email:"):
            val = line.split(":", 1)[1].strip()
            email = val.lower() if val.upper() != "NONE" else None

    return phone, email


async def extract_contacts(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Main entry point: regex first, LLM fallback.
    Returns (phone, email).
    """
    phone, email = extract_contacts_regex(text)

    if not phone and not email:
        try:
            phone, email = await extract_contacts_llm(text)
        except Exception as e:
            log.warning(f"LLM contact extraction failed: {e}")

    log.info(f"Extracted → phone={phone}, email={email}")
    return phone, email
