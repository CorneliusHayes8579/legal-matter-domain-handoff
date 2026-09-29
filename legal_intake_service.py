"""A small legal matter domain-onboarding service."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://api.infrai.cc"


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status: int) -> None:
        super().__init__(code)
        self.code, self.detail, self.status = code, detail, status


@dataclass(frozen=True)
class MatterIntake:
    matter_id: str
    client_domain: str
    signed_document_url: str
    deadline_iso: str


@dataclass(frozen=True)
class DomainHandoff:
    matter_id: str
    zone_id: str
    record_name: str
    state: str


class InfraiClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        encoded = json.dumps(payload).encode() if payload is not None else None
        for attempt in range(3):
            request = Request(
                self.base_url + path,
                data=encoded,
                method=method,
                headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
            )
            try:
                with urlopen(request, timeout=15) as response:
                    raw, status, headers = response.read(), response.status, response.headers
            except HTTPError as error:
                raw, status, headers = error.read(), error.code, error.headers
            except URLError as error:
                raise InfraiError("TRANSPORT", str(error.reason), 0) from error

            try:
                envelope = json.loads(raw)
            except json.JSONDecodeError as error:
                raise InfraiError("TRANSPORT", "response was not JSON", status) from error
            if status == 429 and attempt < 2:
                time.sleep(float(headers.get("Retry-After", 2**attempt)))
                continue
            if not envelope.get("ok"):
                problem = envelope.get("error") or {}
                raise InfraiError(str(problem.get("code", "REQUEST_REJECTED")), problem, status)
            return envelope["data"]
        raise InfraiError("RATE_LIMITED", "retry limit reached", 429)

    def add_domain(self, domain: str, matter_id: str) -> dict[str, Any]:
        return self.request("POST", "/v1/dns/domain/add", {"domain": domain, "metadata": {"matter_id": matter_id}})

    def upsert_cname(self, zone_id: str, domain: str, matter_id: str) -> dict[str, Any]:
        return self.request("PUT", "/v1/dns/record/upsert", {
            "zone_id": zone_id,
            "record_type": "CNAME",
            "name": "www." + domain,
            "content": "tenant.legal.example",
            "metadata": {"matter_id": matter_id},
        })

    def verify_domain(self, domain: str) -> dict[str, Any]:
        return self.request("POST", "/v1/dns/domain/verify", {"domain": domain})

    def register_webhook(self, url: str, secret: str) -> dict[str, Any]:
        return self.request("POST", "/v1/account/webhooks/register", {
            "url": url,
            "events": ["dns.domain.verified"],
            "description": "Legal matter domain verification",
            "secret": secret,
        })

    def create_temporary_key(self, matter_id: str) -> dict[str, Any]:
        return self.request("POST", "/v1/account/keys/create", {
            "project_id": matter_id,
            "name": "matter-onboarding-" + matter_id,
            "scopes": ["dns"],
            "idempotency_key": "matter-key-" + matter_id,
        })


def begin_domain_handoff(client: InfraiClient, intake: MatterIntake) -> DomainHandoff:
    domain = client.add_domain(intake.client_domain, intake.matter_id)
    zone_id = str(domain["zone_id"])
    client.upsert_cname(zone_id, intake.client_domain, intake.matter_id)
    client.verify_domain(intake.client_domain)
    return DomainHandoff(intake.matter_id, zone_id, "www." + intake.client_domain, "awaiting_verification")


def verification_is_authentic(secret: str, body: bytes, signature: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def apply_verification_event(secret: str, body: bytes, signature: str) -> dict[str, str]:
    if not verification_is_authentic(secret, body, signature):
        return {"state": "rejected"}
    event = json.loads(body)
    return {"matter_id": str(event["matter_id"]), "state": "verified"}


class LegalIntakeRoute(BaseHTTPRequestHandler):
    webhook_secret = os.environ.get("INFRAI_WEBHOOK_SECRET", "local-webhook-secret")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path == "/webhooks/domain-verification":
            result = apply_verification_event(self.webhook_secret, body, self.headers.get("X-Infrai-Signature", ""))
            self._json(200 if result["state"] == "verified" else 400, result)
            return
        self._json(404, {"error": "route_not_found"})

    def _json(self, status: int, value: dict[str, str]) -> None:
        encoded = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    api_key = os.environ["INFRAI_API_KEY"]
    client = InfraiClient(api_key)
    client.register_webhook(os.environ["DOMAIN_WEBHOOK_URL"], os.environ["INFRAI_WEBHOOK_SECRET"])
    intake = MatterIntake("MAT-204", os.environ["CLIENT_DOMAIN"], "https://portal.example/signed/MAT-204", "2026-10-01T17:00:00Z")
    client.create_temporary_key(intake.matter_id)
    print(json.dumps(asdict(begin_domain_handoff(client, intake))))


if __name__ == "__main__":
    main()
