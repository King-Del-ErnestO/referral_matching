from rest_framework import serializers

from .models import Agent, Claim, Offer, Referral, ReferralEvent


class AgentSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Agent
        fields = ["id", "name", "email", "performance_score", "active_referral_count", "capacity"]


class ReferralSerializer(serializers.ModelSerializer):
    assigned_agent = AgentSummarySerializer(read_only=True)

    class Meta:
        model = Referral
        fields = [
            "id",
            "external_id",
            "customer_name",
            "customer_email",
            "customer_phone",
            "state",
            "postal_code",
            "estimated_price",
            "intent_level",
            "status",
            "assigned_agent",
            "created_at",
        ]


class OfferSerializer(serializers.ModelSerializer):
    referral = ReferralSerializer(read_only=True)

    class Meta:
        model = Offer
        fields = [
            "id",
            "referral",
            "score",
            "score_explanation",
            "eligibility_snapshot",
            "status",
            "offered_at",
            "expires_at",
            "responded_at",
        ]


class ReferralEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferralEvent
        fields = ["id", "event_type", "actor", "payload", "created_at"]


class ClaimSerializer(serializers.ModelSerializer):
    agent = AgentSummarySerializer(read_only=True)

    class Meta:
        model = Claim
        fields = ["id", "agent", "active", "created_at", "released_at"]


class OpsReferralSerializer(serializers.ModelSerializer):
    assigned_agent = serializers.SerializerMethodField()
    offers = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()
    age_minutes = serializers.SerializerMethodField()

    class Meta:
        model = Referral
        fields = [
            "id",
            "external_id",
            "customer_name",
            "state",
            "postal_code",
            "estimated_price",
            "intent_level",
            "status",
            "assigned_agent",
            "age_minutes",
            "offers",
            "events",
            "created_at",
        ]

    def get_assigned_agent(self, obj):
        if obj.assigned_agent_id is None:
            return None
        agent = obj.assigned_agent
        return {"id": agent.id, "name": agent.name, "email": agent.email}

    def get_offers(self, obj):
        offers = list(obj.offers.all().order_by("-offered_at"))
        return [
            {
                "id": offer.id,
                "agent": offer.agent.name,
                "score": offer.score,
                "status": offer.status,
                "offered_at": offer.offered_at,
                "expires_at": offer.expires_at,
            }
            for offer in offers
        ]

    def get_events(self, obj):
        return ReferralEventSerializer(list(obj.events.all()), many=True).data

    def get_age_minutes(self, obj):
        from django.utils import timezone

        return int((timezone.now() - obj.created_at).total_seconds() // 60)
