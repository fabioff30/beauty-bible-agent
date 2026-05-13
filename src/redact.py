"""
PII redaction — applied before persisting user text and before
sending content to the sleep-time consolidation LLM.

Trade-off: regex is fast and explainable but imperfect.
For the bot's domain (cosmetics chat in PT-BR), the most likely PII
leaks are phone, email, CPF, CEP, and full name fragments. We redact
those and leave the rest verbatim so the consolidation LLM still has
enough signal.
"""

import hashlib
import re

# Brazilian CPF: 11 digits, often dotted: 123.456.789-01 or plain 12345678901
_CPF_RE = re.compile(r'\b(?:\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})\b')

# CEP: 12345-678 or 12345678
_CEP_RE = re.compile(r'\b\d{5}-?\d{3}\b')

# Phone: +55 (11) 91234-5678 / 11912345678 / (11) 1234-5678
_PHONE_RE = re.compile(
    r'(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?\d{4,5}[-\s]?\d{4}\b'
)

# Email
_EMAIL_RE = re.compile(r'\b[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}\b')

# Credit card: 13–19 digits, possibly space/dash separated. Conservative.
_CARD_RE = re.compile(r'\b(?:\d[ -]?){13,19}\b')


def redact_pii(text: str) -> str:
    """Return text with PII patterns replaced by tokens like [EMAIL]."""
    if not text:
        return text
    text = _EMAIL_RE.sub('[EMAIL]', text)
    text = _CPF_RE.sub('[CPF]', text)
    text = _CARD_RE.sub('[CARD]', text)
    text = _PHONE_RE.sub('[TEL]', text)
    text = _CEP_RE.sub('[CEP]', text)
    return text


def hash_photo(content: bytes) -> str:
    """SHA-256 of a photo's raw bytes — stable identifier without storing the image."""
    return hashlib.sha256(content).hexdigest()
