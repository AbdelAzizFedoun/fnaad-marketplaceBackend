from django.contrib import admin
from .models import Subscription, SubscriptionPayment


class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("artist", "status", "trial_end_date", "current_period_end", "monthly_price_xaf")
    list_filter = ("status",)


admin.site.register(Subscription, SubscriptionAdmin)


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ("external_reference", "subscription", "amount_xaf", "status", "campay_reference", "created_at")
    list_filter = ("status",)
    search_fields = ("external_reference", "campay_reference", "phone_number")
