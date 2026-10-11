from rest_framework import serializers
from django.conf import settings
from .models import Subscription, SubscriptionPayment


class SubscriptionSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True)
    effective_end_date = serializers.DateTimeField(read_only=True)
    artist_brand_name = serializers.CharField(source="artist.brand_name", read_only=True)
    artist_username = serializers.CharField(source="artist.user.username", read_only=True)
    artist_phone = serializers.CharField(source="artist.user.phone_number", read_only=True)
    artist_region = serializers.CharField(source="artist.region", read_only=True)
    artist_mobile_money_number = serializers.CharField(source="artist.mobile_money_number", read_only=True)
    artist_mobile_money_provider = serializers.CharField(source="artist.mobile_money_provider", read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id", "artist", "artist_brand_name", "status", "trial_start_date", "trial_end_date",
            "current_period_end", "monthly_price_xaf", "is_active", "effective_end_date",
            "artist_username", "artist_phone", "artist_region", "artist_mobile_money_number",
            "artist_mobile_money_provider",
        ]
        read_only_fields = ["id", "artist", "trial_start_date"]


class SubscriptionPlanSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    duration_months = serializers.IntegerField()
    price_xaf = serializers.IntegerField()


class StartSubscriptionPaymentSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField(default=1, min_value=1)
    amount_xaf = serializers.IntegerField(required=False, min_value=1, max_value=22)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=False)
    method = serializers.ChoiceField(choices=["orange", "mtn"], required=False)

    def validate_plan_id(self, value):
        if not any(plan["id"] == value for plan in settings.SUBSCRIPTION_PLANS):
            raise serializers.ValidationError("Unknown subscription plan.")
        return value


class SubscriptionPaymentSerializer(serializers.ModelSerializer):
    duration_months = serializers.IntegerField(read_only=True)

    class Meta:
        model = SubscriptionPayment
        fields = ["id", "external_reference", "campay_reference", "amount_xaf", "duration_months", "status", "created_at"]
        read_only_fields = fields


class AdminSubscriptionStatsSerializer(serializers.Serializer):
    plans = SubscriptionPlanSerializer(many=True)
    total_artists = serializers.IntegerField()
    trial_count = serializers.IntegerField()
    active_count = serializers.IntegerField()
    expired_count = serializers.IntegerField()
    cancelled_count = serializers.IntegerField()
