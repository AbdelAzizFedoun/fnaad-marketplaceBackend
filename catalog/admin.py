from django.contrib import admin  # type: ignore
from .models import Product, ProductImage


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "artist", "price_xaf", "status", "created_at")
    list_filter = ("status",)
    inlines = [ProductImageInline]


admin.site.register(Product, ProductAdmin)