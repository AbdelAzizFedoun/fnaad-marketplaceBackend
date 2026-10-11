from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.db.models.signals import post_save
from django.dispatch import receiver
from accounts.models import ArtistProfile

TRIAL_DAYS = 30


class Subscription(models.Model):
    STATUS_TRIAL = "trial"
    STATUS_ACTIVE = "active"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_TRIAL, "Free trial"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    artist = models.OneToOneField(ArtistProfile, on_delete=models.CASCADE, related_name="subscription")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_TRIAL)
    trial_start_date = models.DateTimeField(auto_now_add=True)
    trial_end_date = models.DateTimeField()
    current_period_end = models.DateTimeField(null=True, blank=True)
    monthly_price_xaf = models.PositiveIntegerField(default=22)
    last_payment_id = models.CharField(max_length=100, blank=True)

    @property
    def is_active(self):
        now = timezone.now()
        if self.status == self.STATUS_TRIAL:
            return now <= self.trial_end_date
        if self.status == self.STATUS_ACTIVE:
            return self.current_period_end and now <= self.current_period_end
        return False

    @property
    def effective_end_date(self):
        if self.status == self.STATUS_ACTIVE and self.current_period_end:
            return self.current_period_end
        return self.trial_end_date

    def __str__(self):
        return f"{self.artist.brand_name} — {self.status}"


class SubscriptionPayment(models.Model):
    """A CamPay collection request for an artist's subscription."""
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="payments")
    external_reference = models.CharField(max_length=100, unique=True)
    campay_reference = models.CharField(max_length=100, unique=True, null=True, blank=True)
    phone_number = models.CharField(max_length=20)
    amount_xaf = models.PositiveIntegerField()
    duration_months = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=30, default="PENDING")
    provider_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.external_reference} ({self.status})"


@receiver(post_save, sender=ArtistProfile)
def create_subscription_for_artist(sender, instance, created, **kwargs):
    if created:
        Subscription.objects.get_or_create(
            artist=instance,
            defaults={"trial_end_date": timezone.now() + timedelta(days=TRIAL_DAYS)},
        )
