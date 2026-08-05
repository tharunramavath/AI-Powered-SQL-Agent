"""Security helpers: API key auth, RBAC helpers, and secret redaction.

Kept dependency-light (no framework imports) so it is reusable by any host
application. Role-based access control maps a caller identity to a set of
allowed datasource ids.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Principal:
    """An authenticated caller identity."""

    api_key: str
    name: str
    roles: tuple[str, ...] = field(default_factory=tuple)
    # Datasource ids this principal may query; empty means "all allowed".
    allowed_datasources: tuple[str, ...] = field(default_factory=tuple)


def validate_api_key(key: str, valid_keys: list[str]) -> Principal | None:
    """Validate a bearer token against the configured API keys.

    Uses constant-time comparison to avoid timing attacks.

    Args:
        key: The presented token.
        valid_keys: List of accepted tokens.

    Returns:
        A Principal if the key is valid, otherwise None.
    """
    if not valid_keys:
        return None
    for candidate in valid_keys:
        if hmac.compare_digest(key, candidate):
            return Principal(api_key=secrets.token_hex(8), name="api-user", roles=("user",))
    return None


def principal_can_access_datasource(principal: Principal, datasource_id: str) -> bool:
    """Return True if the principal may query the given datasource.

    An empty allowed set means the principal has unrestricted access.
    """
    return not principal.allowed_datasources or datasource_id in principal.allowed_datasources


def redact_secrets(value: str) -> str:
    """Redact obvious secret patterns (URLs with passwords) for safe logging."""
    import re

    # postgresql://user:password@host  ->  postgresql://user:***@host
    pattern = re.compile(r"(://[^:/@]+:)([^@/]+)(@)", re.IGNORECASE)
    return pattern.sub(r"\1***\3", value)


def fingerprint_sql(sql: str) -> str:
    """Return a stable sha256 hash of a SQL string for caching/audit keys."""
    return hashlib.sha256(sql.strip().encode("utf-8")).hexdigest()
