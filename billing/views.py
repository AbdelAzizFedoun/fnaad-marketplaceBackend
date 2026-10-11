import hashlib
import hmac
import re
import uuid
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta
from .models import Subscription, SubscriptionPayment
from .serializers import SubscriptionSerializer, AdminSubscriptionStatsSerializer
from catalog.permissions import IsSuperAdmin
from .serializers import SubscriptionSerializer, StartSubscriptionPaymentSerializer, SubscriptionPaymentSerializer, AdminSubscriptionStatsSerializer, SubscriptionPlanSerializer


def get_subscription_plan(plan_id: int):
    for plan in settings.SUBSCRIPTION_PLANS:
        if plan["id"] == plan_id:
            return plan
    return None


def is_campay_demo():
    return urlparse(settings.CAMPAY_BASE_URL).hostname == "demo.campay.net"


def campay_token():
    if not settings.CAMPAY_USERNAME or not settings.CAMPAY_PASSWORD:
        raise RuntimeError("CamPay is not configured. Set CAMPAY_USERNAME and CAMPAY_PASSWORD on the backend.")
    response = requests.post(
        f"{settings.CAMPAY_BASE_URL}/token/",
        json={"username": settings.CAMPAY_USERNAME, "password": settings.CAMPAY_PASSWORD},
        timeout=20,
    )
    response.raise_for_status()
    token = response.json().get("token")
    if not token:
        raise RuntimeError("CamPay did not return an access token.")
    return token


def normalize_cameroon_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 9:
        digits = f"237{digits}"
    if not re.fullmatch(r"237[26]\d{8}", digits):
        raise ValueError("Enter a valid Cameroon MTN or Orange number.")
    return digits


def apply_successful_payment(payment, payload):
    """Idempotently grant subscription months after CamPay confirms collection."""
    provider_status = str(payload.get("status", "")).upper()
    was_successful = payment.status in {"SUCCESSFUL", "SUCCESS", "COMPLETED"}
    payment.status = provider_status or payment.status
    payment.provider_payload = payload
    if payload.get("reference"):
        payment.campay_reference = str(payload["reference"])
    payment.save(update_fields=["status", "provider_payload", "campay_reference", "updated_at"])
    if provider_status in {"SUCCESSFUL", "SUCCESS", "COMPLETED"} and not was_successful:
        subscription = payment.subscription
        now = timezone.now()
        # An early renewal must not discard the artist's remaining access.
        # Start the new plan at the later of the current expiry or payment time.
        renewal_start = max(now, subscription.current_period_end) if subscription.current_period_end else now
        subscription.status = Subscription.STATUS_ACTIVE
        subscription.current_period_end = renewal_start + timedelta(days=30 * payment.duration_months)
        subscription.last_payment_id = payment.campay_reference or payment.external_reference
        subscription.save(update_fields=["status", "current_period_end", "last_payment_id"])


class StartSubscriptionPaymentView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StartSubscriptionPaymentSerializer

    def post(self, request):
        artist = get_artist_profile_for_user(request.user)
        if artist is None:
            return Response({"detail": "Artist profile required."}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        plan_id = validated_data.get("plan_id", 1)
        plan = get_subscription_plan(plan_id)
        requested_amount = validated_data.get("amount_xaf")
        if requested_amount is not None and not is_campay_demo():
            return Response(
                {"amount_xaf": ["Custom amounts are only available during CamPay demo testing."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        amount_xaf = requested_amount if requested_amount is not None else plan["price_xaf"]
        method = validated_data.get("method")
        operator = {"orange": "ORANGE", "mtn": "MTN"}.get(method) if method else None
        try:
            phone = normalize_cameroon_phone(validated_data.get("phone_number") or artist.mobile_money_number)
        except ValueError as exc:
            return Response({"phone_number": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        subscription, _ = Subscription.objects.get_or_create(
            artist=artist, defaults={"trial_end_date": timezone.now() + timedelta(days=30)}
        )
        external_reference = f"fnaad-sub-{subscription.pk}-{uuid.uuid4().hex[:16]}"
        payment = SubscriptionPayment.objects.create(
            subscription=subscription, external_reference=external_reference,
            phone_number=phone, amount_xaf=amount_xaf, duration_months=plan["duration_months"],
        )
        try:
            token = campay_token()
            collect_body = {
                "amount": str(int(payment.amount_xaf)),
                "currency": "XAF",
                "from": phone,
                "description": "FNAAD artist subscription",
                "external_reference": external_reference,
            }
            if operator:
                collect_body["operator"] = operator
            response = requests.post(
                f"{settings.CAMPAY_BASE_URL}/collect/",
                headers={"Authorization": f"Token {token}"},
                json=collect_body,
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            payment.campay_reference = payload.get("reference")
            payment.provider_payload = payload
            payment.save(update_fields=["campay_reference", "provider_payload", "updated_at"])
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            payment.status = "FAILED"
            payment.save(update_fields=["status", "updated_at"])
            return Response({"detail": "Could not start the Mobile Money request. Please try again.", "error": str(exc)}, status=502)
        data = SubscriptionPaymentSerializer(payment).data
        # Surface whether we're on the CamPay demo sandbox so the client can
        # auto-finalize once the customer confirms on their phone (the demo
        # keeps the transaction PENDING on the API). In production this stays
        # False and confirmation relies on CamPay's webhook / status polling.
        data["demo_mode"] = is_campay_demo()
        return Response(data, status=status.HTTP_201_CREATED)


class SubscriptionPaymentStatusView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubscriptionPaymentSerializer

    def get_object(self):
        # An unknown or already-settled reference must be a 404, not a 500:
        # the app polls this endpoint while a CamPay payment is in flight.
        payment = get_object_or_404(
            SubscriptionPayment.objects.select_related("subscription__artist__user"),
            external_reference=self.kwargs["external_reference"],
        )
        if payment.subscription.artist.user_id != self.request.user.id:
            from django.http import Http404
            raise Http404
        if payment.campay_reference and payment.status == "PENDING":
            try:
                token = campay_token()
                result = requests.get(f"{settings.CAMPAY_BASE_URL}/transaction/{payment.campay_reference}/", headers={"Authorization": f"Token {token}"}, timeout=20)
                result.raise_for_status()
                apply_successful_payment(payment, result.json())
            except (requests.RequestException, RuntimeError, ValueError):
                pass  # Webhook remains the primary production confirmation channel.
        return payment


class SubscriptionPaymentConfirmView(generics.GenericAPIView):
    """
    Re-check CamPay for a completed collection, and (only if CamPay has not
    yet reflected success, e.g. the demo sandbox keeps the transaction
    PENDING after the customer confirms on their phone) trust the artist's
    confirmation that the USSD prompt was paid.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubscriptionPaymentSerializer

    def post(self, request):
        external_reference = request.data.get("external_reference")
        if not external_reference:
            return Response({"detail": "external_reference is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            payment = SubscriptionPayment.objects.select_related("subscription__artist__user").get(external_reference=external_reference)
        except SubscriptionPayment.DoesNotExist:
            return Response({"detail": "Unknown payment."}, status=status.HTTP_404_NOT_FOUND)
        if payment.subscription.artist.user_id != request.user.id:
            from django.http import Http404
            raise Http404

        # 1) Try real CamPay verification first.
        if payment.campay_reference and payment.status == "PENDING":
            try:
                token = campay_token()
                result = requests.get(
                    f"{settings.CAMPAY_BASE_URL}/transaction/{payment.campay_reference}/",
                    headers={"Authorization": f"Token {token}"},
                    timeout=20,
                )
                result.raise_for_status()
                apply_successful_payment(payment, result.json())
            except (requests.RequestException, RuntimeError, ValueError):
                pass

        # 2) Fallback: the artist confirmed the phone prompt but CamPay still
        #    shows PENDING (common in the demo sandbox), so grant the subscription.
        if payment.status == "PENDING" and is_campay_demo():
            apply_successful_payment(
                payment,
                {"status": "SUCCESSFUL", "reference": payment.campay_reference or payment.external_reference},
            )

        return Response(SubscriptionPaymentSerializer(payment).data, status=status.HTTP_200_OK)


class SubscriptionPlansView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SubscriptionPlanSerializer

    def get(self, request):
        return Response({"plans": settings.SUBSCRIPTION_PLANS, "demo_mode": is_campay_demo()})


@csrf_exempt
def campay_webhook(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    signature = request.headers.get("X-Campay-Signature", "")
    if not settings.CAMPAY_WEBHOOK_KEY:
        return JsonResponse({"detail": "CamPay webhook is not configured."}, status=503)
    expected = hmac.new(settings.CAMPAY_WEBHOOK_KEY.encode(), request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return HttpResponseBadRequest("Invalid signature")
    try:
        import json
        payload = json.loads(request.body)
        external_reference = payload.get("external_reference")
        payment = SubscriptionPayment.objects.get(external_reference=external_reference)
    except (ValueError, SubscriptionPayment.DoesNotExist):
        return HttpResponseBadRequest("Unknown payment")
    apply_successful_payment(payment, payload)
    return JsonResponse({"ok": True})


def get_artist_profile_for_user(user):
    return getattr(user, "artist_profile", None)


class MySubscriptionView(generics.RetrieveAPIView):
    """
    Artist-only: view their own subscription/trial status.
    """
    serializer_class = SubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        from django.http import Http404
        artist_profile = get_artist_profile_for_user(self.request.user)
        if artist_profile is None:
            raise Http404("Profil artiste introuvable.")
        subscription, _ = Subscription.objects.get_or_create(
            artist=artist_profile,
            defaults={"trial_end_date": timezone.now() + timedelta(days=30)},
        )
        return subscription


class AdminSubscriptionsListView(generics.ListAPIView):
    """
    Staff-only: list all artist subscriptions, for manual activation after
    the artist pays via Mobile Money outside the app.
    """
    serializer_class = SubscriptionSerializer
    permission_classes = [IsSuperAdmin]
    queryset = Subscription.objects.all().select_related("artist", "artist__user").order_by("-trial_start_date")


class AdminActivateSubscriptionView(generics.UpdateAPIView):
    """
    Staff-only: manually activate a subscription (mark as paid) for a set
    number of days, or cancel it.
    Expects PATCH {"action": "activate", "days": 30} or {"action": "cancel"}.
    """
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [IsSuperAdmin]

    def patch(self, request, *args, **kwargs):
        subscription = self.get_object()
        action = request.data.get("action")

        if action == "activate":
            days = int(request.data.get("days", 30))
            subscription.status = Subscription.STATUS_ACTIVE
            subscription.current_period_end = timezone.now() + timedelta(days=days)
            subscription.save()
        elif action == "cancel":
            subscription.status = Subscription.STATUS_CANCELLED
            subscription.save()
        else:
            return Response({"detail": "action must be 'activate' or 'cancel'."}, status=400)

        return Response(SubscriptionSerializer(subscription).data)


class AdminSubscriptionStatsView(generics.GenericAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminSubscriptionStatsSerializer

    def get(self, request):
        from django.db.models import Count, Q
        qs = Subscription.objects.all()
        stats = qs.aggregate(
            total_artists=Count("id"),
            trial_count=Count("id", filter=Q(status=Subscription.STATUS_TRIAL)),
            active_count=Count("id", filter=Q(status=Subscription.STATUS_ACTIVE)),
            expired_count=Count("id", filter=Q(status=Subscription.STATUS_EXPIRED)),
            cancelled_count=Count("id", filter=Q(status=Subscription.STATUS_CANCELLED)),
        )
        data = {
            "plans": settings.SUBSCRIPTION_PLANS,
            **stats,
        }
        return Response(AdminSubscriptionStatsSerializer(data).data)
