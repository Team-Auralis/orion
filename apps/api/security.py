import re

def mask_pii(text: str) -> str:
    """Masks PII like Phone Numbers, Emails, and SSNs from civilian distress messages."""
    if not text:
        return text
    
    # Mask Emails
    text = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[EMAIL REDACTED]', text)
    
    # Mask Phone Numbers
    text = re.sub(r'\b(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', '[PHONE REDACTED]', text)
    
    # Mask SSNs
    text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[SSN REDACTED]', text)
    
    return text
