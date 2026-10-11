from rest_framework import serializers
from .models import Order


class OrderSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source="product.title", read_only=True)
    artist_name = serializers.CharField(source="artist.brand_name", read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "product", "product_title", "artist", "artist_name",
            "amount_xaf", "status", "created_at",
        ]
        read_only_fields = ["artist", "amount_xaf", "status"]