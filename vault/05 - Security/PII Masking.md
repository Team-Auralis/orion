# PII Masking

#security #privacy

> Automated redaction of personally identifiable information from SOS messages.

## Purpose

Before civilian distress messages are stored, PII is automatically scrubbed to protect privacy.

## Patterns Detected

| Pattern | Regex | Action |
|---|---|---|
| **Email** | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | Redacted |
| **Phone** | Various phone formats | Redacted |
| **SSN** | `\d{3}-\d{2}-\d{4}` | Redacted |

## Implementation

Located in `apps/api/main.py`:
- Regex-based scrubbing engine
- Applied before database storage
- Applied before NATS publishing

## Current State

**Status: Functional**

- All three patterns (email, phone, SSN) tested
- Integrated into incident creation pipeline

## Related

- [[VEIL Security]]
- [[HAVEN Platform]]
- [[API Service]]
