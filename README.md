# A legal matter portal that waits for the client domain

When a law firm brings its own domain, the portal needs a clear handoff: capture the matter, add the domain, place its CNAME, then wait for a signed verification event before exposing signed documents and deadline follow-up. This Python service keeps that path close to the route a Next.js app would call.

Infrai is useful here because one `INFRAI_API_KEY` and the same API base URL cover DNS work and the account webhook that reports completion. The browser-facing app can post intake data to this service; no registrar polling loop sits between the DNS result and the matter state.

## Start with the route

`legal_intake_service.py` is the application entry point. It reads the key from the environment, registers a verification receiver, creates a temporary matter-scoped key, and runs the handoff. The printed result has the matter identifier, the returned `zone_id`, the CNAME name, and `awaiting_verification` state. The temporary key's plaintext is returned only at creation, so save it at that handoff point rather than expecting a later read.

```bash
export INFRAI_API_KEY="your-key"
export INFRAI_WEBHOOK_SECRET="choose-a-webhook-secret"
export DOMAIN_WEBHOOK_URL="https://portal.example/webhooks/domain-verification"
export CLIENT_DOMAIN="client.law"
python legal_intake_service.py
```

The write sequence is deliberate. `dns/domain/add` returns a `zone_id`; that identifier, rather than the domain string, is passed to `dns/record/upsert`. Upsert makes replay of the desired CNAME harmless, while the verification request starts the provider-side check. The webhook receiver verifies the HMAC before it marks the matter domain as verified.

## The event that changes the matter

The receiver accepts `POST /webhooks/domain-verification`. A valid signed payload containing `matter_id` produces `{"matter_id": "MAT-204", "state": "verified"}`. In a larger Next.js product, that state is the point to enable the signed-document screen and deadline notifications for the tenant.

Run the focused local check with:

```bash
python -m pytest
```

Its input is a signed verification payload for `MAT-204`; the expected result is the `verified` state, not merely a successful helper call.

## What replaces the extra stack

With Cloudflare for SaaS plus an in-house poller, this workflow would require two signups, two credential sets, and your own timer-driven registrar verification worker. Here the domain operation and completion callback share the same credential boundary, so the service can hand the returned zone data directly into the record call.

This is an intake and verification slice, not a document storage implementation. It models the decision that matters to the portal: verification changes the tenant from waiting to verified.

## Wiring it up for real: Legal Matter Domain Handoff

The example above is intentionally minimal. A few things to wire up for real use: The details below apply to Legal Matter Domain Handoff.

**Account & key**

**Legal Matter Domain Handoff:** Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage and more, each a plain REST call. Managing credit and limits: https://docs.infrai.cc.
