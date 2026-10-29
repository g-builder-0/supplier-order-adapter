"""
Webhook dispatcher: signs an outbound event payload with HMAC-SHA256 and
POSTs it to a subscriber, so the subscriber can verify the delivery
actually came from this service and wasn't altered in transit.

Deliberately minimal for now: one hardcoded subscriber URL
(WEBHOOK_SUBSCRIBER_URL in settings), no subscriber-registration model,
no delivery-audit table, no retry logic. The thing worth proving at this
stage is that the signature and payload shape are correct and
independently verifiable by a receiver -- not the registration UX,
which is a later addition.
"""

import hashlib
import hmac
import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def generate_signature(payload: dict, secret: str) -> str:
    """
    HMAC-SHA256 over the payload, serialized with sort_keys=True.

    sort_keys=True is load-bearing, not cosmetic: HMAC signs bytes, and
    dict key order in Python is insertion order, not a stable property
    of the data. A receiver that re-serializes the same payload dict
    without sort_keys=True would get different bytes and compute a
    different signature even though nothing about the actual data
    changed. Both sides of the boundary have to agree on this
    canonicalization rule for the signature to mean anything.
    """
    message = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def dispatch_event(event_type: str, data: dict) -> None:
    """
    Sign and POST one event to the hardcoded subscriber URL.

    Call this AFTER the triggering transaction.atomic() block has
    committed, not from inside it — this makes a real network request,
    and holding a DB transaction open for the duration of an outbound
    HTTP call ties a lock's lifetime to a dependency this process
    doesn't control.

    If WEBHOOK_SUBSCRIBER_URL isn't configured, logs and returns rather
    than raising — a missing subscriber shouldn't break the receiving
    flow that triggered this event.
    """
    if not settings.WEBHOOK_SUBSCRIBER_URL:
        logger.info("WEBHOOK_SUBSCRIBER_URL not configured; skipping %s", event_type)
        return

    body = {"event_type": event_type, "data": data}
    signature = generate_signature(body, settings.WEBHOOK_SECRET)

    try:
        response = requests.post(
            settings.WEBHOOK_SUBSCRIBER_URL,
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
                "X-Webhook-Event": event_type,
            },
            timeout=5,
        )
        logger.info(
            "webhook %s -> %s (%s)",
            event_type, settings.WEBHOOK_SUBSCRIBER_URL, response.status_code,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("webhook %s delivery to %s failed: %s", event_type, settings.WEBHOOK_SUBSCRIBER_URL, exc)
