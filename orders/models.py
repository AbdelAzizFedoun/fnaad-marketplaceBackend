from django.conf import settings
from django.db import models
from accounts.models import ArtistProfile
from catalog.models import Product


class Order(models.Model):
    STATUS_PENDING_PAYMENT = "pending_payment"
    STATUS_PAID = "paid"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING_PAYMENT, "Pending payment"),
        (STATUS_PAID, "Paid"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="orders")
    artist = models.ForeignKey(ArtistProfile, on_delete=models.PROTECT, related_name="orders")
    amount_xaf = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING_PAYMENT)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Order #{self.id} — {self.product.title}"


class Payment(models.Model):
    PROVIDER_CHOICES = [("orange", "Orange Money"), ("mtn", "MTN MoMo")]

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="payment")
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    aggregator_transaction_id = models.CharField(max_length=100, blank=True)
    payer_phone_number = models.CharField(max_length=20)
    is_confirmed = models.BooleanField(default=False)
    raw_callback_payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment for Order #{self.order.id}"