"""R8 PRE-UAT H1-DIRECT (Owner source approval Gate A, 2026-11-19, path #99): TEST-only identity
from Google Cloud Run Direct IAP.

Active ONLY when ``TEST_IDENTITY_PROXY=google_iap`` (the config validator allows it only with
APP_ENV=test, DATA_REPOSITORY=mock, DEV_AUTH_MODE=false, ACCESS_MANAGEMENT_MODE=true,
MOCK_FIXTURE_PROFILE=uat_r8, PM_MASTER_TEST_PROFILE=true and no Sheets / credentials / registry
context). With the mode OFF nothing here is imported by the request path.

On every request the signed ``x-goog-iap-jwt-assertion`` is verified:
  * signature with Google's published IAP public keys (cached; one rate-limited refetch on an
    unknown key id; any fetch/parse failure -> no identity, i.e. fail closed);
  * header ``alg == ES256``; ``iss == https://cloud.google.com/iap``; the configured Cloud Run
    audience ``/projects/N/locations/R/services/S``; ``exp`` / ``iat`` with 30 s skew;
  * then the verified ``email`` claim is hashed (``sha256("r8-uat-iap:" + lower(trim(email)))``) and
    looked up EXACTLY in the TEST identity map -> one synthetic employee user id.

``google.auth.jwt.decode`` does not check the issuer (measured), so the issuer is checked here.
The unsigned ``x-goog-authenticated-user-*`` and the development ``X-Dev-*`` headers are never read.
Nothing here logs a token, an email or the map: only a fixed reason code.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from google.auth import jwt as google_jwt

logger = logging.getLogger("app.test_identity_proxy")

IAP_ASSERTION_HEADER = "x-goog-iap-jwt-assertion"
IAP_ISSUER = "https://cloud.google.com/iap"
IAP_ALGORITHM = "ES256"
IAP_PUBLIC_KEY_URL = "https://www.gstatic.com/iap/verify/public_key"
EMAIL_DIGEST_PREFIX = "r8-uat-iap:"
CLOCK_SKEW_SECONDS = 30
MAX_TOKEN_LENGTH = 8192
# IAP assertions live 10 minutes; anything claiming a longer life is refused (defence in depth).
MAX_TOKEN_LIFETIME_SECONDS = 600 + 2 * 30
KEY_TTL_DEFAULT_SECONDS = 300
KEY_TTL_MIN_SECONDS = 60  # > the refetch interval, so an expiry refetch is never rate-limited by a success
KEY_TTL_MAX_SECONDS = 3600
KEY_REFETCH_MIN_INTERVAL_SECONDS = 30
KEY_FETCH_TIMEOUT_SECONDS = 5
PEM_PUBLIC_KEY_PREFIX = "-----BEGIN PUBLIC KEY-----"

CLOUD_RUN_AUDIENCE_RE = re.compile(r"^/projects/[0-9]+/locations/[a-z0-9-]+/services/[a-z0-9-]+$")
EMAIL_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SYNTHETIC_USER_ID_RE = re.compile(r"^USR-TEST-[A-Z0-9][A-Z0-9-]*$")

KeyFetcher = Callable[[], tuple[Mapping[str, str], int | None]]


def email_digest(email: str) -> str:
    """The identity-map key of one verified email (no plain-text email is ever configured)."""
    return hashlib.sha256((EMAIL_DIGEST_PREFIX + email.strip().lower()).encode("utf-8")).hexdigest()


def parse_identity_map(raw: str) -> dict[str, str]:
    """Parse and validate ``TEST_IDENTITY_MAP`` (JSON object: email digest -> synthetic user id).
    Non-empty; every key a lowercase 64-hex digest; every value a ``USR-TEST-`` synthetic id;
    one human -> one employee (values unique). Raises ValueError (no value is echoed)."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("TEST_IDENTITY_MAP must be a JSON object") from None
    if not isinstance(data, dict) or not data:
        raise ValueError("TEST_IDENTITY_MAP must be a non-empty JSON object")
    for key, value in data.items():
        if not isinstance(key, str) or not EMAIL_DIGEST_RE.fullmatch(key):
            raise ValueError("TEST_IDENTITY_MAP keys must be lowercase sha256 hex email digests")
        if not isinstance(value, str) or not SYNTHETIC_USER_ID_RE.fullmatch(value):
            raise ValueError("TEST_IDENTITY_MAP values must be synthetic USR-TEST- user ids")
    if len(set(data.values())) != len(data):
        raise ValueError("TEST_IDENTITY_MAP must map each person to a different synthetic employee")
    return dict(data)


def known_synthetic_user_ids() -> frozenset[str]:
    """Active synthetic TEST accounts of the Access Management Mock seed (the only identities a
    hosted TEST user may be mapped to)."""
    from app.repositories.mock import seed_data

    rows = [*seed_data.SEED_PERSONNEL_MASTER, *seed_data.SEED_ACCESS_PERSONNEL]
    return frozenset(
        row["user_id"] for row in rows
        if row.get("user_id") and row.get("active_status") == "ACTIVE" and row.get("is_test_data") == "TRUE"
        and SYNTHETIC_USER_ID_RE.fullmatch(row["user_id"])
    )


def fetch_iap_public_keys() -> tuple[dict[str, str], int | None]:
    """GET Google's IAP public keys (JSON: key id -> PEM SPKI public key) and the Cache-Control max-age."""
    request = urllib.request.Request(IAP_PUBLIC_KEY_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=KEY_FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310 (fixed https URL)
        if response.status != 200:
            raise ValueError("unexpected status")
        body = response.read(256 * 1024)
        cache_control = response.headers.get("Cache-Control", "")
    match = re.search(r"max-age=(\d+)", cache_control)
    return json.loads(body), int(match.group(1)) if match else None


def _valid_key_set(keys: object) -> dict[str, str]:
    if not isinstance(keys, Mapping) or not keys:
        raise ValueError("empty or malformed key set")
    out: dict[str, str] = {}
    for kid, pem in keys.items():
        if not isinstance(kid, str) or not kid or not isinstance(pem, str) or not pem.startswith(PEM_PUBLIC_KEY_PREFIX):
            raise ValueError("malformed key entry")
        out[kid] = pem
    return out


@dataclass
class IapKeyCache:
    """Thread-safe cache of the IAP public keys.

    * fresh for ``max-age`` (bounded to [60 s, 1 h]; default 5 min when absent);
    * an unknown key id triggers at most one refetch per ``KEY_REFETCH_MIN_INTERVAL_SECONDS``;
    * expired keys are never used: when a refresh fails after expiry, no key is returned.
    """

    fetcher: KeyFetcher | None = None  # None -> the module's fetch_iap_public_keys, resolved per fetch
    clock: Callable[[], float] = time.monotonic
    _keys: dict[str, str] = field(default_factory=dict)
    _expires_at: float = 0.0
    _last_fetch_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def key_for(self, kid: str) -> str | None:
        with self._lock:
            now = self.clock()
            fresh = now < self._expires_at
            if fresh and kid in self._keys:
                return self._keys[kid]
            if not fresh:
                self._keys = {}  # expired keys are never used
            if self._last_fetch_at is not None and now - self._last_fetch_at < KEY_REFETCH_MIN_INTERVAL_SECONDS:
                return None  # refetch rate-limited (unknown kid, or a failed/expired fetch moments ago)
            self._last_fetch_at = now
            try:
                raw, max_age = (self.fetcher or fetch_iap_public_keys)()
                keys = _valid_key_set(raw)
            except Exception:  # noqa: BLE001 - any failure fails closed
                logger.warning("iap_public_keys_unavailable")
                return None
            ttl = KEY_TTL_DEFAULT_SECONDS if max_age is None else max(KEY_TTL_MIN_SECONDS, min(int(max_age), KEY_TTL_MAX_SECONDS))
            self._keys, self._expires_at = keys, now + ttl
            return keys.get(kid)


@dataclass(frozen=True)
class IdentityProxy:
    """Verifies one IAP assertion and maps it to a synthetic TEST user id (or None)."""

    audience: str
    identity_map: Mapping[str, str]
    keys: IapKeyCache

    def identify(self, assertion: str | None) -> str | None:
        reason = self._reject_reason(assertion)
        if isinstance(reason, tuple):
            return reason[1]
        logger.info("iap_identity_rejected reason=%s", reason)
        return None

    def _reject_reason(self, assertion: str | None) -> str | tuple[str, str]:
        if not assertion:
            return "missing"
        if len(assertion) > MAX_TOKEN_LENGTH:
            return "oversized"
        try:
            header = google_jwt.decode_header(assertion)
        except Exception:  # noqa: BLE001
            return "malformed"
        if not isinstance(header, dict) or header.get("alg") != IAP_ALGORITHM:
            return "algorithm"
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            return "key_id"
        key = self.keys.key_for(kid)
        if key is None:
            return "unknown_key"
        try:
            claims = google_jwt.decode(assertion, certs={kid: key}, audience=self.audience,
                                       clock_skew_in_seconds=CLOCK_SKEW_SECONDS)
        except Exception:  # noqa: BLE001 - signature, audience, expiry, issued-at
            return "invalid"
        if claims.get("iss") != IAP_ISSUER:
            return "issuer"
        if claims.get("aud") != self.audience:
            return "audience"
        try:
            lifetime = int(claims["exp"]) - int(claims["iat"])
        except (KeyError, TypeError, ValueError):
            return "lifetime"
        if lifetime > MAX_TOKEN_LIFETIME_SECONDS:
            return "lifetime"
        email = claims.get("email")
        if not isinstance(email, str) or not email.strip():
            return "email"
        user_id = self.identity_map.get(email_digest(email))
        if user_id is None:
            return "unmapped"
        return ("ok", user_id)


def build_identity_proxy(audience: str, raw_identity_map: str, keys: IapKeyCache | None = None) -> IdentityProxy:
    """Startup check (fails the process, never a request): audience form, map shape, and every mapped
    id an active synthetic account of the Mock seed."""
    if not CLOUD_RUN_AUDIENCE_RE.fullmatch(audience or ""):
        raise RuntimeError("TEST_IAP_AUDIENCE must be /projects/PROJECT_NUMBER/locations/REGION/services/SERVICE")
    identity_map = parse_identity_map(raw_identity_map)
    unknown = [uid for uid in identity_map.values() if uid not in known_synthetic_user_ids()]
    if unknown:
        raise RuntimeError(f"TEST_IDENTITY_MAP points at unknown or inactive synthetic accounts: {sorted(unknown)}")
    return IdentityProxy(audience=audience, identity_map=identity_map, keys=keys or IapKeyCache())
