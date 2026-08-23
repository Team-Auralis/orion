import re

def mask_pii(text: str) -> str:
    """Masks PII like Phone Numbers, Emails, and SSNs from civilian distress messages."""
    if not text:
        return text
        
    # Safety guard: truncate to max 2048 characters to prevent any possibility of ReDoS
    # (API already limits to 1000, but we add a defense-in-depth bound here).
    text = text[:2048]
    
    # Mask Emails: Replaced overlapping [a-zA-Z0-9_.+-]+ with non-overlapping and simpler boundaries
    # avoiding catastrophic backtracking on long valid-looking prefixes that fail at the end.
    text = re.sub(r'[^\s@]+@[^\s@]+\.[^\s@]+', '[EMAIL REDACTED]', text)
    
    # Mask Phone Numbers: Simplified strict digit/dash pattern without ambiguous overlapping optional groups
    text = re.sub(r'\b(?:\+1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', '[PHONE REDACTED]', text)
    
    # Mask SSNs
    text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[SSN REDACTED]', text)
    
    return text

