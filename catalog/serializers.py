from rest_framework import serializers
from .models import Product, ProductImage, Conversation, Message, Favorite, Review, CommissionRequest, CommissionResponse, SiteSettings
from social.models import Comment
from django.db.models import Q
from django.utils import timezone

from datetime import timedelta


ONLINE_THRESHOLD_SECONDS = 60

class SiteSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteSettings
        fields = ["id", "require_product_approval"]
        read_only_fields = ["id"]


class ProductImageSerializer(serializers.ModelSerializer):
    # This field is used both to accept the multipart file upload and to return
    # its URL.  A SerializerMethodField is read-only, which meant the upload
    # endpoint was creating ProductImage rows with an empty `image` value.
    # DRF's ImageField builds an absolute URL when the request is in context.
    image = serializers.ImageField(required=True)
    thumbnail = serializers.ImageField(read_only=True, allow_null=True)

    class Meta:
        model = ProductImage
        fields = ["id", "image", "thumbnail", "is_primary", "order"]

class ProductSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    artist_name = serializers.CharField(source="artist.brand_name", read_only=True)
    artist_phone = serializers.CharField(source="artist.user.phone_number", read_only=True)
    artist_mobile_money_number = serializers.CharField(source="artist.mobile_money_number", read_only=True)
    artist_mobile_money_provider = serializers.CharField(source="artist.mobile_money_provider", read_only=True)
    artist_region = serializers.CharField(source="artist.region", read_only=True)
    artist_region_display = serializers.CharField(source="artist.get_region_display", read_only=True)
    artist_is_verified = serializers.BooleanField(source="artist.is_verified", read_only=True)
    artist_id = serializers.IntegerField(source="artist.id", read_only=True)
    artist_user_id = serializers.IntegerField(source="artist.user_id", read_only=True)
    artist_avatar = serializers.ImageField(source="artist.avatar", read_only=True)
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "title", "description", "price_xaf", "status", "category", "category_display",
            "public_slug", "public_url", "artist_name", "artist_phone",
            "artist_mobile_money_number", "artist_mobile_money_provider",
            "artist_id", "artist_user_id", "artist_avatar", "artist_region", "artist_region_display", "artist_is_verified",
            "is_sold", "sold_at",
            "average_rating", "review_count", "like_count", "comment_count", "view_count",
            "images", "created_at",
        ]
        read_only_fields = ["status", "public_slug", "public_url", "created_at", "is_sold", "sold_at"]

    def get_average_rating(self, obj):
        reviews = obj.reviews.all()
        if not reviews:
            return None
        return round(sum(r.rating for r in reviews) / len(reviews), 1)

    def get_review_count(self, obj):
        return obj.reviews.count()

    def get_like_count(self, obj):
        return obj.favorited_by.count()

    def get_comment_count(self, obj):
        return obj.comments.count()


class MessageReplySerializer(serializers.ModelSerializer):
    """The compact source-message preview embedded in a reply."""

    sender_username = serializers.CharField(source="sender.username", read_only=True)

    class Meta:
        model = Message
        fields = ["id", "sender", "sender_username", "message_type", "text"]


class MessageSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source="sender.username", read_only=True)
    read = serializers.SerializerMethodField()
    map_url = serializers.SerializerMethodField()
    reply_to = MessageReplySerializer(read_only=True)
    reply_to_id = serializers.PrimaryKeyRelatedField(
        source="reply_to",
        queryset=Message.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )
    reactions = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id", "conversation", "sender", "sender_username",
            "message_type", "text", "latitude", "longitude", "map_url",
            "image", "document", "audio", "reply_to", "reply_to_id", "reactions", "read", "created_at", "edited_at", "is_forwarded",
        ]
        read_only_fields = ["sender", "conversation", "edited_at", "is_forwarded"]

    def get_map_url(self, obj):
        """A Google Maps link for a location message.

        Returned as a URL so any client (app, web, or a copied link) can open
        the point in Google Maps without re-implementing the coordinates.
        """
        if obj.latitude is None or obj.longitude is None:
            return None
        return (
            "https://www.google.com/maps/search/?api=1"
            f"&query={obj.latitude},{obj.longitude}"
        )

    def get_read(self, obj):
        conversation = obj.conversation
        if conversation.product:
            artist_user = getattr(conversation.product.artist, "user", None)
        else:
            artist_user = conversation.commission_response.artist.user

        sender_is_artist = artist_user is not None and obj.sender_id == artist_user.id

        relevant_last_read = (
            conversation.customer_last_read_at if sender_is_artist else conversation.artist_last_read_at
        )

        if relevant_last_read is None:
            return False
        return relevant_last_read >= obj.created_at

    def get_reactions(self, obj):
        request = self.context.get("request")
        viewer_id = request.user.id if request and request.user.is_authenticated else None
        grouped = {}

        for reaction in obj.reactions.all():
            entry = grouped.setdefault(
                reaction.emoji,
                {"emoji": reaction.emoji, "count": 0, "reacted_by_me": False},
            )
            entry["count"] += 1
            if reaction.user_id == viewer_id:
                entry["reacted_by_me"] = True

        return list(grouped.values())
    

class ConversationSerializer(serializers.ModelSerializer):
    product_title = serializers.SerializerMethodField()
    customer_username = serializers.CharField(source="customer.username", read_only=True)
    artist_id = serializers.SerializerMethodField()
    artist_name = serializers.SerializerMethodField()
    artist_avatar = serializers.SerializerMethodField()
    artist_is_verified = serializers.SerializerMethodField()
    messages = MessageSerializer(many=True, read_only=True)
    unread = serializers.SerializerMethodField()
    other_user_online = serializers.SerializerMethodField()
    other_user_typing = serializers.SerializerMethodField()
    contact = serializers.SerializerMethodField()
    product_id = serializers.SerializerMethodField()
    product_price_xaf = serializers.SerializerMethodField()
    product_image = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "product", "product_title", "commission_response", "customer", "customer_username",
            "artist_id", "artist_name", "artist_avatar", "artist_is_verified",
            "status", "unread", "other_user_online", "other_user_typing", "is_reported", "report_reason",
            "reported_at", "created_at", "messages", "contact",
            "product_id", "product_price_xaf", "product_image",
        ]
        read_only_fields = ["id", "customer", "customer_username", "product", "commission_response", "status", "created_at"]

    def get_product_title(self, obj):
        if obj.product:
            return obj.product.title
        # A commission conversation has no product. Without this fallback the
        # conversation list renders a blank title for these rows.
        if obj.commission_response:
            return obj.commission_response.commission.title
        return None

    def get_artist_id(self, obj):
        if obj.product:
            return obj.product.artist.id
        return obj.commission_response.artist.id

    def get_product_id(self, obj):
        return obj.product.id if obj.product else None

    def get_product_price_xaf(self, obj):
        return obj.product.price_xaf if obj.product else None

    def get_product_image(self, obj):
        if not obj.product:
            return None
        primary = next(
            (image for image in obj.product.images.all() if image.is_primary),
            None,
        ) or obj.product.images.first()
        if not primary:
            return None
        return self._absolute_url(primary.image)

    def get_artist_name(self, obj):
        if obj.product:
            return obj.product.artist.brand_name
        return obj.commission_response.artist.brand_name

    def get_artist_avatar(self, obj):
        artist = obj.product.artist if obj.product else obj.commission_response.artist
        if not artist.avatar:
            return None
        # Must return a URL string. Returning the FieldFile itself makes DRF's
        # JSON encoder fall through to its __iter__ branch, which walks the
        # binary chunks of the file and fails on non-UTF-8 bytes.
        request = self.context.get("request")
        return request.build_absolute_uri(artist.avatar.url) if request else artist.avatar.url

    def get_artist_is_verified(self, obj):
        if obj.product:
            return obj.product.artist.is_verified
        return obj.commission_response.artist.is_verified

    def _absolute_url(self, file_field):
        if not file_field:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(file_field.url) if request else file_field.url

    def get_contact(self, obj):
        """
        Contact details for BOTH participants so the chat can show the
        customer and the artist on a single "View contact" screen.

        Only the two participants can ever receive this: every conversation
        endpoint uses conversations_visible_to_user(). Phone numbers follow the
        same rules as the existing profile endpoints — the customer sees the
        artist's number, and the artist only sees the customer's number once an
        order is confirmed or delivered. Commission conversations are matched as
        well, which the older product-only check missed.
        """
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None

        user = request.user
        customer = obj.customer
        artist = obj.product.artist if obj.product else obj.commission_response.artist
        viewer_is_customer = user.id == customer.id

        artist_can_reach_customer = Conversation.objects.filter(
            Q(product__artist=artist) | Q(commission_response__artist=artist),
            customer=customer,
            status__in=[Conversation.STATUS_CONFIRMED, Conversation.STATUS_DELIVERED],
        ).exists()

        return {
            "viewer_is_customer": viewer_is_customer,
            "customer": {
                "id": customer.id,
                "username": customer.username,
                "profile_photo": self._absolute_url(customer.profile_photo),
                "phone_number": None if viewer_is_customer or not artist_can_reach_customer else customer.phone_number,
                "member_since": customer.date_joined_platform,
            },
            "artist": {
                "id": artist.id,
                "brand_name": artist.brand_name,
                "avatar": self._absolute_url(artist.avatar),
                "region": artist.region,
                "region_display": artist.get_region_display(),
                "is_verified": artist.is_verified,
                "phone_number": artist.user.phone_number if viewer_is_customer else None,
                "mobile_money_number": artist.mobile_money_number if viewer_is_customer else None,
                "mobile_money_provider": artist.mobile_money_provider if viewer_is_customer else None,
            },
        }

    def get_unread(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False

        user = request.user
        artist_profile = getattr(user, "artist_profile", None)
        is_artist_side = artist_profile is not None and self._get_artist_id(obj) == artist_profile.id

        last_read = obj.artist_last_read_at if is_artist_side else obj.customer_last_read_at

        last_message = obj.messages.order_by("-created_at").first()
        if last_message is None:
            return False

        if last_message.sender_id == user.id:
            return False

        if last_read is None:
            return True

        return last_message.created_at > last_read

    def get_other_user_online(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False

        user = request.user
        artist_profile = getattr(user, "artist_profile", None)
        is_artist_side = artist_profile is not None and self._get_artist_id(obj) == artist_profile.id

        if is_artist_side:
            other_user = obj.customer
        else:
            if obj.product:
                other_user = obj.product.artist.user
            else:
                other_user = obj.commission_response.artist.user

        if other_user.last_seen is None:
            return False

        return timezone.now() - other_user.last_seen < timedelta(seconds=ONLINE_THRESHOLD_SECONDS)

    def get_other_user_typing(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        user = request.user
        artist_profile = getattr(user, "artist_profile", None)
        is_artist_side = artist_profile is not None and self._get_artist_id(obj) == artist_profile.id
        typing_until = obj.customer_typing_until if is_artist_side else obj.artist_typing_until
        return typing_until is not None and typing_until > timezone.now()

    def _get_artist_id(self, obj):
        if obj.product:
            return obj.product.artist_id
        return obj.commission_response.artist_id

    def get_read(self, obj):
        relevant_last_read = obj.customer_last_read_at
        if relevant_last_read is None:
            return False
        return relevant_last_read >= obj.created_at

class FavoriteSerializer(serializers.ModelSerializer):
    product_detail = ProductSerializer(source="product", read_only=True)

    class Meta:
        model = Favorite
        fields = ["id", "product", "product_detail", "created_at"]
        read_only_fields = ["id", "created_at"]


class ProductCommentSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="customer.username", read_only=True)

    class Meta:
        model = Comment
        fields = ["id", "product", "customer", "username", "text", "created_at"]
        read_only_fields = ["id", "product", "customer", "username", "created_at"]


class ReviewSerializer(serializers.ModelSerializer):
    customer_username = serializers.CharField(source="customer.username", read_only=True)

    class Meta:
        model = Review
        fields = ["id", "product", "customer", "customer_username", "conversation", "rating", "comment", "created_at"]
        read_only_fields = ["id", "customer", "customer_username", "product", "created_at"]

    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value

    def validate(self, attrs):
        conversation = attrs.get("conversation")
        request = self.context["request"]

        if conversation.customer_id != request.user.id:
            raise serializers.ValidationError("You can only rate your own orders.")

        if conversation.status != Conversation.STATUS_DELIVERED:
            raise serializers.ValidationError("You can only rate a delivered order.")

        if Review.objects.filter(conversation=conversation, customer=request.user).exists():
            raise serializers.ValidationError("You have already rated this order.")

        return attrs

    def create(self, validated_data):
        validated_data["customer"] = self.context["request"].user
        validated_data["product"] = validated_data["conversation"].product
        return super().create(validated_data)


class CommissionResponseSerializer(serializers.ModelSerializer):
    artist_name = serializers.CharField(source="artist.brand_name", read_only=True)
    artist_avatar = serializers.ImageField(source="artist.avatar", read_only=True)
    artist_phone = serializers.CharField(source="artist.user.phone_number", read_only=True)
    artist_is_verified = serializers.BooleanField(source="artist.is_verified", read_only=True)
    artist_id = serializers.IntegerField(source="artist.id", read_only=True)

    class Meta:
        model = CommissionResponse
        fields = [
            "id", "commission", "artist_id", "artist_name", "artist_avatar",
            "artist_phone", "artist_is_verified", "message", "proposed_price_xaf", "created_at",
        ]
        read_only_fields = ["id", "commission", "created_at"]

    def validate(self, attrs):
        commission = attrs.get("commission") or self.instance.commission if self.instance else None
        request = self.context["request"]
        artist_profile = getattr(request.user, "artist_profile", None)

        if artist_profile is None:
            raise serializers.ValidationError("Only artists can respond to a request.")

        if commission and commission.status != CommissionRequest.STATUS_OPEN:
            raise serializers.ValidationError("This request is no longer open.")

        if commission and CommissionResponse.objects.filter(commission=commission, artist=artist_profile).exists():
            raise serializers.ValidationError("You have already responded to this request.")

        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["artist"] = request.user.artist_profile
        return super().create(validated_data)


class CommissionRequestSerializer(serializers.ModelSerializer):
    customer_username = serializers.CharField(source="customer.username", read_only=True)
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    region_display = serializers.CharField(source="get_region_display", read_only=True)
    responses = CommissionResponseSerializer(many=True, read_only=True)
    response_count = serializers.SerializerMethodField()

    class Meta:
        model = CommissionRequest
        fields = [
            "id", "customer", "customer_username", "title", "description",
            "category", "category_display", "budget_xaf", "region", "region_display",
            "status", "responses", "response_count", "created_at",
        ]
        read_only_fields = ["id", "customer", "customer_username", "status", "created_at"]

    def get_response_count(self, obj):
        return obj.responses.count()

    def create(self, validated_data):
        validated_data["customer"] = self.context["request"].user
        return super().create(validated_data)



from accounts.models import ArtistProfile, User


class ArtistPublicSerializer(serializers.ModelSerializer):
    region_display = serializers.CharField(source="get_region_display", read_only=True)
    gender_display = serializers.CharField(source="get_gender_display", read_only=True)
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = ArtistProfile
        fields = [
            "id", "brand_name", "bio", "artistic_practice", "avatar",
            "region", "region_display", "gender", "gender_display",
            "is_verified", "product_count",
        ]

    def get_product_count(self, obj):
        return obj.products.count()


class ArtistPrivateSerializer(serializers.ModelSerializer):
    region_display = serializers.CharField(source="get_region_display", read_only=True)
    gender_display = serializers.CharField(source="get_gender_display", read_only=True)

    # An artist editing their own profile must not be able to move their region,
    # change their gender, or grant themselves the verified badge. `is_verified`
    # feeds Sanaa's ranking score, so a self-awarded badge would be a paid
    # placement the artist bought for free. These are decided by the FNAAD team
    # through the admin endpoints.
    region = serializers.CharField(read_only=True)
    gender = serializers.CharField(read_only=True)
    is_verified = serializers.BooleanField(read_only=True)
    is_suspended = serializers.BooleanField(read_only=True)
    suspension_reason = serializers.CharField(read_only=True)

    class Meta:
        model = ArtistProfile
        fields = [
            "id", "brand_name", "bio", "artistic_practice", "instagram_handle",
            "portfolio_url", "avatar", "region", "region_display",
            "gender", "gender_display", "mobile_money_number",
            "mobile_money_provider", "is_verified", "national_id_number",
            "is_suspended", "suspension_reason", "created_at",
        ]


class AdminArtistSerializer(serializers.ModelSerializer):
    region_display = serializers.CharField(source="get_region_display", read_only=True)
    gender_display = serializers.CharField(source="get_gender_display", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_phone = serializers.CharField(source="user.phone_number", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = ArtistProfile
        fields = [
            "id", "user_email", "user_username", "user_phone",
            "brand_name", "bio", "artistic_practice", "instagram_handle",
            "portfolio_url", "avatar", "region", "region_display",
            "gender", "gender_display", "mobile_money_number",
            "mobile_money_provider", "is_verified", "national_id_number",
            "is_suspended", "suspension_reason", "created_at", "verified_at", "suspended_at",
            "product_count",
        ]

    def get_product_count(self, obj):
        return obj.products.count()


class ArtistProductsSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "title", "description", "price_xaf", "status", "category",
            "category_display", "public_slug", "is_sold", "sold_at",
            "average_rating", "review_count", "view_count", "images", "created_at",
        ]

    def get_average_rating(self, obj):
        reviews = obj.reviews.all()
        if not reviews:
            return None
        return round(sum(r.rating for r in reviews) / len(reviews), 1)

    def get_review_count(self, obj):
        return obj.reviews.count()


class AdminDashboardStatsSerializer(serializers.Serializer):
    total_artists = serializers.IntegerField()
    total_products = serializers.IntegerField()
    pending_products = serializers.IntegerField()
    total_customers = serializers.IntegerField()
    total_conversations = serializers.IntegerField()
    total_revenue = serializers.IntegerField()


class ProductImageDeleteSerializer(serializers.Serializer):
    id = serializers.IntegerField()

    id = serializers.IntegerField()
    username = serializers.CharField()
    member_since = serializers.DateTimeField(source="date_joined_platform")
    phone_number = serializers.SerializerMethodField()
    orders = serializers.SerializerMethodField()

    def get_phone_number(self, obj):
        request = self.context["request"]
        artist_profile = getattr(request.user, "artist_profile", None)
        if artist_profile is None:
            return None

        has_confirmed_order = Conversation.objects.filter(
            customer=obj,
            product__artist=artist_profile,
            status__in=[Conversation.STATUS_CONFIRMED, Conversation.STATUS_DELIVERED],
        ).exists()

        return obj.phone_number if has_confirmed_order else None

    def get_orders(self, obj):
        request = self.context["request"]
        artist_profile = getattr(request.user, "artist_profile", None)
        if artist_profile is None:
            return []

        conversations = Conversation.objects.filter(
            customer=obj, product__artist=artist_profile
        ).order_by("-created_at")

        return [
            {
                "id": c.id,
                "product_title": c.product.title,
                "status": c.status,
                "created_at": c.created_at,
            }
            for c in conversations
        ]    


from django.contrib.auth import get_user_model


class CustomerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()

        fields = ["id", "username", "email", "phone_number", "profile_photo", "role", "date_joined_platform"]


class SanaaArtistRecommendationSerializer(serializers.Serializer):
    """Artist recommendation payload returned by the Sanaa image-rank endpoint."""

    id = serializers.IntegerField()
    brand_name = serializers.CharField()
    artistic_practice = serializers.CharField(allow_null=True)
    region_display = serializers.CharField()
    is_verified = serializers.BooleanField()
    average_rating = serializers.FloatField(allow_null=True)
    review_count = serializers.IntegerField()
    like_count = serializers.IntegerField()
    matching_work_count = serializers.IntegerField()
    recommendation_score = serializers.FloatField()
    avatar = serializers.SerializerMethodField()

    def get_avatar(self, obj):
        request = self.context.get("request")
        if not obj.avatar:
            return None
        return request.build_absolute_uri(obj.avatar.url) if request else obj.avatar.url

   
