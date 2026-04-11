"""Security layer — authentication, rate-limiting, and execution sandboxing.

Planned components:
  - auth.py     : API-key / JWT bearer token validation (middleware)
  - sandbox.py  : allowlist for code-execution tools (prevent shell injection)
  - ratelimit.py: per-session token-bucket rate limiter
"""
