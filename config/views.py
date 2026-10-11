from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse

FAVICON_PATH = settings.BASE_DIR.parent / "fnaad-frontend" / "assets" / "favicon.png"


def api_root(request):
    """Landing endpoint for `/` and `/api/`.

    Without this the bare backend URL answered 404 and, with DEBUG=True, Django
    rendered its technical 404 page instead of something usable.
    """
    return JsonResponse(
        {
            "service": "FNAAD API",
            "status": "ok",
            "endpoints": {
                "api": "/api/",
                "admin": "/admin/",
                "auth": "/api/token/",
                "accounts": "/api/accounts/",
                "catalog": "/api/catalog/",
                "orders": "/api/orders/",
                "billing": "/api/billing/",
            },
        }
    )


def favicon(request):
    """Serve the app icon for `/favicon.ico`.

    Browsers request this whenever the API host is opened directly, and with
    DEBUG=True an unmatched path renders Django's full technical 404 page.
    """
    if FAVICON_PATH.exists():
        return FileResponse(FAVICON_PATH.open("rb"), content_type="image/png")
    return HttpResponse(status=204)
