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
                "New Favorite",
                f"{request.user.username} favorited your artwork “{product.title}”.",
                "product_status",
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
                    "product_status",
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
    Analytics dashboard for the logged-in artist: views, favorites,
    average rating, and message response rate across their products.
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

        # Response rate: % of conversations where the artist has sent at least one message
        conversations = Conversation.objects.filter(product__artist=artist_profile)
        total_conversations = conversations.count()
        responded_conversations = 0
        for conv in conversations:
            if conv.messages.filter(sender=request.user).exists():
                responded_conversations += 1

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
            "total_reviews": review_count,
            "average_rating": average_rating,
            "total_conversations": total_conversations,
            "response_rate": response_rate,
            "products": per_product,
        })    

class MyArtistAnalyticsView(generics.GenericAPIView):
    """
    Artist-only dashboard: views, favorites, ratings, and response rate
