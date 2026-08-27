"""
Custom application exceptions.
"""


class HanrryBaseException(Exception):
    """Base exception for all Hanrry errors."""
    pass


class ResumeParseError(HanrryBaseException):
    """Raised when resume parsing fails."""
    pass


class ContactExtractionError(HanrryBaseException):
    """Raised when contact info cannot be extracted."""
    pass


class FilterError(HanrryBaseException):
    """Raised during JD-based candidate filtering."""
    pass


class EmailSendError(HanrryBaseException):
    """Raised when sending an email fails."""
    pass


class CallInitError(HanrryBaseException):
    """Raised when a telephony call cannot be initiated."""
    pass


class SchedulerError(HanrryBaseException):
    """Raised when scheduling a call fails."""
    pass


class ReportGenerationError(HanrryBaseException):
    """Raised when report generation fails."""
    pass
