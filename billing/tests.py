from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import ArtistProfile, User
from .models import Subscription, SubscriptionPayment
from .views import apply_successful_payment


class SuccessfulSubscriptionPaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="artist",
            email="artist@example.com",
            phone_number="690000000",
            password="secure-password",
            role=User.ROLE_ARTIST,
        )
        self.artist = ArtistProfile.objects.create(
            user=self.user,
            brand_name="Test artist",
            mobile_money_number="690000000",
            mobile_money_provider="orange",
        )
        self.subscription = self.artist.subscription

    def test_renewal_adds_to_remaining_subscription_time(self):
        remaining_end = timezone.now() + timedelta(days=8)
        self.subscription.status = Subscription.STATUS_ACTIVE
        self.subscription.current_period_end = remaining_end
        self.subscription.save(update_fields=["status", "current_period_end"])
        payment = SubscriptionPayment.objects.create(
            subscription=self.subscription,
            external_reference="early-renewal",
            phone_number="237690000000",
            amount_xaf=2500,
            duration_months=1,
        )

        apply_successful_payment(payment, {"status": "SUCCESSFUL", "reference": "campay-early-renewal"})

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.STATUS_ACTIVE)
        self.assertEqual(self.subscription.current_period_end, remaining_end + timedelta(days=30))

    def test_repeated_success_callback_does_not_extend_twice(self):
        payment = SubscriptionPayment.objects.create(
            subscription=self.subscription,
            external_reference="idempotent-renewal",
            phone_number="237690000000",
            amount_xaf=2500,
            duration_months=1,
        )
        payload = {"status": "SUCCESSFUL", "reference": "campay-idempotent-renewal"}

        apply_successful_payment(payment, payload)
        self.subscription.refresh_from_db()
        first_end_date = self.subscription.current_period_end
        apply_successful_payment(payment, payload)
        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.current_period_end, first_end_date)


class CustomSubscriptionAmountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="artist-custom-amount",
            email="custom-amount@example.com",
            phone_number="690000001",
            password="secure-password",
            role=User.ROLE_ARTIST,
        )
        self.artist = ArtistProfile.objects.create(
            user=self.user,
            brand_name="Custom amount artist",
            mobile_money_number="690000001",
            mobile_money_provider="orange",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = "/api/billing/campay/start/"

    @override_settings(CAMPAY_BASE_URL="https://demo.campay.net/api")
    def test_demo_custom_amount_is_sent_to_campay(self):
        token_response = Mock()
        token_response.json.return_value = {"token": "test-token"}
        collect_response = Mock()
        collect_response.json.return_value = {"reference": "demo-reference"}

        with patch("billing.views.requests.post", side_effect=[token_response, collect_response]) as post:
            response = self.client.post(
                self.url,
                {"plan_id": 2, "amount_xaf": 18, "phone_number": "690000001", "method": "orange"},
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["amount_xaf"], 18)
        self.assertEqual(post.call_args_list[1].kwargs["json"]["amount"], "18")

    @override_settings(CAMPAY_BASE_URL="https://api.campay.net/api")
    def test_custom_amount_is_rejected_outside_demo(self):
        response = self.client.post(
            self.url,
            {"plan_id": 2, "amount_xaf": 18, "phone_number": "690000001", "method": "orange"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(SubscriptionPayment.objects.exists())

    @override_settings(CAMPAY_BASE_URL="https://demo.campay.net/api")
    def test_demo_custom_amount_cannot_exceed_22(self):
        response = self.client.post(
            self.url,
            {"plan_id": 2, "amount_xaf": 23, "phone_number": "690000001", "method": "orange"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(SubscriptionPayment.objects.exists())
