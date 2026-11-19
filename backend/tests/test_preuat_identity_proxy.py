"""R8 PRE-UAT H1-DIRECT (Owner source approval Gate A, 2026-11-19, path #100): TEST hosted identity from
Cloud Run Direct IAP — verifier, key cache, hosting fence, mode isolation, SPA fallback and config.

Every token here is signed with a locally generated P-256 key; no network is used (the key fetcher is
replaced). Ids: V* verifier, K* key cache, G* hosting fence, C* config, S* SPA, H* identity map,
B* business with a verified identity.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from google.auth import crypt
from google.auth import jwt as google_jwt
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from app.domain import test_identity_proxy as tip

PROJECT_AUDIENCE = "/projects/123456789012/locations/asia-southeast1/services/r8-uat-test"
LB_AUDIENCE = "/projects/123456789012/global/backendServices/987654321"
MGR_EMAIL, OPM_EMAIL, CLERK_EMAIL, TECH_EMAIL = (
    "owner.tester@example.test", "assigner.tester@example.test", "reader.tester@example.test",
    "tech.tester@example.test")
UNMAPPED_EMAIL = "stranger@example.test"
API = "/api/v1"


def _keypair() -> tuple[bytes, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private, public


PRIVATE, PUBLIC = _keypair()
OTHER_PRIVATE, OTHER_PUBLIC = _keypair()
KID = "test-kid-1"


def mint(email: str | None = MGR_EMAIL, *, private: bytes = PRIVATE, kid: str = KID, **overrides) -> str:
    now = int(time.time())
    claims = {"iss": tip.IAP_ISSUER, "aud": PROJECT_AUDIENCE, "iat": now, "exp": now + 600,
              "sub": "accounts.google.com:1234567890"}
    if email is not None:
        claims["email"] = email
    claims.update(overrides)
    for key in [k for k, v in claims.items() if v is None]:
        del claims[key]
    return google_jwt.encode(crypt.ES256Signer.from_string(private, key_id=kid), claims).decode()


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unsigned(header: dict, claims: dict, signature: bytes = b"") -> str:
    return f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims).encode())}.{b64(signature)}"


def identity_map(**extra: str) -> dict[str, str]:
    mapping = {tip.email_digest(MGR_EMAIL): "USR-TEST-AM-MGR", tip.email_digest(OPM_EMAIL): "USR-TEST-AM-OPM",
               tip.email_digest(CLERK_EMAIL): "USR-TEST-AM-CLERK", tip.email_digest(TECH_EMAIL): "USR-TEST-911"}
    mapping.update(extra)
    return mapping


class FakeFetcher:
    def __init__(self, keys: dict | None = None, max_age: int | None = 3000) -> None:
        self.keys = {KID: PUBLIC} if keys is None else keys
        self.max_age = max_age
        self.calls = 0
        self.fail = False

    def __call__(self):
        self.calls += 1
        if self.fail:
            raise OSError("network down")
        return self.keys, self.max_age


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def proxy(fetcher: FakeFetcher | None = None, clock: Clock | None = None, mapping: dict | None = None):
    cache = tip.IapKeyCache(fetcher=fetcher or FakeFetcher(), clock=clock or Clock())
    return tip.IdentityProxy(audience=PROJECT_AUDIENCE, identity_map=mapping or identity_map(), keys=cache)


# V — verifier ------------------------------------------------------------------------------------


def test_v1_valid_assertion_maps_to_the_synthetic_employee() -> None:
    assert proxy().identify(mint()) == "USR-TEST-AM-MGR"
    assert proxy().identify(mint(OPM_EMAIL)) == "USR-TEST-AM-OPM"


def test_v2_signature_by_another_key_is_refused() -> None:
    assert proxy().identify(mint(private=OTHER_PRIVATE)) is None


def test_v3_forged_algorithms_are_refused() -> None:
    now = int(time.time())
    claims = {"iss": tip.IAP_ISSUER, "aud": PROJECT_AUDIENCE, "iat": now, "exp": now + 600, "email": MGR_EMAIL}
    head = lambda alg: {"alg": alg, "kid": KID, "typ": "JWT"}  # noqa: E731
    signing_input = f"{b64(json.dumps(head('HS256')).encode())}.{b64(json.dumps(claims).encode())}"
    hs = hmac.new(PUBLIC.encode(), signing_input.encode(), hashlib.sha256).digest()
    assert proxy().identify(f"{signing_input}.{b64(hs)}") is None  # HS256 with the public key as secret
    assert proxy().identify(unsigned(head("none"), claims)) is None
    assert proxy().identify(unsigned(head("RS256"), claims, b"x" * 256)) is None
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_pem = rsa_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    rs = google_jwt.encode(crypt.RSASigner.from_string(rsa_pem, key_id=KID), claims).decode()
    assert proxy().identify(rs) is None


def test_v4_expired_and_not_yet_valid_assertions_are_refused() -> None:
    now = int(time.time())
    assert proxy().identify(mint(iat=now - 900, exp=now - 31 - 60)) is None
    assert proxy().identify(mint(iat=now + 600, exp=now + 1200)) is None
    assert proxy().identify(mint(exp=None)) is None
    assert proxy().identify(mint(iat=None)) is None


def test_v4b_clock_skew_tolerance_is_thirty_seconds() -> None:
    now = int(time.time())
    assert proxy().identify(mint(iat=now - 600, exp=now - 10)) == "USR-TEST-AM-MGR"


def test_v5_v6_wrong_audiences_are_refused() -> None:
    assert proxy().identify(mint(aud=LB_AUDIENCE)) is None
    assert proxy().identify(mint(aud="/projects/123456789012/locations/asia-southeast1/services/other")) is None
    assert proxy().identify(mint(aud="/projects/123456789012/locations/us-central1/services/r8-uat-test")) is None
    assert proxy().identify(mint(aud=[PROJECT_AUDIENCE, LB_AUDIENCE])) is None
    assert proxy().identify(mint(aud=None)) is None


def test_v7_wrong_issuer_is_refused_even_though_decode_alone_accepts_it() -> None:
    token = mint(iss="https://accounts.google.com")
    claims = google_jwt.decode(token, certs={KID: PUBLIC}, audience=PROJECT_AUDIENCE)  # the measured gap
    assert claims["iss"] == "https://accounts.google.com"
    assert proxy().identify(token) is None
    assert proxy().identify(mint(iss=None)) is None


def test_v8_unknown_key_id_is_refused_with_one_rate_limited_refetch() -> None:
    fetcher, clock = FakeFetcher(), Clock()
    p = proxy(fetcher, clock)
    assert p.identify(mint()) == "USR-TEST-AM-MGR"
    assert fetcher.calls == 1
    for _ in range(5):  # within the refetch interval of the last fetch: no refetch at all
        assert p.identify(mint(kid="unknown")) is None
    assert fetcher.calls == 1
    clock.now += tip.KEY_REFETCH_MIN_INTERVAL_SECONDS
    for _ in range(5):
        assert p.identify(mint(kid="unknown")) is None
    assert fetcher.calls == 2  # one refetch for the unknown kid, then rate-limited
    assert p.identify(mint()) == "USR-TEST-AM-MGR"  # known kid still served from the fresh cache


def test_v9_key_fetch_failure_or_malformed_body_fails_closed() -> None:
    fetcher = FakeFetcher()
    fetcher.fail = True
    assert proxy(fetcher).identify(mint()) is None
    for bad in ({}, {KID: "not a key"}, {KID: 123}, ["x"]):
        assert proxy(FakeFetcher(keys=bad)).identify(mint()) is None


def test_v12_email_normalisation_and_missing_email() -> None:
    assert proxy().identify(mint("  Owner.Tester@EXAMPLE.test ")) == "USR-TEST-AM-MGR"
    assert proxy().identify(mint(None)) is None
    assert proxy().identify(mint("")) is None
    assert proxy().identify(mint("owner.tester@example.test.evil")) is None


def test_v11_unmapped_account_gets_no_identity() -> None:
    assert proxy().identify(mint(UNMAPPED_EMAIL)) is None


def test_v15_missing_garbage_and_oversized_assertions() -> None:
    for value in (None, "", "abc", "a.b.c", "x" * (tip.MAX_TOKEN_LENGTH + 1)):
        assert proxy().identify(value) is None
    oversized_but_valid = mint(padding="p" * tip.MAX_TOKEN_LENGTH)
    assert len(oversized_but_valid) > tip.MAX_TOKEN_LENGTH
    assert proxy().identify(oversized_but_valid) is None


def test_v16_no_token_email_or_map_value_is_logged(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    p = proxy()
    token = mint(UNMAPPED_EMAIL)
    p.identify(token)
    p.identify(mint())
    p.identify(mint(iss="https://evil.example"))
    text = caplog.text
    for secret in (token, UNMAPPED_EMAIL, MGR_EMAIL, tip.email_digest(MGR_EMAIL), "USR-TEST-AM-MGR"):
        assert secret not in text
    assert "reason=unmapped" in text and "reason=issuer" in text


def test_v17_each_verification_layer_refuses_on_its_own(monkeypatch) -> None:
    """Defence in depth: every layer is pinned by its own reason, so removing one is caught even when
    another layer would still refuse the token."""
    now = int(time.time())
    claims = {"iss": tip.IAP_ISSUER, "aud": PROJECT_AUDIENCE, "iat": now, "exp": now + 600, "email": MGR_EMAIL}
    assert proxy()._reject_reason(unsigned({"alg": "HS256", "kid": KID}, claims, b"x" * 32)) == "algorithm"
    assert proxy()._reject_reason(mint(aud=LB_AUDIENCE)) == "invalid"  # google-auth audience check
    assert proxy()._reject_reason(mint(iss="https://evil.example")) == "issuer"
    assert proxy()._reject_reason(mint()) == ("ok", "USR-TEST-AM-MGR")
    # the explicit audience equality, independent of google-auth's own check
    real_decode = tip.google_jwt.decode
    monkeypatch.setattr(tip.google_jwt, "decode",
                        lambda token, **kw: {**real_decode(token, **kw), "aud": LB_AUDIENCE})
    assert proxy()._reject_reason(mint()) == "audience"


def test_v18_token_lifetime_is_capped() -> None:
    now = int(time.time())
    assert proxy().identify(mint(iat=now, exp=now + tip.MAX_TOKEN_LIFETIME_SECONDS)) == "USR-TEST-AM-MGR"
    assert proxy()._reject_reason(mint(iat=now, exp=now + tip.MAX_TOKEN_LIFETIME_SECONDS + 1)) == "lifetime"
    assert proxy().identify(mint(iat=now, exp=now + 10**8)) is None


# K — key cache -----------------------------------------------------------------------------------


def test_k1_cache_hit_needs_no_fetch_and_ttl_expiry_refetches() -> None:
    fetcher, clock = FakeFetcher(max_age=100), Clock()
    p = proxy(fetcher, clock)
    for _ in range(10):
        assert p.identify(mint()) == "USR-TEST-AM-MGR"
    assert fetcher.calls == 1
    clock.now += 101
    assert p.identify(mint()) == "USR-TEST-AM-MGR"
    assert fetcher.calls == 2


def test_k2_expired_keys_are_never_used_when_refresh_fails() -> None:
    fetcher, clock = FakeFetcher(max_age=60), Clock()
    p = proxy(fetcher, clock)
    assert p.identify(mint()) == "USR-TEST-AM-MGR"
    clock.now += 61
    fetcher.fail = True
    assert p.identify(mint()) is None
    clock.now += 5
    assert p.identify(mint()) is None  # still expired, refetch rate-limited: fail closed
    fetcher.fail = False
    clock.now += tip.KEY_REFETCH_MIN_INTERVAL_SECONDS
    assert p.identify(mint()) == "USR-TEST-AM-MGR"


def test_k3_ttl_is_bounded() -> None:
    fetcher, clock = FakeFetcher(max_age=10**9), Clock()
    p = proxy(fetcher, clock)
    p.identify(mint())
    clock.now += tip.KEY_TTL_MAX_SECONDS + 1
    p.identify(mint())
    assert fetcher.calls == 2
    fetcher2, clock2 = FakeFetcher(max_age=None), Clock()
    p2 = proxy(fetcher2, clock2)
    p2.identify(mint())
    clock2.now += tip.KEY_TTL_DEFAULT_SECONDS + 1
    p2.identify(mint())
    assert fetcher2.calls == 2


def test_k3b_short_max_age_never_locks_valid_users_out() -> None:
    fetcher, clock = FakeFetcher(max_age=5), Clock()
    p = proxy(fetcher, clock)
    for step in range(0, 600, 3):  # ten minutes of traffic every 3 s
        clock.now = 1000.0 + step
        assert p.identify(mint()) == "USR-TEST-AM-MGR", step
    assert fetcher.calls <= 600 // tip.KEY_TTL_MIN_SECONDS + 1


def test_k4_rotated_key_is_picked_up_after_one_refetch() -> None:
    fetcher, clock = FakeFetcher(), Clock()
    p = proxy(fetcher, clock)
    assert p.identify(mint()) == "USR-TEST-AM-MGR"
    fetcher.keys = {KID: PUBLIC, "kid-2": OTHER_PUBLIC}
    assert p.identify(mint(private=OTHER_PRIVATE, kid="kid-2")) is None  # inside the refetch interval
    clock.now += tip.KEY_REFETCH_MIN_INTERVAL_SECONDS
    assert p.identify(mint(private=OTHER_PRIVATE, kid="kid-2")) == "USR-TEST-AM-MGR"
    assert fetcher.calls == 2


def test_k5_fetch_parses_max_age(monkeypatch) -> None:
    class Response:
        status = 200
        headers = {"Cache-Control": "public, max-age=3000"}

        def read(self, _n):
            return json.dumps({KID: PUBLIC}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"], seen["timeout"] = request.full_url, timeout
        return Response()

    monkeypatch.setattr(tip.urllib.request, "urlopen", fake_urlopen)
    keys, max_age = tip.fetch_iap_public_keys()
    assert keys == {KID: PUBLIC} and max_age == 3000
    assert seen == {"url": "https://www.gstatic.com/iap/verify/public_key", "timeout": tip.KEY_FETCH_TIMEOUT_SECONDS}


# H — identity map --------------------------------------------------------------------------------


def test_h1_identity_map_validation() -> None:
    good = identity_map()
    assert tip.parse_identity_map(json.dumps(good)) == good
    bad_values = [
        "", "not json", "[]", "{}", json.dumps({MGR_EMAIL: "USR-TEST-AM-MGR"}),
        json.dumps({tip.email_digest(MGR_EMAIL).upper(): "USR-TEST-AM-MGR"}),
        json.dumps({tip.email_digest(MGR_EMAIL): "ADMIN"}),
        json.dumps({tip.email_digest(MGR_EMAIL): "USR-TEST-AM-MGR", tip.email_digest(OPM_EMAIL): "USR-TEST-AM-MGR"}),
    ]
    for raw in bad_values:
        with pytest.raises(ValueError):
            tip.parse_identity_map(raw)


def test_h2_mapped_ids_must_be_active_synthetic_accounts() -> None:
    known = tip.known_synthetic_user_ids()
    assert {"USR-TEST-AM-MGR", "USR-TEST-AM-OPM", "USR-TEST-AM-CLERK", "USR-TEST-911", "USR-TEST-912"} <= known
    assert "USR-TEST-AM-RESIGNED" not in known
    tip.build_identity_proxy(PROJECT_AUDIENCE, json.dumps(identity_map()), tip.IapKeyCache(fetcher=FakeFetcher()))
    for uid in ("USR-TEST-AM-RESIGNED", "USR-TEST-NOBODY"):
        with pytest.raises(RuntimeError):
            tip.build_identity_proxy(PROJECT_AUDIENCE, json.dumps({tip.email_digest("x@example.test"): uid}))
    with pytest.raises(RuntimeError):
        tip.build_identity_proxy(LB_AUDIENCE, json.dumps(identity_map()))


def test_h3_digest_is_the_documented_formula() -> None:
    expected = hashlib.sha256(b"r8-uat-iap:owner.tester@example.test").hexdigest()
    assert tip.email_digest(" Owner.Tester@Example.TEST ") == expected


# C — configuration -------------------------------------------------------------------------------

PROXY_ENV = {
    "APP_ENV": "test", "DATA_REPOSITORY": "mock", "DEV_AUTH_MODE": "false", "ACCESS_MANAGEMENT_MODE": "true",
    "MOCK_FIXTURE_PROFILE": "uat_r8", "PM_MASTER_TEST_PROFILE": "true", "TEST_IDENTITY_PROXY": "google_iap",
    "TEST_IAP_AUDIENCE": PROJECT_AUDIENCE, "TEST_IDENTITY_MAP": json.dumps(identity_map()),
}
SENSITIVE_ENV = ("GOOGLE_SHEET_ID", "GOOGLE_APPLICATION_CREDENTIALS", "REGISTRY_DATA_CONTEXT", "TEST_SPA_DIR",
                 "PART_TEST_METER_SOURCE")


def _settings(monkeypatch, **overrides):
    from app.config import Settings

    for name in SENSITIVE_ENV:
        monkeypatch.delenv(name, raising=False)
    env = {**PROXY_ENV, **overrides}
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_c0_the_exact_hosted_profile_is_accepted(monkeypatch) -> None:
    s = _settings(monkeypatch)
    assert s.identity_proxy_enabled and not s.dev_auth_effective and s.registry_context_effective == "TEST"


@pytest.mark.parametrize("override", [
    {"DEV_AUTH_MODE": "true"}, {"APP_ENV": "development"}, {"APP_ENV": "production"}, {"APP_ENV": "local"},
    {"DATA_REPOSITORY": "google_sheets", "ACCESS_MANAGEMENT_MODE": "false", "PM_MASTER_TEST_PROFILE": "false",
     "MOCK_FIXTURE_PROFILE": ""},
    {"ACCESS_MANAGEMENT_MODE": "false", "PM_MASTER_TEST_PROFILE": "false"}, {"MOCK_FIXTURE_PROFILE": ""},
    {"PM_MASTER_TEST_PROFILE": "false"}, {"GOOGLE_SHEET_ID": "sheet"},
    {"GOOGLE_APPLICATION_CREDENTIALS": "/x.json"}, {"REGISTRY_DATA_CONTEXT": "TEST"},
    {"REGISTRY_DATA_CONTEXT": "REAL"}, {"TEST_IAP_AUDIENCE": LB_AUDIENCE}, {"TEST_IAP_AUDIENCE": ""},
    {"TEST_IDENTITY_MAP": ""}, {"TEST_IDENTITY_MAP": json.dumps({MGR_EMAIL: "USR-TEST-AM-MGR"})},
    {"TEST_IDENTITY_PROXY": "header"},
])
def test_c1_every_other_combination_is_refused(monkeypatch, override) -> None:
    with pytest.raises(ValueError):
        _settings(monkeypatch, **override)


@pytest.mark.parametrize("override", [
    {"TEST_IAP_AUDIENCE": PROJECT_AUDIENCE}, {"TEST_IDENTITY_MAP": "{}"}, {"TEST_SPA_DIR": "/app/static"},
])
def test_c1b_proxy_settings_without_the_mode_are_refused(monkeypatch, override) -> None:
    base = {"TEST_IDENTITY_PROXY": None, "TEST_IAP_AUDIENCE": None, "TEST_IDENTITY_MAP": None}
    with pytest.raises(ValueError):
        _settings(monkeypatch, **{**base, **override})


def test_c1c_refused_configuration_never_echoes_setting_values(monkeypatch) -> None:
    secret_map = json.dumps({tip.email_digest(MGR_EMAIL): "USR-TEST-AM-MGR"})
    with pytest.raises(ValueError) as refused:
        _settings(monkeypatch, DEV_AUTH_MODE="true", TEST_IDENTITY_MAP=secret_map)
    text = str(refused.value)
    assert tip.email_digest(MGR_EMAIL)[:12] not in text and "USR-TEST-AM-MGR" not in text


def test_c2_default_settings_keep_the_mode_off(monkeypatch) -> None:
    s = _settings(monkeypatch, TEST_IDENTITY_PROXY=None, TEST_IAP_AUDIENCE=None, TEST_IDENTITY_MAP=None)
    assert not s.identity_proxy_enabled


# Apps -------------------------------------------------------------------------------------------

ANONYMOUS_200_BASELINE = frozenset({
    "/api/v1/access/me", "/api/v1/access/root", "/api/v1/equipment", "/api/v1/findings", "/api/v1/health",
    "/api/v1/inspections", "/api/v1/location-snapshots/by-event/{event_id}",
    "/api/v1/material-requests/by-work-order/{source_work_order_id}", "/api/v1/me", "/api/v1/models",
    "/api/v1/my-work", "/api/v1/part-instances", "/api/v1/parts", "/api/v1/position-lifetime/by-host/{part_instance_id}",
    "/api/v1/readiness", "/api/v1/vehicles",
})


def _build_app(monkeypatch, *, proxy_mode: bool, spa_dir: str | None = None, fetcher: FakeFetcher | None = None):
    from app.config import get_settings
    from app.dependencies import reset_dependency_cache
    from app.main import create_app

    for name in SENSITIVE_ENV:
        monkeypatch.delenv(name, raising=False)
    env = dict(PROXY_ENV)
    if not proxy_mode:
        env.update(TEST_IDENTITY_PROXY="off")
        env.pop("TEST_IAP_AUDIENCE")
        env.pop("TEST_IDENTITY_MAP")
        monkeypatch.delenv("TEST_IAP_AUDIENCE", raising=False)
        monkeypatch.delenv("TEST_IDENTITY_MAP", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    if spa_dir:
        monkeypatch.setenv("TEST_SPA_DIR", spa_dir)
    monkeypatch.setattr(tip, "fetch_iap_public_keys", fetcher or FakeFetcher())
    get_settings.cache_clear()
    reset_dependency_cache()
    return create_app()


@pytest.fixture
def reset_cache():
    yield
    from app.config import get_settings
    from app.dependencies import reset_dependency_cache

    reset_dependency_cache()
    get_settings.cache_clear()


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://testserver")


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "UAT8-X", path)


async def _openapi_paths(monkeypatch) -> dict[str, dict]:
    app = _build_app(monkeypatch, proxy_mode=False)
    return app.openapi()["paths"]


SPOOF = {"X-Dev-User-Id": "USR-TEST-AM-MGR", "X-Dev-Role": "ADMIN",
         "X-Goog-Authenticated-User-Email": f"accounts.google.com:{MGR_EMAIL}",
         "X-Goog-Authenticated-User-Id": "accounts.google.com:1"}


# G — hosting fence and mode isolation -------------------------------------------------------------


async def test_g4_mode_off_anonymous_reads_are_exactly_the_recorded_baseline(monkeypatch, reset_cache) -> None:
    paths = await _openapi_paths(monkeypatch)
    app = _build_app(monkeypatch, proxy_mode=False)
    ok = set()
    async with _client(app) as c:
        for path, ops in paths.items():
            if "get" in ops and (await c.get(_concrete(path), headers=SPOOF)).status_code == 200:
                ok.add(path)
        assert (await c.get("/openapi.json")).status_code == 200  # unchanged default
    assert ok == ANONYMOUS_200_BASELINE


async def test_g1_proxy_mode_refuses_every_api_request_without_a_verified_identity(monkeypatch, reset_cache) -> None:
    paths = await _openapi_paths(monkeypatch)
    app = _build_app(monkeypatch, proxy_mode=True)
    forged = [None, "", mint(private=OTHER_PRIVATE), mint(aud=LB_AUDIENCE), mint(iss="https://evil.example"),
              mint(UNMAPPED_EMAIL)]
    async with _client(app) as c:
        for path, ops in paths.items():
            for method in ops:
                headers = dict(SPOOF)
                token = forged[hash(path + method) % len(forged)]
                if token is not None:
                    headers[tip.IAP_ASSERTION_HEADER] = token
                r = await c.request(method.upper(), _concrete(path), headers=headers, json={})
                if (method, path) == ("get", "/api/v1/health"):
                    assert r.status_code == 200
                    continue
                assert r.status_code == 401, (method, path, r.status_code)
                assert r.json()["error"]["code"] == "IAP_IDENTITY_REQUIRED"
                assert r.headers["X-Request-Id"] == r.json()["error"]["request_id"]
        for token in forged:
            headers = {**SPOOF, **({tip.IAP_ASSERTION_HEADER: token} if token else {})}
            assert (await c.get(f"{API}/vehicles", headers=headers)).status_code == 401
        assert (await c.get(f"{API}/no-such-route")).status_code == 401
        assert (await c.get("/api")).status_code == 401


async def test_g1b_x_dev_and_unsigned_headers_never_change_a_verified_identity(monkeypatch, reset_cache) -> None:
    app = _build_app(monkeypatch, proxy_mode=True)
    async with _client(app) as c:
        me = await c.get(f"{API}/me", headers={**SPOOF, "X-Dev-User-Id": "USR-TEST-AM-OPM",
                                               tip.IAP_ASSERTION_HEADER: mint(CLERK_EMAIL)})
        assert me.status_code == 200
        assert me.json()["user_id"] == "USR-TEST-AM-CLERK" and me.json()["roles"] == []


async def test_g1c_context_outside_api_ignores_dev_and_unsigned_headers(monkeypatch, reset_cache) -> None:
    """The /api fence answers 401 first, so the context's own header isolation is probed on a non-/api
    route added only in this test."""
    from app.context import get_request_context

    app = _build_app(monkeypatch, proxy_mode=True)

    async def probe(request: Request) -> dict:
        context = get_request_context(request)
        return {"user_id": context.user_id, "roles": list(context.roles), "dev": context.is_dev_auth}

    app.add_api_route("/probe-context", probe, methods=["GET"])
    async with _client(app) as c:
        assert (await c.get("/probe-context", headers=SPOOF)).json() == {"user_id": None, "roles": [], "dev": False}
        mapped = await c.get("/probe-context", headers={**SPOOF, tip.IAP_ASSERTION_HEADER: mint(OPM_EMAIL)})
        assert mapped.json() == {"user_id": "USR-TEST-AM-OPM", "roles": [], "dev": False}


async def test_g1d_fence_judges_the_routed_path_even_with_a_root_path(monkeypatch, reset_cache) -> None:
    """A server started with --root-path must not let `/prefix/api/...` past the fence."""
    app = _build_app(monkeypatch, proxy_mode=True)
    for path in ("/x/api/v1/equipment", "/x/api/v1/readiness", "/x/api/v1/me"):
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
                 "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "/x", "query_string": b"",
                 "headers": [(b"host", b"testserver")], "client": ("127.0.0.1", 1), "server": ("testserver", 80)}
        await app(scope, receive, send)
        assert sent[0]["status"] == 401, path


async def test_g2_api_docs_are_not_served_in_proxy_mode(monkeypatch, reset_cache) -> None:
    app = _build_app(monkeypatch, proxy_mode=True)
    async with _client(app) as c:
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            assert (await c.get(path, headers={tip.IAP_ASSERTION_HEADER: mint()})).status_code == 404


async def test_g3_no_roles_so_no_technical_recovery(monkeypatch, reset_cache) -> None:
    app = _build_app(monkeypatch, proxy_mode=True)
    async with _client(app) as c:
        me = await c.get(f"{API}/access/me", headers={tip.IAP_ASSERTION_HEADER: mint(CLERK_EMAIL), **SPOOF})
        assert me.json()["recovery"] is False and me.json()["personnel_id"] == "PER-TEST-AM-CLERK"
        refused = await c.post(f"{API}/access/root/appointment",
                               headers={tip.IAP_ASSERTION_HEADER: mint(CLERK_EMAIL), "X-Request-Id": str(uuid.uuid4()),
                                        **SPOOF},
                               json={"personnel_id": "PER-TEST-AM-CLERK", "reason_th": "x",
                                     "expected_revision": me.json()["revision"]})
        assert refused.status_code == 403


async def test_g5_health_is_open_but_carries_no_data(monkeypatch, reset_cache) -> None:
    app = _build_app(monkeypatch, proxy_mode=True)
    async with _client(app) as c:
        r = await c.get(f"{API}/health")
        assert r.status_code == 200 and set(r.json()) == {"status", "app_env"}
        assert (await c.post(f"{API}/health")).status_code == 401
        assert (await c.head(f"{API}/health")).status_code == 401  # only GET is open


# B — business with a verified identity -------------------------------------------------------------


async def test_b1_b2_grants_come_only_from_access_management(monkeypatch, reset_cache) -> None:
    app = _build_app(monkeypatch, proxy_mode=True)

    def h(email: str) -> dict:
        return {tip.IAP_ASSERTION_HEADER: mint(email), "X-Request-Id": str(uuid.uuid4())}

    async with _client(app) as c:
        mgr = (await c.get(f"{API}/access/me", headers=h(MGR_EMAIL))).json()
        assert mgr["personnel_id"] == "PER-TEST-AM-MGR" and mgr["is_root"] is True
        assert (await c.get(f"{API}/me", headers=h(CLERK_EMAIL))).json()["capabilities"] == []
        assert (await c.get(f"{API}/vehicles", headers=h(CLERK_EMAIL))).status_code == 200
        body = {"asset_type": "VEHICLE", "asset_id": "UAT8-VEH-01", "source_type": "MANUAL"}
        assert (await c.post(f"{API}/repairs", headers=h(CLERK_EMAIL), json=body)).status_code == 403

        async def grant(changes: dict) -> int:
            revision = (await c.get(f"{API}/access/me", headers=h(MGR_EMAIL))).json()["revision"]
            r = await c.post(f"{API}/access/grants", headers=h(MGR_EMAIL), json={
                "target": {"kind": "EMPLOYEE", "personnel_id": "PER-TEST-AM-CLERK"}, "changes": changes,
                "reason_th": "UAT", "expected_revision": revision})
            return r.status_code

        assert await grant({"can_view": True}) == 200
        assert "can_view" in (await c.get(f"{API}/me", headers=h(CLERK_EMAIL))).json()["capabilities"]
        assert await grant({"can_view": False}) == 200
        assert (await c.get(f"{API}/me", headers=h(CLERK_EMAIL))).json()["capabilities"] == []
        # the reader cannot grant
        r = await c.post(f"{API}/access/grants", headers=h(CLERK_EMAIL), json={
            "target": {"kind": "EMPLOYEE", "personnel_id": "PER-TEST-AM-CLERK"}, "changes": {"can_view": True},
            "reason_th": "x", "expected_revision": mgr["revision"]})
        assert r.status_code == 403


async def test_b3_unmapped_signed_in_account_is_anonymous_and_refused(monkeypatch, reset_cache) -> None:
    app = _build_app(monkeypatch, proxy_mode=True)
    async with _client(app) as c:
        r = await c.get(f"{API}/me", headers={tip.IAP_ASSERTION_HEADER: mint(UNMAPPED_EMAIL)})
        assert r.status_code == 401 and r.json()["error"]["code"] == "IAP_IDENTITY_REQUIRED"


async def test_b4_key_outage_fails_every_api_request_closed(monkeypatch, reset_cache) -> None:
    fetcher = FakeFetcher()
    fetcher.fail = True
    app = _build_app(monkeypatch, proxy_mode=True, fetcher=fetcher)
    async with _client(app) as c:
        assert (await c.get(f"{API}/me", headers={tip.IAP_ASSERTION_HEADER: mint()})).status_code == 401


# S — same-origin SPA -------------------------------------------------------------------------------


@pytest.fixture
def spa_dir(tmp_path):
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>R8 TEST</title>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log('r8')", encoding="utf-8")
    (root / "assets" / "app.css").write_text("body{}", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    return root


async def test_s1_assets_and_client_routes(monkeypatch, reset_cache, spa_dir) -> None:
    app = _build_app(monkeypatch, proxy_mode=True, spa_dir=str(spa_dir))
    async with _client(app) as c:
        js = await c.get("/assets/app.js")
        assert js.status_code == 200 and "javascript" in js.headers["content-type"]
        assert "text/css" in (await c.get("/assets/app.css")).headers["content-type"]
        for route in ("/", "/repairs/RPR-1", "/access-management", "/assets/missing.js"):
            r = await c.get(route)
            assert r.status_code == 200 and "R8 TEST" in r.text and r.headers["cache-control"] == "no-cache"
        assert (await c.head("/")).status_code == 200


async def test_s2_traversal_and_directory_listing_are_refused(monkeypatch, reset_cache, spa_dir) -> None:
    app = _build_app(monkeypatch, proxy_mode=True, spa_dir=str(spa_dir))
    responses = []
    for raw in (b"/../secret.txt", b"/assets/../../secret.txt", b"/%2e%2e/secret.txt", b"/..%2fsecret.txt"):
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        from urllib.parse import unquote

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
                 "scheme": "http", "path": unquote(raw.decode()), "raw_path": raw, "query_string": b"",
                 "root_path": "", "headers": [(b"host", b"testserver")], "client": ("127.0.0.1", 1),
                 "server": ("testserver", 80)}
        await app(scope, receive, send)
        body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        responses.append((sent[0]["status"], body))
    for status_code, body in responses:
        assert b"outside" not in body
        assert status_code in (200, 404)
    async with _client(app) as c:
        r = await c.get("/assets/")
        assert "R8 TEST" in r.text  # a directory gets the SPA index, never a listing


async def test_s3_api_status_semantics_are_unchanged(monkeypatch, reset_cache, spa_dir) -> None:
    app = _build_app(monkeypatch, proxy_mode=True, spa_dir=str(spa_dir))
    h = {tip.IAP_ASSERTION_HEADER: mint()}
    async with _client(app) as c:
        nope = await c.get(f"{API}/no-such-route", headers=h)
        assert nope.status_code == 404 and nope.json()["error"]["code"] == "NOT_FOUND"
        assert nope.headers["content-type"].startswith("application/json")
        assert (await c.post(f"{API}/no-such-route", headers=h, json={})).status_code == 404
        assert (await c.delete(f"{API}/vehicles", headers=h)).status_code == 405
        assert (await c.post("/repairs/RPR-1", json={})).status_code == 404
        assert (await c.get(f"{API}/vehicles", headers=h)).headers["content-type"].startswith("application/json")


async def test_s4_spa_is_never_served_when_the_mode_is_off(monkeypatch, reset_cache, spa_dir) -> None:
    with pytest.raises(ValueError):
        _settings(monkeypatch, TEST_IDENTITY_PROXY="off", TEST_IAP_AUDIENCE=None, TEST_IDENTITY_MAP=None,
                  TEST_SPA_DIR=str(spa_dir))
    app = _build_app(monkeypatch, proxy_mode=False)
    async with _client(app) as c:
        assert (await c.get("/")).status_code == 404
        assert (await c.get("/repairs/RPR-1")).status_code == 404


async def test_s6_disabled_docs_paths_fall_back_to_the_spa_index_without_any_schema(monkeypatch, reset_cache,
                                                                                    spa_dir) -> None:
    app = _build_app(monkeypatch, proxy_mode=True, spa_dir=str(spa_dir))
    async with _client(app) as c:
        for path in ("/docs", "/redoc", "/openapi.json"):
            r = await c.get(path, headers={tip.IAP_ASSERTION_HEADER: mint()})
            assert "R8 TEST" in r.text and r.headers["content-type"].startswith("text/html")
            assert not any(word in r.text.lower() for word in ("swagger", "redoc", '"openapi"', '"paths"'))


async def test_s5_missing_index_refuses_to_start(monkeypatch, reset_cache, tmp_path) -> None:
    with pytest.raises(RuntimeError):
        _build_app(monkeypatch, proxy_mode=True, spa_dir=str(tmp_path))


async def test_c3_bad_map_target_refuses_to_start(monkeypatch, reset_cache) -> None:
    monkeypatch.setitem(PROXY_ENV, "TEST_IDENTITY_MAP", json.dumps({tip.email_digest(MGR_EMAIL): "USR-TEST-AM-RESIGNED"}))
    with pytest.raises(RuntimeError):
        _build_app(monkeypatch, proxy_mode=True)
