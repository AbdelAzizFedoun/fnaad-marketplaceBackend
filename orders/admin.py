from django.contrib import admin
from .models import Order, Payment


class PaymentInline(admin.StackedInline):
    model = Payment
    can_delete = False


class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "product", "artist", "amount_xaf", "status", "created_at")
    list_filter = ("status",)
    inlines = [PaymentInline]


admin.site.register(Order, OrderAdmin)