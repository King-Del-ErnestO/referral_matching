"""Claim handling: an agent accepts an offer and takes ownership of the referral."""

from django.db import transaction
from django.utils import timezone

from . import notifications
from .events import record_event
from .models import Agent, Claim, Offer, Referral, ReferralEvent


class ClaimError(Exception):
    def __init__(self, message, code="claim_failed"):
        super().__init__(message)
        self.code = code


def claim_offer(offer, agent):
    """Accept an offer on behalf of the agent and assign the referral."""
    referral = Referral.objects.select_for_update().get(pk=offer.referral_id)
    offer = Offer.objects.select_for_update().get(pk=offer.pk)
    agent = Agent.objects.select_for_update().get(pk=agent.pk)

    record_event(
        referral,
        ReferralEvent.Type.CLAIM_ATTEMPTED,
        actor=agent.name,
        payload={"offer_id": offer.id},
    )

    if offer.status != Offer.Status.PENDING:
        raise ClaimError("This offer is no longer open.", code="offer_not_open")
    if offer.expires_at < timezone.now():
        raise ClaimError("This offer has expired.", code="offer_expired")
    if referral.status == Referral.Status.ASSIGNED:
        raise ClaimError("This referral has already been claimed.", code="already_claimed")
    if Claim.objects.filter(referral=referral, active=True).exists():
        raise ClaimError("This referral has already been claimed.", code="already_claimed")

    try:
        with transaction.atomic():
            referral = Referral.objects.select_for_update().get(pk=referral.pk)
            offer = Offer.objects.select_for_update().get(pk=offer.pk)
            agent = Agent.objects.select_for_update().get(pk=agent.pk)

            if offer.status != Offer.Status.PENDING:
                raise ClaimError("This offer is no longer open.", code="offer_not_open")
            if offer.expires_at < timezone.now():
                raise ClaimError("This offer has expired.", code="offer_expired")
            if referral.status == Referral.Status.ASSIGNED:
                raise ClaimError("This referral has already been claimed.", code="already_claimed")
            if Claim.objects.filter(referral=referral, active=True).exists():
                raise ClaimError("This referral has already been claimed.", code="already_claimed")

            claim = Claim.objects.create(referral=referral, agent=agent)
            referral.status = Referral.Status.ASSIGNED
            referral.assigned_agent = agent
            referral.save(update_fields=["status", "assigned_agent"])

            offer.status = Offer.Status.ACCEPTED
            offer.responded_at = timezone.now()
            offer.save(update_fields=["status", "responded_at"])

            agent.active_referral_count += 1
            agent.save(update_fields=["active_referral_count"])

            notifications.send_claim_confirmation(claim)
    except notifications.NotificationError as exc:
        record_event(
            referral,
            ReferralEvent.Type.CLAIM_CONFLICTED,
            actor=agent.name,
            payload={"offer_id": offer.id, "error": str(exc), "reason": "notification_failed"},
        )
        raise ClaimError(f"The claim could not be completed: {exc}", code="notification_failed") from exc

    record_event(
        referral,
        ReferralEvent.Type.CLAIM_SUCCEEDED,
        actor=agent.name,
        payload={"offer_id": offer.id, "claim_id": claim.id},
    )

    return claim


def decline_offer(offer, agent):
    """Record that the agent passed on the offer and continue the queue."""
    if offer.status != Offer.Status.PENDING:
        raise ClaimError("This offer is no longer open.", code="offer_not_open")

    offer.status = Offer.Status.DECLINED
    offer.responded_at = timezone.now()
    offer.save(update_fields=["status", "responded_at"])

    record_event(
        offer.referral,
        ReferralEvent.Type.OFFER_DECLINED,
        actor=agent.name,
        payload={"offer_id": offer.id},
    )

    from .matching import build_offers

    build_offers(offer.referral)
    return offer
