import pytest
from rest_framework.test import APIClient

from referrals import webhooks
from referrals.models import Offer, Referral, ReferralEvent

pytestmark = pytest.mark.django_db

PAYLOAD = {
    "event_id": "evt-abc-123",
    "external_id": "lead-90001",
    "customer_name": "Jordan Sample",
    "customer_email": "jordan.sample@example.com",
    "customer_phone": "555-0101",
    "state": "CO",
    "postal_code": "80202",
    "estimated_price": 450_000,
    "intent_level": "hot",
}


def post_webhook(payload, token="dev-webhook-secret"):
    client = APIClient()
    return client.post(
        "/api/webhooks/referrals/", payload, format="json", headers={"X-Webhook-Token": token}
    )


def test_webhook_requires_token(db):
    response = post_webhook(PAYLOAD, token="wrong")
    assert response.status_code == 403
    assert Referral.objects.count() == 0


def test_webhook_rejects_incomplete_payload(db):
    response = post_webhook({"event_id": "evt-1"})
    assert response.status_code == 400
    assert "external_id" in response.data["fields"]


def test_webhook_creates_referral_and_offers(make_agent):
    make_agent("agent.one", performance_score=0.9)
    make_agent("agent.two", performance_score=0.6)

    response = post_webhook(dict(PAYLOAD, event_id="evt-create-1"))
    assert response.status_code == 201

    referral = Referral.objects.get(external_id="lead-90001")
    assert referral.status == Referral.Status.OFFERED
    assert referral.customer_name == "Jordan Sample"
    assert Offer.objects.filter(referral=referral).count() > 0
    event_types = set(referral.events.values_list("event_type", flat=True))
    assert ReferralEvent.Type.REFERRAL_RECEIVED in event_types
    assert ReferralEvent.Type.OFFER_SENT in event_types


def test_webhook_deduplicates_persisted_event_id(make_agent):
    make_agent("agent.one", performance_score=0.9)
    make_agent("agent.two", performance_score=0.6)

    first = post_webhook(dict(PAYLOAD, event_id="evt-duplicate-1"))
    assert first.status_code == 201

    webhooks._PROCESSED_EVENT_IDS.clear()

    second = post_webhook(dict(PAYLOAD, event_id="evt-duplicate-1"))
    assert second.status_code == 200
    assert second.data["status"] == "duplicate_ignored"
    assert Referral.objects.filter(external_id="lead-90001").count() == 1
