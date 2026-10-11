from django.utils import timezone

# Only write last_seen once per interval. The old version
# updated the row on every authenticated request, which
# meant one DB write per API call for every active user.
LAST_SEEN_INTERVAL = timezone.timedelta(minutes=5)


class UpdateLastSeenMiddleware:
    """
    Updates the logged-in user's last_seen timestamp, at most
    once per interval. This approximates "online" status without
    a database write on every request.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            last_seen = user.last_seen
            if last_seen is None or (timezone.now() - last_seen) >= LAST_SEEN_INTERVAL:
                from .models import User
                User.objects.filter(id=user.id).update(last_seen=timezone.now())

        return response
