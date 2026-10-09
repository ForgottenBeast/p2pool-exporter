import os
import time

_SENSITIVE_KEY_MARKERS = ("key", "secret", "password", "token")


def _is_sensitive_key(key):
    return isinstance(key, str) and any(
        marker in key.lower() for marker in _SENSITIVE_KEY_MARKERS
    )


def redact_sensitive(data):
    """Recursively replace values of sensitive-looking keys with "<redacted>".

    A key is considered sensitive if it contains "key", "secret", "password",
    or "token" (case-insensitive) anywhere in its name, e.g. "private_key",
    "coinbase_private_key", "api_secret", "redis_password", "auth_token".
    Used before logging any externally-sourced payload (P2Pool API payouts,
    raffle data, etc.) so secret material never reaches log output. Returns a
    new structure; the input is never mutated.
    """
    if isinstance(data, dict):
        return {
            k: "<redacted>" if _is_sensitive_key(k) else redact_sensitive(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact_sensitive(v) for v in data]
    return data


def redis_auth_kwargs():
    """Redis client auth kwargs from REDIS_PASSWORD_FILE (e.g. a systemd credential).

    Returns {} when unset so unauthenticated deployments keep working.
    """
    path = os.environ.get("REDIS_PASSWORD_FILE")
    if not path:
        return {}
    with open(path) as f:
        return {"password": f.read().rstrip("\r\n")}


def estimate_hashrate(accepted_shares):
    now = time.time()
    oldest_share = now
    total_difficulty = 0
    for s in accepted_shares:
        if s["timestamp"] < oldest_share:
            oldest_share = s["timestamp"]

    if now == oldest_share:
        return 0

    total_difficulty = sum(s["difficulty"] for s in accepted_shares)
    return total_difficulty / (now - oldest_share)  # Hashrate in H/s
