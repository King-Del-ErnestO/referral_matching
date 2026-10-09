"""Candidate scoring and offer generation for incoming referrals."""

from datetime import timedelta

from django.utils import timezone

from . import eligibility
from .events import record_event
from .models import Agent, Offer, Referral, ReferralEvent

OFFER_TTL_MINUTES = 10
MAX_OFFERS_PER_REFERRAL = 3

# Weights tuned during the Q2 spike; see notebook in the pilot planning doc.
WEIGHT_GEO = 0.30
WEIGHT_PRICE = 0.20
WEIGHT_PERFORMANCE = 0.30
WEIGHT_CAPACITY = 0.20
ELIGIBILITY_PENALTY = 0.10


def score_agent(agent, referral):
    """Score an agent for a referral. Higher is better."""
    explanation = {}

    geo = 0.0
    if referral.state in (agent.licensed_states or []):
        geo += 0.5
    if any(referral.postal_code.startswith(p) for p in (agent.service_area_zip_prefixes or [])):
        geo += 0.5
    explanation["geo_fit"] = round(geo, 3)

    span = max(agent.maximum_price - agent.minimum_price, 1)
    midpoint = agent.minimum_price + span / 2
    price = max(0.0, 1.0 - abs(referral.estimated_price - midpoint) / max(midpoint, 1))
    explanation["price_fit"] = round(price, 3)

    performance = agent.performance_score if agent.performance_score is not None else 1.0
    explanation["performance"] = round(performance, 3)

    capacity_headroom = max(agent.capacity - agent.active_referral_count, 0)
    capacity = min(capacity_headroom / max(agent.capacity, 1), 1.0)
    explanation["capacity"] = round(capacity, 3)

    score = (
        WEIGHT_GEO * geo
        + WEIGHT_PRICE * price
        + WEIGHT_PERFORMANCE * performance
        + WEIGHT_CAPACITY * capacity
    )

    snapshot = eligibility.evaluate(agent, referral)
    penalty = ELIGIBILITY_PENALTY * len(snapshot["reasons"])
    score -= penalty
    explanation["eligibility_penalty"] = round(-penalty, 3)
    explanation["total"] = round(score, 3)

    return score, explanation, snapshot


def build_offers(referral):
    """Rank eligible agents for a referral and create offers for the top candidates."""
    if referral.status in {Referral.Status.ASSIGNED, Referral.Status.CLOSED}:
        return []

    now = timezone.now()
    offered_agent_ids = set(
        Offer.objects.filter(referral=referral).values_list("agent_id", flat=True)
    )
    candidates = []
    for agent in Agent.objects.filter(active=True).exclude(pk__in=offered_agent_ids):
        score, explanation, snapshot = score_agent(agent, referral)
        if not snapshot["eligible"]:
            continue
        candidates.append((score, agent, explanation, snapshot))

    candidates.sort(key=lambda item: item[0], reverse=True)

    record_event(
        referral,
        ReferralEvent.Type.CANDIDATES_GENERATED,
        actor="matching",
        payload={"considered": len(candidates)},
    )

    offers = []
    for score, agent, explanation, snapshot in candidates[:MAX_OFFERS_PER_REFERRAL]:
        offer = Offer.objects.create(
            referral=referral,
            agent=agent,
            score=score,
            score_explanation=explanation,
            eligibility_snapshot=snapshot,
            expires_at=now + timedelta(minutes=OFFER_TTL_MINUTES),
        )
        offers.append(offer)
        record_event(
            referral,
            ReferralEvent.Type.OFFER_SENT,
            actor="matching",
            payload={"agent_id": agent.id, "score": round(score, 3)},
        )

    if offers:
        referral.status = Referral.Status.OFFERED
        referral.save(update_fields=["status"])
    return offers
