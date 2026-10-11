from rest_framework import generics, permissions, status, views as drf_views
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.parsers import MultiPartParser as MPParser, FormParser as FParser
from rest_framework import serializers as drf_serializers
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.shortcuts import render, get_object_or_404
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.conf import settings
import logging
from pathlib import Path
import os
import uuid
from datetime import timedelta
from .models import Product, ProductImage, Conversation, Message, MessageReaction, Favorite, Review, CommissionRequest, CommissionResponse, SiteSettings
from social.models import Comment
from social.models import Comment, Like
from .serializers import ProductSerializer, ProductImageSerializer, ConversationSerializer, MessageSerializer, FavoriteSerializer, ProductCommentSerializer, ReviewSerializer, CommissionRequestSerializer, CommissionResponseSerializer, CustomerProfileSerializer, SiteSettingsSerializer, AdminArtistSerializer, ArtistPublicSerializer, ArtistPrivateSerializer, SanaaArtistRecommendationSerializer
from .models import Product
from django.db.models import Avg, Count
from django.db.models.functions import Coalesce

from billing.models import Subscription
from .assistant import (
    ALLOWED_IMAGE_TYPES,
    MAX_UPLOAD_BYTES,
    ask_sanaa,
    get_my_products,
    rank_artists_by_image,
    resolve_catalogue,
    should_load_catalogue,
    wants_recommendations,
)

logger = logging.getLogger(__name__)


class StandardResultsPagination(PageNumberPagination):
    """Default pagination for public lists: 20 rows per page,
    clients may request up to 100 with ?page_size=."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

from accounts.models import ArtistProfile
from .models import Product, ProductImage, Conversation, Message
from .serializers import ProductSerializer, ProductImageSerializer, ConversationSerializer, MessageSerializer
from .image_utils import generate_product_thumbnail
from accounts.push import send_push_notification, create_notification
from .permissions import IsSuperAdmin

def product_public_view(request, slug):
    product = get_object_or_404(Product, public_slug=slug, status="approved")
    images = list(product.images.all())
    primary_image = next((image for image in images if image.is_primary), None) or (images[0] if images else None)
    image_url = request.build_absolute_uri(primary_image.image.url) if primary_image else None

    return render(request, "product_share.html", {
        "product": product,
        "image_url": image_url,
        "product_images": [
            request.build_absolute_uri(image.image.url)
            for image in images
        ],
    })

def user_is_artist(user):
    return bool(
        user
        and user.is_authenticated
        and getattr(user, "role", None) == user.ROLE_ARTIST
    )


def get_artist_profile_for_user(user):
    if not user_is_artist(user):
        return None
    return getattr(user, "artist_profile", None)


def conversations_visible_to_user(user):
    artist_profile = get_artist_profile_for_user(user)
    query = models.Q(customer=user)

    if artist_profile is not None:
        query |= models.Q(product__artist=artist_profile)
        query |= models.Q(commission_response__artist=artist_profile)

    return Conversation.objects.filter(query, blocked_by__isnull=True).distinct()


def conversation_artist_profile(conversation):
    """The artist behind a conversation.

    A conversation either comes from a product or from a commission response,
    so `conversation.product` is None for commissions. Reading the artist
    through this helper keeps every caller null-safe.
    """
    if conversation.product_id is not None:
        return conversation.product.artist
    return conversation.commission_response.artist


def conversation_artist_id(conversation):
    return conversation_artist_profile(conversation).id


class ProductListView(generics.ListAPIView):
    """
    Public list of approved artworks — this is what React Native
    will call to display the main gallery.
    Supports optional ?region=<region_code>, ?category=<category_code>,
    ?search=<text> (matches product title or artist brand name),
    and ?sort=<newest|price_low|price_high|rating> (default: newest).
    """
    pagination_class = StandardResultsPagination
    serializer_class = ProductSerializer

    def get_queryset(self):
        from django.utils import timezone
        now = timezone.now()

        queryset = Product.objects.filter(
            status=Product.STATUS_APPROVED,
            artist__is_suspended=False,
        ).select_related(
            # Pull artist + their user in one JOIN — avoids 1 query per product
            "artist",
            "artist__user",
        ).prefetch_related(
            # Load all images in a single grouped query
            "images",
            # Load reviews, favorites and comments in bulk
            "reviews",
            "favorited_by",
            "comments",
        )

        queryset = queryset.filter(
            models.Q(artist__subscription__status=Subscription.STATUS_TRIAL, artist__subscription__trial_end_date__gte=now)
            | models.Q(artist__subscription__status=Subscription.STATUS_ACTIVE, artist__subscription__current_period_end__gte=now)
        )

        region = self.request.query_params.get("region")
        if region:
            queryset = queryset.filter(artist__region=region)

        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category=category)

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                models.Q(title__icontains=search) | models.Q(artist__brand_name__icontains=search)
            )

        queryset = queryset.annotate(
            avg_rating=Coalesce(Avg("reviews__rating"), 0.0),
            fav_count=Count("favorited_by", distinct=True),
        )

        sort = self.request.query_params.get("sort", "newest")
        if sort == "price_low":
            queryset = queryset.order_by("price_xaf")
        elif sort == "price_high":
            queryset = queryset.order_by("-price_xaf")
        elif sort == "rating":
            queryset = queryset.order_by("-avg_rating", "-created_at")
        elif sort == "popular":
            queryset = queryset.order_by("-fav_count", "-created_at")
        else:
            queryset = queryset.order_by("-created_at")

        return queryset




class ProductCreateView(generics.CreateAPIView):
    """
    Lets an authenticated artist create a new product.
    Status depends on SiteSettings.require_product_approval:
    pending (needs admin review) if enabled, approved immediately if disabled.
    Suspended artists cannot create new products.
    """
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        if not user_is_artist(self.request.user):
            raise PermissionDenied("Seuls les artistes peuvent creer des oeuvres.")

        artist_profile = getattr(self.request.user, "artist_profile", None)
        if artist_profile is None:
            artist_profile = ArtistProfile.objects.create(
                user=self.request.user,
                brand_name=self.request.user.username,
                mobile_money_number=self.request.user.phone_number or "0000000000",
                mobile_money_provider="orange",
            )

        if artist_profile.is_suspended:
            raise PermissionDenied("Your artist account has been suspended. Contact the FNAAD team.")

        from django.utils import timezone
        from datetime import timedelta
        subscription, _ = Subscription.objects.get_or_create(
            artist=artist_profile,
            defaults={"trial_end_date": timezone.now() + timedelta(days=30)},
        )
        if not subscription.is_active:
            raise PermissionDenied(
                "Your trial period has ended. Subscribe to continue publishing artworks."
            )

        site_settings = SiteSettings.get_solo()
        initial_status = (
            Product.STATUS_PENDING if site_settings.require_product_approval else Product.STATUS_APPROVED
        )

        serializer.save(artist=artist_profile, status=initial_status)

        if initial_status == Product.STATUS_APPROVED:
            send_push_notification(
                self.request.user.expo_push_token,
                title="Artwork published",
                body=f"\"{serializer.instance.title}\" is now publicly visible.",
                data={"type": "product_status", "product_id": serializer.instance.id, "status": "approved"},
            )

class PendingProductListView(generics.ListAPIView):
    """
    Staff-only list of products awaiting approval.
    """
    serializer_class = ProductSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        return Product.objects.filter(status=Product.STATUS_PENDING)


class ProductApproveView(generics.UpdateAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsSuperAdmin]

    def patch(self, request, *args, **kwargs):
        product = self.get_object()
        new_status = request.data.get("status")

        if new_status not in [Product.STATUS_APPROVED, Product.STATUS_REJECTED]:
            return Response(
                {"detail": "Status must be 'approved' or 'rejected'."},
                status=400,
            )

        product.status = new_status
        product.save()

        artist_user = product.artist.user
        if new_status == Product.STATUS_APPROVED:
            title, body = "Artwork approved", f"\"{product.title}\" is now publicly visible."
        else:
            title, body = "Artwork rejected", f"\"{product.title}\" was not approved."

        create_notification(
            artist_user, title, body, "product_status",
            {"product_id": product.id, "status": new_status},
        )

        return Response(ProductSerializer(product).data)


class ProductImageUploadView(generics.CreateAPIView):
    """
    Lets the product's owning artist upload an image for it.
    Expects multipart form data: image=<file>, is_primary=<bool>, order=<int>
    """
    serializer_class = ProductImageSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def perform_create(self, serializer):
        product_id = self.kwargs["product_id"]
        product = Product.objects.get(id=product_id)

        artist_profile = get_artist_profile_for_user(self.request.user)
        if artist_profile is None or product.artist_id != artist_profile.id:
            raise PermissionDenied("You cannot modify this artwork.")

        product_image = serializer.save(product=product)
        generate_product_thumbnail(product_image)


class ProductDetailView(generics.RetrieveAPIView):
    """
    Detail view for a single product.
    Public (approved) products are visible to everyone.
    The owning artist can also view their own product regardless of status
    (needed so they can load it into the edit screen even if pending/rejected).
    """
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return Product.objects.all()

    def get_object(self):
        obj = super().get_object()
        user = self.request.user

        artist_profile = get_artist_profile_for_user(user) if user.is_authenticated else None
        is_owner = artist_profile is not None and obj.artist_id == artist_profile.id

        if obj.status == Product.STATUS_APPROVED:
            # Don't count the artist viewing their own product
            if not is_owner:
                Product.objects.filter(id=obj.id).update(view_count=models.F("view_count") + 1)
                obj.refresh_from_db(fields=["view_count"])
            return obj

        if is_owner:
            return obj

        from django.http import Http404
        raise Http404("Product not found.")
    
class StartConversationView(generics.CreateAPIView):
    """
    Customer starts (or resumes) a conversation about a specific product.
    Expects: {"product": <product_id>}
    Returns the existing conversation if one already exists for this customer+product.
    """
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        product_id = request.data.get("product")
        product = get_object_or_404(Product, id=product_id, status=Product.STATUS_APPROVED)

        if product.artist.user_id == request.user.id:
            return Response(
                {"detail": "You cannot start a conversation with yourself."},
                status=400,
            )

        existing = Conversation.objects.filter(product=product, customer=request.user).first()
        if existing and existing.blocked_by_id:
            return Response({"detail": "This conversation is no longer available."}, status=status.HTTP_403_FORBIDDEN)

        conversation, created = Conversation.objects.get_or_create(
            product=product,
            customer=request.user,
        )
        serializer = self.get_serializer(conversation)
        return Response(serializer.data, status=201 if created else 200)


class StartCommissionConversationView(generics.CreateAPIView):
    """
    Customer starts (or resumes) a conversation about a commission response.
    Expects: {"commission_response": <response_id>}
    Returns the existing conversation if one already exists for this customer+response.
    Sends an initial message to start the conversation about the commission request.
    """
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        response_id = request.data.get("commission_response")
        response = get_object_or_404(CommissionResponse, id=response_id)

        if response.commission.customer_id != request.user.id:
            return Response(
                {"detail": "Vous ne pouvez pas ouvrir une conversation pour cette demande."},
                status=403,
            )

        if response.artist.user_id == request.user.id:
            return Response(
                {"detail": "Vous ne pouvez pas ouvrir une conversation avec vous-meme."},
                status=400,
            )

        existing = Conversation.objects.filter(commission_response=response, customer=request.user).first()
        if existing and existing.blocked_by_id:
            return Response({"detail": "This conversation is no longer available."}, status=status.HTTP_403_FORBIDDEN)

        conversation, created = Conversation.objects.get_or_create(
            commission_response=response,
            customer=request.user,
        )

        if created:
            commission_title = response.commission.title
            initial_message = f"Hello, I am interested in continuing the conversation about your commission request \"{commission_title}\" on FNAAD."
            Message.objects.create(
                conversation=conversation,
                sender=request.user,
                message_type=Message.TYPE_TEXT,
                text=initial_message,
            )

            send_push_notification(
                response.artist.user.expo_push_token,
                title="New message",
                body=f"{request.user.username} started a conversation about \"{commission_title}\"",
                data={"type": "message", "conversation_id": conversation.id},
            )

        serializer = self.get_serializer(conversation)
        return Response(serializer.data, status=201 if created else 200)


class MyConversationsListView(generics.ListAPIView):
    """
    Lists conversations relevant to the logged-in user:
    - If customer: conversations they started
    - If artist: conversations about their products
    """
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return conversations_visible_to_user(self.request.user)


class ConversationDetailView(generics.RetrieveAPIView):
    """
    Fetch a single conversation with its full message history.
    Only accessible to the customer involved or the product's artist.
    """
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return conversations_visible_to_user(self.request.user)


class SendMessageView(generics.CreateAPIView):
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    # Chat messages can contain JSON (text/location) or a file uploaded from
    # the mobile image/document picker.
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def perform_create(self, serializer):
        conversation_id = self.request.data.get("conversation")
        user = self.request.user
        conversation = get_object_or_404(conversations_visible_to_user(user), id=conversation_id)
        reply_to = serializer.validated_data.get("reply_to")

        if reply_to and reply_to.conversation_id != conversation.id:
            raise drf_serializers.ValidationError({
                "reply_to_id": "A reply must reference a message in this conversation."
            })

        message = serializer.save(conversation=conversation, sender=user)

        if user.id == conversation.customer_id:
            recipient = conversation_artist_profile(conversation).user
        else:
            recipient = conversation.customer

        if message.message_type == Message.TYPE_IMAGE:
            body = f"{user.username} sent you an image"
        elif message.message_type == Message.TYPE_DOCUMENT:
            body = f"{user.username} sent you a document"
        elif message.message_type == Message.TYPE_LOCATION:
            body = f"{user.username} sent you their location"
        else:
            body = f"{user.username}: {message.text[:80]}" if message.text else f"{user.username} sent you a message"

        send_push_notification(
            recipient.expo_push_token,
            title="New message",
            body=body,
            data={"type": "message", "conversation_id": conversation.id},
        )


class ToggleMessageReactionView(generics.GenericAPIView):
    """Add, replace, or remove the current user's reaction on a message."""

    permission_classes = [permissions.IsAuthenticated]
    allowed_emojis = {"❤️", "👍", "😂", "😮", "😢", "🙏"}

    def post(self, request, pk):
        emoji = str(request.data.get("emoji", "")).strip()
        if emoji not in self.allowed_emojis:
            raise drf_serializers.ValidationError({"emoji": "Choose one of the supported reactions."})

        message = get_object_or_404(
            Message.objects.filter(conversation__in=conversations_visible_to_user(request.user)),
            pk=pk,
        )
        existing = MessageReaction.objects.filter(message=message, user=request.user).first()

        if existing and existing.emoji == emoji:
            existing.delete()
        elif existing:
            existing.emoji = emoji
            existing.save(update_fields=["emoji"])
        else:
            MessageReaction.objects.create(message=message, user=request.user, emoji=emoji)

        return Response(MessageSerializer(message, context={"request": request}).data)


class ForwardMessageView(generics.GenericAPIView):
    """Forward a visible message into another conversation owned by the user."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        source = get_object_or_404(
            Message.objects.filter(conversation__in=conversations_visible_to_user(request.user)), pk=pk
        )
        target_id = request.data.get("conversation_id")
        target = get_object_or_404(conversations_visible_to_user(request.user), id=target_id)
        if target.id == source.conversation_id:
            raise drf_serializers.ValidationError({"conversation_id": "Choose a different conversation."})

        forwarded = Message.objects.create(
            conversation=target, sender=request.user, message_type=source.message_type,
            text=source.text, latitude=source.latitude, longitude=source.longitude,
            image=source.image.name if source.image else None,
            document=source.document.name if source.document else None,
            audio=source.audio.name if source.audio else None,
            is_forwarded=True,
        )
        recipient = conversation_artist_profile(target).user if target.customer_id == request.user.id else target.customer
        send_push_notification(
            recipient.expo_push_token, title="New message",
            body=f"{request.user.username} forwarded you a message",
            data={"type": "message", "conversation_id": target.id},
        )
        return Response(MessageSerializer(forwarded, context={"request": request}).data, status=status.HTTP_201_CREATED)


class ConversationMessagesDeleteView(generics.GenericAPIView):
    """Let a participant permanently unsend only messages they authored."""
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        conversation = get_object_or_404(conversations_visible_to_user(request.user), id=pk)
        message_ids = request.data.get("message_ids")
        messages = conversation.messages.filter(sender=request.user)

        if message_ids is not None:
            if not isinstance(message_ids, list) or not all(isinstance(value, int) for value in message_ids):
                return Response({"message_ids": "Provide a list of message IDs."}, status=status.HTTP_400_BAD_REQUEST)
            messages = messages.filter(id__in=message_ids)

        # Django does not delete files when a FileField row is deleted.
        for message in messages:
            if message.image:
                message.image.delete(save=False)
            if message.document:
                message.document.delete(save=False)

        deleted_count, _ = messages.delete()
        return Response({"deleted_count": deleted_count}, status=status.HTTP_200_OK)


class ConversationTypingView(generics.GenericAPIView):
    """Store a short-lived typing heartbeat for the other participant."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        conversation = get_object_or_404(conversations_visible_to_user(request.user), id=pk)
        is_typing = bool(request.data.get("is_typing", False))
        artist = conversation_artist_profile(conversation)
        field = "artist_typing_until" if request.user.id == artist.user_id else "customer_typing_until"
        setattr(conversation, field, timezone.now() + timedelta(seconds=6) if is_typing else None)
        conversation.save(update_fields=[field])
        return Response({"is_typing": is_typing})


class ConversationBlockView(generics.GenericAPIView):
    """Block the other participant and remove this chat from both inboxes."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        conversation = get_object_or_404(conversations_visible_to_user(request.user), id=pk)
        conversation.blocked_by = request.user
        conversation.customer_typing_until = None
        conversation.artist_typing_until = None
        conversation.save(update_fields=["blocked_by", "customer_typing_until", "artist_typing_until"])
        return Response({"blocked": True})


class BlockedConversationListView(generics.ListAPIView):
    """List conversations blocked by the current user only."""
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Conversation.objects.filter(blocked_by=self.request.user).select_related(
            "customer", "product__artist", "product__artist__user",
            "commission_response__artist", "commission_response__artist__user",
        )


class ConversationUnblockView(generics.GenericAPIView):
    """Only the participant who blocked a conversation can restore it."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, id=pk, blocked_by=request.user)
        conversation.blocked_by = None
        conversation.save(update_fields=["blocked_by"])
        return Response({"blocked": False})


class MessageEditView(generics.GenericAPIView):
    """Edit a sender's own text message while preserving its identity and replies."""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        message = get_object_or_404(
            Message.objects.filter(
                conversation__in=conversations_visible_to_user(request.user),
                sender=request.user,
                message_type=Message.TYPE_TEXT,
            ),
            pk=pk,
        )
        text = str(request.data.get("text", "")).strip()
        if not text:
            raise drf_serializers.ValidationError({"text": "A message cannot be empty."})
        message.text = text
        message.edited_at = timezone.now()
        message.save(update_fields=["text", "edited_at"])
        return Response(MessageSerializer(message, context={"request": request}).data)


class UpdateConversationStatusView(generics.UpdateAPIView):
    """
    Updates a conversation's status.
    Customer can only set: confirmed, cancelled
    Artist can only set: delivered, cancelled
    Expects: PATCH {"status": "confirmed"}
    """
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return conversations_visible_to_user(self.request.user)

    def patch(self, request, *args, **kwargs):
        conversation = self.get_object()
        new_status = request.data.get("status")
        user = request.user
        artist_profile = get_artist_profile_for_user(user)

        is_artist = artist_profile is not None and conversation_artist_id(conversation) == artist_profile.id
        is_customer = conversation.customer_id == user.id

        allowed_for_customer = [Conversation.STATUS_CONFIRMED, Conversation.STATUS_CANCELLED]
        allowed_for_artist = [Conversation.STATUS_DELIVERED, Conversation.STATUS_CANCELLED]

        if is_customer and new_status in allowed_for_customer:
            pass
        elif is_artist and new_status in allowed_for_artist:
            pass
        else:
            return Response(
                {"detail": "You are not authorized to set this status."},
                status=403,
            )

        conversation.status = new_status
        conversation.save()

        recipient = conversation.product.artist.user if is_customer else conversation.customer
        status_labels = dict(Conversation.STATUS_CHOICES) if hasattr(Conversation, "STATUS_CHOICES") else {}
        status_label = status_labels.get(new_status, new_status)

        send_push_notification(
            recipient.expo_push_token,
            title="Order status updated",
            body=f"The order is now: {status_label}",
            data={"type": "order_status", "conversation_id": conversation.id, "status": new_status},
        )

        return Response(ConversationSerializer(conversation).data)


class MyProductsListView(generics.ListAPIView):
    """
    Lists all products belonging to the logged-in artist,
    regardless of status (pending, approved, rejected, hidden).
    """
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        artist_profile = get_artist_profile_for_user(self.request.user)
        if artist_profile is None:
            return Product.objects.none()
        return Product.objects.filter(artist=artist_profile).order_by("-created_at")


class UnreadMessageCountView(generics.GenericAPIView):
    """
    Returns the number of conversations with unread messages for the current user.
    Handles both customer-side and artist-side unread counts for dual-role users.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        conversations = conversations_visible_to_user(user)
        artist_profile = get_artist_profile_for_user(user)

        unread_count = 0
        for conv in conversations:
            is_artist_side = artist_profile is not None and conversation_artist_id(conv) == artist_profile.id
            last_read = conv.artist_last_read_at if is_artist_side else conv.customer_last_read_at
            last_message = conv.messages.order_by("-created_at").first()

            if last_message is None:
                continue
            if last_message.sender_id == user.id:
                continue
            if last_read is None:
                unread_count += 1
            elif last_message.created_at > last_read:
                unread_count += 1

        return Response({"unread_count": unread_count})


class MarkConversationReadView(generics.UpdateAPIView):
    """
    Marks a conversation as read for the current user (customer or artist side).
    """
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return conversations_visible_to_user(self.request.user)

    def patch(self, request, *args, **kwargs):
        conversation = self.get_object()
        user = request.user
        artist_profile = get_artist_profile_for_user(user)

        from django.utils import timezone
        now = timezone.now()

        if artist_profile is not None and conversation_artist_id(conversation) == artist_profile.id:
            conversation.artist_last_read_at = now
        else:
            conversation.customer_last_read_at = now

        conversation.save()
        return Response(ConversationSerializer(conversation, context={"request": request}).data)


class ProductUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    """
    Lets the owning artist view, edit, or delete their own product.
    Editing resets status back to pending (re-moderation required),
    since the content changed after approval.
    """
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        artist_profile = get_artist_profile_for_user(self.request.user)
        if artist_profile is None:
            return Product.objects.none()
        return Product.objects.filter(artist=artist_profile)

    def perform_update(self, serializer):
        site_settings = SiteSettings.get_solo()
        new_status = (
            Product.STATUS_PENDING if site_settings.require_product_approval else Product.STATUS_APPROVED
        )
        serializer.save(status=new_status)

class ProductMarkSoldView(generics.UpdateAPIView):
    """
    Lets the owning artist mark their product as sold or available again.
    Expects: PATCH {"is_sold": true} or {"is_sold": false}
    """
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        artist_profile = get_artist_profile_for_user(self.request.user)
        if artist_profile is None:
            return Product.objects.none()
        return Product.objects.filter(artist=artist_profile)

    def patch(self, request, *args, **kwargs):
        product = self.get_object()
        is_sold = request.data.get("is_sold")

        if is_sold is None:
            return Response(
                {"detail": "Field 'is_sold' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        product.is_sold = bool(is_sold)
        if product.is_sold and not product.sold_at:
            product.sold_at = timezone.now()
        elif not product.is_sold:
            product.sold_at = None
        product.save()

        return Response(ProductSerializer(product).data)


class ArtistProductsListView(generics.ListAPIView):
    """
    Public list of approved products for a given artist.
    Artists can always view their own products.
    Other viewers only see products if the artist has an active subscription/trial,
    or if the artist has no subscription at all.
    """
    pagination_class = StandardResultsPagination
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        from django.utils import timezone
        artist_id = self.kwargs["artist_id"]
        now = timezone.now()
        base_qs = Product.objects.filter(artist_id=artist_id, status=Product.STATUS_APPROVED)

        if self.request.user.is_authenticated:
            artist_profile = get_artist_profile_for_user(self.request.user)
            if artist_profile is not None and artist_profile.id == artist_id:
                return base_qs

        return base_qs.filter(
            models.Q(artist__subscription__isnull=True) |
            models.Q(artist__subscription__status=Subscription.STATUS_TRIAL, artist__subscription__trial_end_date__gte=now) |
            models.Q(artist__subscription__status=Subscription.STATUS_ACTIVE, artist__subscription__current_period_end__gte=now)
        )


class MyArtistProfileView(generics.RetrieveUpdateAPIView):
    """
    Lets a logged-in artist view and edit their own profile:
    brand_name, bio, avatar, region.
    """
    serializer_class = ArtistPrivateSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MPParser, FParser]

    def get_object(self):
        artist_profile = get_artist_profile_for_user(self.request.user)
        if artist_profile is None:
            from django.http import Http404
            raise Http404("Profil artiste introuvable.")
        return artist_profile

class CustomerProfileView(generics.RetrieveAPIView):
    """
    Artist-only: view a customer's profile - scoped so an artist can only
    see customers they've actually had a conversation with, not browse everyone.
    """
    serializer_class = CustomerProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        from django.http import Http404

        artist_profile = get_artist_profile_for_user(self.request.user)
        if artist_profile is None:
            raise PermissionDenied("Seuls les artistes peuvent voir ce profil.")

        customer_id = self.kwargs["pk"]
        has_conversation = Conversation.objects.filter(
            customer_id=customer_id, product__artist=artist_profile
        ).exists()
        if not has_conversation:
            raise Http404("Client introuvable.")

        User = get_user_model()
        return get_object_or_404(User, id=customer_id)    

class ReportConversationView(generics.UpdateAPIView):
    """
    Lets either party (customer or artist) flag a conversation as problematic.
    Expects: PATCH {"reason": "..."}
    """
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return conversations_visible_to_user(self.request.user)

    def patch(self, request, *args, **kwargs):
        conversation = self.get_object()
        reason = request.data.get("reason", "").strip()

        if not reason:
            return Response({"detail": "Please specify the problem."}, status=400)

        from django.utils import timezone
        conversation.is_reported = True
        conversation.report_reason = reason
        conversation.reported_at = timezone.now()
        conversation.save()

        return Response(ConversationSerializer(conversation, context={"request": request}).data)


class AdminReportedConversationsListView(generics.ListAPIView):
    """
    Staff-only list of reported conversations, for dispute review.
    """
    serializer_class = ConversationSerializer
    permission_classes = [IsSuperAdmin]
    queryset = Conversation.objects.filter(is_reported=True).order_by("-reported_at")        


class ToggleFavoriteView(generics.GenericAPIView):
    """
    POST {"product": <id>} — adds to favorites if not already favorited,
    removes if already favorited. Returns {"favorited": true/false}.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        product_id = request.data.get("product")
        product = get_object_or_404(Product, id=product_id)

        favorite, created = Favorite.objects.get_or_create(user=request.user, product=product)
        if not created:
            favorite.delete()
            return Response({"favorited": False})

        if product.artist and product.artist.user != request.user:
            create_notification(
                product.artist.user,
                "New Like",
                f"{request.user.username} liked your artwork “{product.title}”.",
                "favorite",
                {"product_id": product.id},
            )

        return Response({"favorited": True})


class MyFavoritesListView(generics.ListAPIView):
    """
    Full list of the logged-in user's favorited products (with product details).
    """
    serializer_class = FavoriteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Favorite.objects.filter(user=self.request.user).order_by("-created_at")


class MyFavoriteIdsView(generics.GenericAPIView):
    """
    Lightweight endpoint: just the list of favorited product IDs,
    so the gallery can mark hearts as filled without fetching full product data again.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        ids = list(Favorite.objects.filter(user=request.user).values_list("product_id", flat=True))
        return Response({"favorite_ids": ids})


class ProductCommentListCreateView(generics.ListCreateAPIView):
    """Public discussion, with posting reserved for signed-in users."""
    pagination_class = StandardResultsPagination
    serializer_class = ProductCommentSerializer

    def get_permissions(self):
        return [permissions.IsAuthenticated()] if self.request.method == "POST" else [permissions.AllowAny()]

    def get_queryset(self):
        return Comment.objects.filter(
            product_id=self.kwargs["product_id"]
        ).select_related("customer")
    
    def perform_create(self, serializer):
        product = get_object_or_404(Product, id=self.kwargs["product_id"])
        serializer.save(product=product, customer=self.request.user)

        if product.artist and product.artist.user != self.request.user:
            create_notification(
                product.artist.user,
                "New Comment",
                f"{self.request.user.username} commented on your artwork “{product.title}”.",
                "comment",
                {"product_id": product.id, "comment": True},
            )

class ToggleProductLikeView(generics.GenericAPIView):
    """
    POST — toggles a like on/off for the current user on a product.
    Returns {"liked": true/false, "like_count": <int>}.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        product = get_object_or_404(Product, id=self.kwargs["product_id"])
        like, created = Like.objects.get_or_create(customer=request.user, product=product)
        if not created:
            like.delete()
            liked = False
        else:
            liked = True
            
            if product.artist and product.artist.user != request.user:
                create_notification(
                    product.artist.user,
                    "New Like",
                    f"{request.user.username} liked your artwork “{product.title}”.",
                    "favorite",
                    {"product_id": product.id},
                )
        return Response({"liked": liked, "like_count": product.likes.count()})
    
class CreateReviewView(generics.CreateAPIView):
    """
    Customer submits a review for a delivered conversation.
    Expects: {"conversation": <id>, "rating": 1-5, "comment": "..."}
    """
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]


class ProductReviewsListView(generics.ListAPIView):
    """
    Public list of reviews for a given product.
    """
    pagination_class = StandardResultsPagination
    serializer_class = ReviewSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        product_id = self.kwargs["product_id"]
        return Review.objects.filter(product_id=product_id).order_by("-created_at")


class MyReviewableConversationsView(generics.ListAPIView):
    """
    Lists the logged-in customer's delivered conversations that
    haven't been reviewed yet — used to show "rate this order" prompts.
    """
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        reviewed_ids = Review.objects.filter(customer=self.request.user).values_list("conversation_id", flat=True)
        return Conversation.objects.filter(
            customer=self.request.user,
            status=Conversation.STATUS_DELIVERED,
        ).exclude(id__in=reviewed_ids)        

class MyArtistAnalyticsView(generics.GenericAPIView):
    """
    Artist-only dashboard: views, favorites, ratings, and response rate
    across all of the logged-in artist's products.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        artist_profile = get_artist_profile_for_user(request.user)
        if artist_profile is None:
            return Response({"detail": "Profil artiste introuvable."}, status=404)

        products = Product.objects.filter(artist=artist_profile)

        total_views = sum(p.view_count for p in products)
        total_favorites = Favorite.objects.filter(product__artist=artist_profile).count()

        all_reviews = Review.objects.filter(product__artist=artist_profile)
        review_count = all_reviews.count()
        average_rating = (
            round(sum(r.rating for r in all_reviews) / review_count, 1) if review_count else None
        )

        conversations = Conversation.objects.filter(product__artist=artist_profile)
        total_conversations = conversations.count()
        responded_conversations = conversations.filter(
            messages__sender__artist_profile=artist_profile
        ).distinct().count()
        response_rate = (
            round((responded_conversations / total_conversations) * 100, 1)
            if total_conversations else None
        )

        per_product = [
            {
                "id": p.id,
                "title": p.title,
                "view_count": p.view_count,
                "favorite_count": p.favorited_by.count(),
                "average_rating": (
                    round(sum(r.rating for r in p.reviews.all()) / p.reviews.count(), 1)
                    if p.reviews.count() else None
                ),
                "review_count": p.reviews.count(),
            }
            for p in products
        ]

        return Response({
            "total_views": total_views,
            "total_favorites": total_favorites,
            "average_rating": average_rating,
            "review_count": review_count,
            "total_conversations": total_conversations,
            "response_rate": response_rate,
            "products": per_product,
        })    

class CreateCommissionRequestView(generics.CreateAPIView):
    """
    Customer posts a new commission request.
    """
    serializer_class = CommissionRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        commission = serializer.save(customer=self.request.user)
        # Notify all active artists so they don't miss out on requests
        matching_artists = ArtistProfile.objects.filter(is_suspended=False)
        for artist in matching_artists:
            create_notification(
                artist.user,
                "New artwork request",
                f"{commission.customer.username} is looking for {commission.get_category_display().lower()}: “{commission.title}”.",
                "commission_request",
                {"commission_id": commission.id},
            )


class MyCommissionRequestsView(generics.ListAPIView):
    """
    Customer's own commission requests, with all responses included.
    """
    serializer_class = CommissionRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return CommissionRequest.objects.filter(customer=self.request.user).order_by("-created_at")


class OpenCommissionRequestsListView(generics.ListAPIView):
    """
    Artists browse open commission requests.
    Supports optional ?category=<code> and ?region=<code> filters.
    """
    pagination_class = StandardResultsPagination
    serializer_class = CommissionRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = CommissionRequest.objects.filter(status=CommissionRequest.STATUS_OPEN)

        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category=category)

        region = self.request.query_params.get("region")
        if region:
            queryset = queryset.filter(region=region)

        return queryset.order_by("-created_at")


class RespondToCommissionView(generics.CreateAPIView):
    """
    Artist responds to a commission request with a message and optional price.
    Expects: {"commission": <id>, "message": "...", "proposed_price_xaf": <int, optional>}
    """
    serializer_class = CommissionResponseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        artist_profile = get_artist_profile_for_user(self.request.user)
        if artist_profile is None:
            raise PermissionDenied("Only artists can respond to requests.")

        commission_id = self.request.data.get("commission")
        commission = get_object_or_404(CommissionRequest, id=commission_id, status=CommissionRequest.STATUS_OPEN)

        response = serializer.save(commission=commission, artist=artist_profile)

        create_notification(
            commission.customer,
            "New response to your request",
            f"{artist_profile.brand_name} is interested in \"{commission.title}\"",
            "commission_response",
            {"commission_id": commission.id},
        )


class UpdateCommissionStatusView(generics.UpdateAPIView):
    """
    Customer updates their own commission request's status.
    Expects: PATCH {"status": "in_progress" | "completed" | "cancelled"}
    """
    serializer_class = CommissionRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return CommissionRequest.objects.filter(customer=self.request.user)

    def patch(self, request, *args, **kwargs):
        commission = self.get_object()
        new_status = request.data.get("status")

        allowed = [
            CommissionRequest.STATUS_IN_PROGRESS,
            CommissionRequest.STATUS_COMPLETED,
            CommissionRequest.STATUS_CANCELLED,
        ]
        if new_status not in allowed:
            return Response({"detail": "Invalid status."}, status=400)

        commission.status = new_status
        commission.save()
        return Response(CommissionRequestSerializer(commission).data)        

class SiteSettingsView(generics.RetrieveUpdateAPIView):
    """
    Staff-only: view/update global site settings — currently just
    whether new products require manual admin approval before going live.
    """
    serializer_class = SiteSettingsSerializer
    permission_classes = [IsSuperAdmin]

    def get_object(self):
        return SiteSettings.get_solo()

class AssistantChatView(generics.GenericAPIView):
    """
    Chat with Sanaa, the AI assistant. Stateless — frontend sends full
    conversation history each time.
    Expects: {"message": "...", "history": [{"role": "user"/"assistant", "content": "..."}]}

    The endpoint is reachable without an account so the landing page can be
    tried, but it costs a paid model call per message, so it is rate limited.
    """
    permission_classes = []
    authentication_classes = [JWTAuthentication]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sanaa"

    def post(self, request, *args, **kwargs):
        message = (request.data.get("message") or "").strip()
        history = request.data.get("history") or []

        if not message:
            return Response({"detail": "Message required."}, status=400)
        if len(message) > 1000:
            return Response({"detail": "Message too long (1000 characters maximum)."}, status=400)
        if not isinstance(history, list) or len(history) > 20:
            return Response({"detail": "Invalid history."}, status=400)

        # Parse the constraints once and share them, so the artworks Sanaa shows
        # and the artists she names always come from the same filter. An empty
        # category is widened and announced; an empty budget never is.
        if should_load_catalogue(message, history):
            candidate_products, ranked_artists, widened_category = resolve_catalogue(message)
        else:
            # "hi" and "how does the app work" get no catalogue at all, so the
            # model is neither billed for nor tempted by artworks nobody asked for.
            candidate_products, ranked_artists, widened_category = [], [], None
        should_recommend = wants_recommendations(message)

        subscription_data = None
        my_products = None
        artist_profile = None
        if request.user.is_authenticated:
            try:
                artist_profile = ArtistProfile.objects.get(user=request.user)
                subscription = Subscription.objects.get(artist=artist_profile)
                last_payment = (
                    subscription.payments
                    .filter(status__in=["SUCCESSFUL", "SUCCESS", "COMPLETED"])
                    .first()
                )
                subscription_data = {
                    "status": subscription.status,
                    "status_display": subscription.get_status_display(),
                    "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
                    "trial_start_date": subscription.trial_start_date.isoformat() if subscription.trial_start_date else None,
                    "trial_end_date": subscription.trial_end_date.isoformat() if subscription.trial_end_date else None,
                    "monthly_price_xaf": subscription.monthly_price_xaf,
                    "last_payment_id": subscription.last_payment_id or None,
                    "last_payment_date": last_payment.created_at.isoformat() if last_payment else None,
                    "last_payment_amount_xaf": last_payment.amount_xaf if last_payment else None,
                    "is_active": subscription.is_active,
                }
            except (ArtistProfile.DoesNotExist, Subscription.DoesNotExist):
                pass

            if artist_profile is not None:
                my_products = get_my_products(artist_profile)

        try:
            reply, product_ids, artist_ids, degraded = ask_sanaa(
                message, history,
                candidate_products=candidate_products,
                candidate_artists=ranked_artists,
                is_artist=bool(getattr(request.user, "is_artist", False)),
                user_name=request.user.username if request.user.is_authenticated else "",
                subscription_data=subscription_data,
                my_products=my_products,
                widened_category=widened_category,
            )
        except Exception:
            # Never leak the provider's error text, key fragments or stack trace
            # to the client; the operator gets the trace instead.
            logger.exception("Sanaa chat failed for message %r", message[:80])
            return Response(
                {"detail": "The assistant is temporarily unavailable. Please try again in a moment."},
                status=503,
            )

        product_by_id = {str(product.id): product for product in candidate_products}
        recommended_products = [
            product_by_id[pid] for pid in product_ids if pid in product_by_id
        ]

        valid_artist_ids = {str(artist.id) for artist in ranked_artists}
        if not artist_ids and should_recommend:
            # The model picked nobody. Falling back to the plain ranking is fine
            # as long as we only do it for an actual shopping question, and as long
            # as it stays limited to artists who have matching work available.
            artist_ids = [str(artist.id) for artist in ranked_artists]
        artist_by_id = {str(artist.id): artist for artist in ranked_artists}
        recommended_artists = [artist_by_id[aid] for aid in artist_ids if aid in valid_artist_ids]

        try:
            recommended_products_data = ProductSerializer(
                recommended_products, many=True, context={"request": request}
            ).data
            recommended_artists_data = ArtistPublicSerializer(recommended_artists, many=True).data
        except Exception:
            # A single malformed record must not cost the user their whole answer.
            logger.exception("Sanaa recommendation serialisation failed")
            return Response(
                {"reply": reply, "recommended_products": [], "recommended_artists": [], "degraded": True},
                status=200,
            )

        return Response({
            "reply": reply,
            "recommended_products": recommended_products_data,
            "recommended_artists": recommended_artists_data,
            "degraded": degraded,
        })


class ArtistProfileDetailView(generics.RetrieveAPIView):
    """
    Public artist profile — shows only public info.
    """
    serializer_class = ArtistPublicSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return ArtistProfile.objects.all()


class AdminArtistListView(generics.ListAPIView):
    """
    Staff-only list of all artists with full personal info.
    """
    serializer_class = AdminArtistSerializer
    permission_classes = [IsSuperAdmin]
    queryset = ArtistProfile.objects.all().select_related("user").order_by("-created_at")


class AdminArtistVerifyView(generics.UpdateAPIView):
    """
    Staff-only verify/unverify an artist.
    """
    serializer_class = AdminArtistSerializer
    permission_classes = [IsSuperAdmin]
    queryset = ArtistProfile.objects.all()

    def patch(self, request, *args, **kwargs):
        artist = self.get_object()
        is_verified = request.data.get("is_verified")
        if is_verified is None:
            return Response({"detail": "is_verified is required."}, status=400)
        artist.is_verified = bool(is_verified)
        artist.verified_at = timezone.now() if artist.is_verified else None
        artist.save(update_fields=["is_verified", "verified_at"])
        return Response(AdminArtistSerializer(artist, context={"request": request}).data)


class AdminArtistSuspendView(generics.UpdateAPIView):
    """
    Staff-only suspend/unsuspend an artist.
    """
    serializer_class = AdminArtistSerializer
    permission_classes = [IsSuperAdmin]
    queryset = ArtistProfile.objects.all()

    def patch(self, request, *args, **kwargs):
        artist = self.get_object()
        is_suspended = request.data.get("is_suspended")
        reason = request.data.get("reason", "")
        if is_suspended is None:
            return Response({"detail": "is_suspended is required."}, status=400)
        artist.is_suspended = bool(is_suspended)
        artist.suspended_at = timezone.now() if artist.is_suspended else None
        artist.suspension_reason = reason if artist.is_suspended else ""
        artist.save(update_fields=["is_suspended", "suspended_at", "suspension_reason"])
        return Response(AdminArtistSerializer(artist, context={"request": request}).data)


class ProductImageDeleteView(generics.DestroyAPIView):
    queryset = ProductImage.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        obj = super().get_object()
        artist_profile = get_artist_profile_for_user(self.request.user)
        if artist_profile is None or obj.product.artist_id != artist_profile.id:
            raise PermissionDenied("Vous ne pouvez pas supprimer cette image.")
        return obj


class AdminDashboardStatsView(drf_views.APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, *args, **kwargs):
        from django.db.models import Q
        from billing.models import Subscription
        from django.contrib.auth import get_user_model
        User = get_user_model()

        total_products = Product.objects.count()
        pending_products = Product.objects.filter(status=Product.STATUS_PENDING).count()
        approved_products = Product.objects.filter(status=Product.STATUS_APPROVED).count()
        rejected_products = Product.objects.filter(status=Product.STATUS_REJECTED).count()

        total_artists = ArtistProfile.objects.count()
        total_customers = User.objects.filter(role=User.ROLE_CUSTOMER).count()

        total_conversations = Conversation.objects.count()
        negotiating = Conversation.objects.filter(status=Conversation.STATUS_NEGOTIATING).count()
        confirmed = Conversation.objects.filter(status=Conversation.STATUS_CONFIRMED).count()
        delivered = Conversation.objects.filter(status=Conversation.STATUS_DELIVERED).count()
        cancelled = Conversation.objects.filter(status=Conversation.STATUS_CANCELLED).count()

        top_artists = []
        for artist in ArtistProfile.objects.annotate(pcount=Count("products")).order_by("-pcount")[:5]:
            top_artists.append({
                "brand_name": artist.brand_name,
                "product_count": artist.products.count(),
            })

        artists_by_region = []
        for region_code, region_label in ArtistProfile.REGION_CHOICES:
            count = ArtistProfile.objects.filter(region=region_code).count()
            if count:
                artists_by_region.append({
                    "region": region_code,
                    "region_display": region_label,
                    "count": count,
                })

        products_by_category = []
        for category_code, category_label in Product.CATEGORY_CHOICES:
            count = Product.objects.filter(category=category_code).count()
            if count:
                products_by_category.append({
                    "category": category_code,
                    "category_display": category_label,
                    "count": count,
                })

        total_subscriptions = Subscription.objects.count()
        trial_count = Subscription.objects.filter(status=Subscription.STATUS_TRIAL).count()
        active_count = Subscription.objects.filter(status=Subscription.STATUS_ACTIVE).count()
        expired_count = Subscription.objects.filter(status=Subscription.STATUS_EXPIRED).count()
        cancelled_count = Subscription.objects.filter(status=Subscription.STATUS_CANCELLED).count()

        return Response({
            "products": {
                "total": total_products,
                "pending": pending_products,
                "approved": approved_products,
                "rejected": rejected_products,
            },
            "users": {
                "total_artists": total_artists,
                "total_customers": total_customers,
            },
            "orders": {
                "total_conversations": total_conversations,
                "negotiating": negotiating,
                "confirmed": confirmed,
                "delivered": delivered,
                "cancelled": cancelled,
            },
            "top_artists": top_artists,
            "artists_by_region": artists_by_region,
            "products_by_category": products_by_category,
            "subscription_stats": {
                "total_artists": total_subscriptions,
                "trial_count": trial_count,
                "active_count": active_count,
                "expired_count": expired_count,
                "cancelled_count": cancelled_count,
            },
        })


class RegistrationStatsView(drf_views.APIView):
    """
    Registration analytics for the admin panel: how many clients and
    artists have signed up, the sign-up trend, and where artists are
    located. Clients do not carry a region on their profile, so the
    region breakdown covers artists only.
    """
    permission_classes = [IsSuperAdmin]

    def get(self, request, *args, **kwargs):
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from datetime import timedelta

        User = get_user_model()
        now = timezone.now()

        customers = User.objects.filter(role=User.ROLE_CUSTOMER)
        artists = User.objects.filter(role=User.ROLE_ARTIST)
        total_customers = customers.count()
        total_artists = artists.count()
        total_members = total_customers + total_artists

        def _count_since(queryset, days):
            return queryset.filter(
                date_joined_platform__gte=now - timedelta(days=days)
            ).count()

        # Every region is listed — even with zero artists — so the table
        # doubles as a coverage map of the marketplace.
        artists_by_region = []
        for region_code, region_label in ArtistProfile.REGION_CHOICES:
            count = ArtistProfile.objects.filter(region=region_code).count()
            artists_by_region.append({
                "region": region_code,
                "region_display": region_label,
                "count": count,
                "share_pct": round(count * 100 / total_artists, 1) if total_artists else 0,
            })
        artists_by_region.sort(key=lambda entry: entry["count"], reverse=True)

        # Day-by-day sign-ups for the last two weeks.
        trend = []
        for offset in range(13, -1, -1):
            day = (now - timedelta(days=offset)).date()
            trend.append({
                "date": day.isoformat(),
                "customers": customers.filter(date_joined_platform__date=day).count(),
                "artists": artists.filter(date_joined_platform__date=day).count(),
            })

        return Response({
            "totals": {
                "customers": total_customers,
                "artists": total_artists,
                "total_members": total_members,
                "artist_share_pct": round(total_artists * 100 / total_members, 1) if total_members else 0,
            },
            "recent": {
                "customers_last_7d": _count_since(customers, 7),
                "artists_last_7d": _count_since(artists, 7),
                "customers_last_30d": _count_since(customers, 30),
                "artists_last_30d": _count_since(artists, 30),
            },
            "artists_by_region": artists_by_region,
            "trend": trend,
        })


class ResumeCancelledConversationView(generics.GenericAPIView):
    """
    A customer who cancelled a conversation can resume it instead of starting a
    brand-new one (which would violate the unique (product, customer) constraint).

    PATCH /catalog/conversations/<id>/resume/  →  { "status": "negotiating" }
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk, *args, **kwargs):
        conversation = get_object_or_404(conversations_visible_to_user(request.user), id=pk)
        if conversation.customer_id != request.user.id:
            return Response({"detail": "Only the customer can resume a conversation."}, status=403)
        if conversation.status != Conversation.STATUS_CANCELLED:
            return Response({"detail": "This conversation is not cancelled."}, status=400)
        conversation.status = Conversation.STATUS_NEGOTIATING
        conversation.cancelled_at = None
        conversation.save(update_fields=["status", "cancelled_at"])
        return Response({"status": conversation.status, "resumed": True})


class SanaaImageRankView(generics.GenericAPIView):
    """
    Sanaa analyses an uploaded reference drawing/photo and ranks the best-matching
    artists. Gemini vision classifies the image into one of the real product
    categories; that category becomes a database filter; the artists are then
    ranked with the same score used for text queries.

    POST /catalog/assistant/image-rank/  (multipart: image, message?)
    """
    permission_classes = []
    authentication_classes = [JWTAuthentication]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sanaa_image"
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        image = request.data.get("image")
        message = (request.data.get("message") or "").strip()
        if not image:
            return Response({"detail": "Image is required."}, status=400)
        if len(message) > 1000:
            return Response({"detail": "Message too long (1000 characters maximum)."}, status=400)

        # Trust the declared content type, but only among the three we accept.
        # The extension comes from our own allowlist, never from the uploaded
        # filename, so a crafted name cannot decide where anything is written.
        content_type = (getattr(image, "content_type", "") or "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_IMAGE_TYPES:
            return Response(
                {"detail": "Unsupported format. Use JPG, PNG, or WEBP."},
                status=400,
            )

        upload_dir = Path(settings.MEDIA_ROOT) / "sanaa_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / f"{uuid.uuid4().hex}{ALLOWED_IMAGE_TYPES[content_type]}"

        try:
            size = self._write_upload(image, dest)
        except ValueError as exc:
            return Response({"detail": f"Image rejected: {exc}"}, status=400)
        except OSError:
            logger.exception("Sanaa image upload could not be written")
            return Response({"detail": "Unreadable image."}, status=400)

        try:
            # The local path is handed to the model helper, never a URL built from
            # the request's Host header: nothing here makes an outbound request to
            # a host the caller controls.
            ranked, category = rank_artists_by_image(
                str(dest), message=message, content_type=content_type, limit=5
            )
        except Exception:
            logger.exception("Sanaa image rank failed")
            return Response(
                {"detail": "The assistant could not analyze this image. Please try again."},
                status=503,
            )
        finally:
            # The upload is an input to one model call and nothing else; it never
            # needs to be publicly served.
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove Sanaa upload %s", dest)

        if not ranked:
            return Response({
                "artists": [],
                "category": category,
                "reply": "No available artist matches this image at the moment.",
            })

        payload = SanaaArtistRecommendationSerializer(
            ranked, many=True, context={"request": request}
        ).data
        return Response({
            "artists": payload,
            "category": category,
            "reply": (
                "Here are the available artists working in this style."
                if category
                else "I couldn't classify this image, here are the top-rated artists."
            ),
        })

    @staticmethod
    def _write_upload(image, dest: Path) -> int:
        """Stream the upload to disk, aborting as soon as it exceeds the cap."""
        request_file = getattr(image, "file", None) or image
        written = 0
        with open(dest, "wb") as out:
            if hasattr(request_file, "chunks"):
                for chunk in request_file.chunks():
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        out.close()
                        dest.unlink(missing_ok=True)
                        raise ValueError(f"image trop lourde (max {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo)")
                    out.write(chunk)
            else:
                data = request_file.read() if hasattr(request_file, "read") else b""
                written = len(data)
                if written > MAX_UPLOAD_BYTES:
                    raise ValueError(f"image trop lourde (max {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo)")
                out.write(data)

        if written == 0:
            dest.unlink(missing_ok=True)
            raise ValueError("image vide")
        return written
