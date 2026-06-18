from __future__ import annotations

import re


SENSITIVE_QUERY_RE = re.compile(
    r"(?i)([?&](?:token|api[_-]?key|apikey|password|passwd|secret|cookie|authorization|access[_-]?key|refresh[_-]?token|pick[_-]?code|pickcode|receive[_-]?code|share[_-]?code)=)[^&#\s\"'<>]+"
)
AUTH_HEADER_RE = re.compile(r"(?im)^(\s*(?:authorization|cookie|x-emby-token|x-mediabrowser-token)\s*[:=]\s*)[^\r\n]+")
TOKEN_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|api[_-]?key|apikey|password|passwd|secret|authorization|cookie)\s*[:=]\s*[^,\s\"'<>]+"
)


def redact_sensitive_text(value: str, max_length: int = 1000) -> str:
    redacted = SENSITIVE_QUERY_RE.sub(r"\1[REDACTED]", value)
    redacted = AUTH_HEADER_RE.sub(r"\1[REDACTED]", redacted)
    redacted = TOKEN_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    if len(redacted) > max_length:
        return redacted[:max_length] + "...[TRUNCATED]"
    return redacted
