from django.contrib.auth import get_user_model
from accounts.models import ArtistProfile
from catalog.models import Product, Conversation

User = get_user_model()

fedoun = User.objects.get(username="fedoun")
fedoun.expo_push_token = "ExponentPushToken[real-device-token-9999]"
fedoun.set_password("testpass123")
fedoun.save()

leila = User.objects.get(username="leila")
leila.expo_push_token = "ExponentPushToken[fake-test-token-456]"
leila.set_password("testpass123")
leila.save()

print(f"fedoun: staff={fedoun.is_staff} token={fedoun.expo_push_token}")
print(f"leila: role={leila.role} token={leila.expo_push_token}")

ap = ArtistProfile.objects.filter(user=leila).first()

p_approve = Product.objects.create(
    artist=ap, title="Approve Test", description="Test",
    status="pending", price_xaf=100000, category="other",
)
p_reject = Product.objects.create(
    artist=ap, title="Reject Test", description="Test",
    status="pending", price_xaf=100000, category="other",
)
print(f"Product to approve: id={p_approve.id}")
print(f"Product to reject: id={p_reject.id}")

approved_product = Product.objects.filter(status="approved").first()
conv, created = Conversation.objects.get_or_create(product=approved_product, customer=fedoun)
print(f"Conversation id={conv.id} (created={created}) on product id={approved_product.id}")

print("\n--- SUMMARY: use these IDs in the test script ---")
print(f"APPROVE_PRODUCT_ID = {p_approve.id}")
print(f"REJECT_PRODUCT_ID  = {p_reject.id}")
print(f"CONVERSATION_ID    = {conv.id}")