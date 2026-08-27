"""
Caller identity at the network level.

Lived in routes/auth.py while login was the only rate-limited endpoint. The
contact form is the second, and the reasoning below is the kind that must not
be reimplemented from memory in a second place — get it wrong there and the
limiter either buckets every visitor together or trusts a spoofable header.
"""
from fastapi import Request


def client_ip(request: Request) -> str:
    """
    Caller's address, honouring the proxy header.

    Everything reaches this app through Cloudflare, so `request.client.host` is
    always the tunnel and would collapse every user onto one bucket — the first
    person to trip a limit would lock out everybody. `CF-Connecting-IP` is set
    by Cloudflare and cannot be spoofed past it; the chain order for
    X-Forwarded-For is left-most = original client.
    """
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
