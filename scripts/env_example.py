"""Parse `.env.example`-style files and classify each variable as secret vs config.

This is a best-effort fallback for servers whose registry entry doesn't declare
`environment_variables`. The classifier uses the variable *name* only — we never
look at the value, which on `.env.example` is a placeholder anyway.
"""

from __future__ import annotations

import re

# Match `VAR=...` or `export VAR=...` lines; ignore comments and blank lines.
_VAR_RE = re.compile(
    r"^[ \t]*(?:export[ \t]+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)[ \t]*="
)

# Tokens whose presence by themselves strongly imply a credential. Matched
# case-insensitively against `_`-separated tokens in the variable name.
_HARD_SECRET_TOKENS = frozenset({
    "SECRET", "TOKEN", "PASSWORD", "PASSWD", "PWD", "APIKEY", "JWT",
})

# Tokens that imply a credential unless the name also contains a config suffix.
_SOFT_SECRET_TOKENS = frozenset({
    "KEY", "PRIVATE", "CREDENTIAL", "BEARER", "SIGNING", "SALT", "DSN",
    "PIN", "OTP", "SESSION", "HMAC",
})

# Even weaker — only counts as a secret when paired with no config suffix.
_WEAK_SECRET_TOKENS = frozenset({"AUTH", "ACCESS", "PASS"})

# Tokens that mark a variable as plain config even when a secret-ish keyword
# also appears (e.g. AUTH_REQUIRED, JWT_ALGORITHM, MAX_MODELS_PER_SESSION).
_CONFIG_SUFFIX_TOKENS = frozenset({
    "REQUIRED", "ENABLED", "DISABLED", "URL", "HOST", "PORT", "PATH", "DIR",
    "NAME", "ID", "METHOD", "TYPE", "FORMAT", "TIMEOUT", "INTERVAL", "EVENTS",
    "MODE", "LEVEL", "COUNT", "LIMIT", "SIZE", "TTL", "PREFIX", "SUFFIX",
    "ENDPOINT", "REGION", "VERSION", "DEBUG", "VERBOSE", "DRY", "LOG",
    "ALGORITHM", "STRATEGY", "POLICY", "SCOPE", "SCOPES", "AUDIENCE",
    "ISSUER", "REALM", "PROJECT",
    "MAX", "MIN", "AGE", "SECONDS", "MINUTES", "HOURS", "DAYS", "MS",
    "RETRIES", "BACKOFF", "DELAY", "RATE", "THRESHOLD", "BUFFER",
    "MODELS", "MODEL",
})


def is_likely_secret(name: str) -> bool:
    """Classify an env var name as a likely credential. See module docstring."""
    tokens = set(name.upper().split("_"))

    has_hard = bool(tokens & _HARD_SECRET_TOKENS)
    has_soft = bool(tokens & _SOFT_SECRET_TOKENS)
    has_weak = bool(tokens & _WEAK_SECRET_TOKENS)

    if not (has_hard or has_soft or has_weak):
        return False

    has_config_suffix = bool(tokens & _CONFIG_SUFFIX_TOKENS)

    # Hard tokens beat config suffixes (SECRET_FILE, TOKEN_PATH still point at
    # secret material) — except for clearly meta names like JWT_ALGORITHM.
    if has_hard:
        return not bool(
            tokens & {"ALGORITHM", "NAME", "ID", "TYPE", "METHOD", "FORMAT", "MODE"}
        )

    # Soft and weak tokens lose to any config suffix.
    return not has_config_suffix


def parse_env_file(text: str) -> list[tuple[str, bool]]:
    """Extract `(name, is_secret)` pairs from a `.env.example` file.

    Duplicates are dropped, preserving first occurrence.
    """
    seen: set[str] = set()
    out: list[tuple[str, bool]] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _VAR_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        if name in seen:
            continue
        seen.add(name)
        out.append((name, is_likely_secret(name)))
    return out


__all__ = ["is_likely_secret", "parse_env_file"]
