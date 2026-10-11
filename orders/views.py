from rest_framework import generics, permissions
from .models import Order
from .serializers import OrderSerializer
from catalog.models import Product
from accounts.push import send_push_notification


class OrderCreateView(generics.CreateAPIView):
    """
    Customer sends an inquiry on a product — creates an Order in
    pending_payment status. No money moves yet; this is the first
    signal of interest, visible to the artist afterward.
    """
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        product = Product.objects.get(id=self.request.data.get("product"))
        serializer.save(
            customer=self.request.user,
            artist=product.artist,
            amount_xaf=product.price_xaf,
            status=Order.STATUS_PENDING_PAYMENT,
        )


class MyOrdersView(generics.ListAPIView):
    """
    Artist's view of orders/inquiries received on their products.
    """
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        artist_profile = getattr(self.request.user, "artist_profile", None)
        if artist_profile is None:
            return Order.objects.none()
        return Order.objects.filter(artist=artist_profile).order_by("-created_at")
    
class OrderCreateView(generics.CreateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        product = Product.objects.get(id=self.request.data.get("product"))
        order = serializer.save(
            customer=self.request.user,
            artist=product.artist,
            amount_xaf=product.price_xaf,
            status=Order.STATUS_PENDING_PAYMENT,
        )

        send_push_notification(
            product.artist.user.expo_push_token,
            title="New order",
            body=f"{self.request.user.username} is interested in \"{product.title}\"",
            data={"type": "new_order", "order_id": order.id},
        )





