import hashlib
import hmac
import json
from unittest.mock import MagicMock

import legal_intake_service
from legal_intake_service import apply_verification_event


def test_verified_domain_event_unlocks_the_matter_portal() -> None:
    secret = "test-secret"
    body = json.dumps({"matter_id": "MAT-204", "domain": "client.law"}).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert apply_verification_event(secret, body, signature) == {"matter_id": "MAT-204", "state": "verified"}


def test_entry_point_uses_supported_handoff_calls(monkeypatch, capsys) -> None:
    monkeypatch.setenv("INFRAI_API_KEY", "test-key")
    monkeypatch.setenv("DOMAIN_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setenv("INFRAI_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("CLIENT_DOMAIN", "client.law")
    client = MagicMock()
    client.add_domain.return_value = {"zone_id": "zone-1"}
    monkeypatch.setattr(legal_intake_service, "InfraiClient", lambda key: client)

    legal_intake_service.main()

    assert [call[0] for call in client.method_calls] == [
        "register_webhook", "create_temporary_key", "add_domain", "upsert_cname", "verify_domain",
    ]
    assert json.loads(capsys.readouterr().out)["zone_id"] == "zone-1"
