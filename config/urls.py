"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    http://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from .views import api_root, favicon
try:
    from rest_framework_simplejwt.views import (
        TokenObtainPairView,
        TokenRefreshView,
        TokenBlacklistView,
    )
except Exception:
    # Fallback stubs if djangorestframework-simplejwt is not available.
    from django.http import HttpResponseServerError

    class _MissingJWTView:
        @staticmethod
        def as_view():
            def _view(request, *args, **kwargs):
                return HttpResponseServerError(
                    b"rest_framework_simplejwt is not installed. Install djangorestframework-simplejwt."
                )

            return _view

    TokenObtainPairView = _MissingJWTView()
    TokenRefreshView = _MissingJWTView()
    TokenBlacklistView = _MissingJWTView()

try:
    from rest_framework.throttling import ScopedRateThrottle

    class ThrottledTokenObtainPairView(TokenObtainPairView):
        """Login endpoint: per-IP rate limit to slow credential brute force."""
        throttle_classes = [ScopedRateThrottle]
        throttle_scope = "login"
except Exception:
    ThrottledTokenObtainPairView = TokenObtainPairView

urlpatterns = [
    path("", api_root, name="api-root"),
    path("favicon.ico", favicon, name="favicon"),
    path("api/", api_root, name="api-index"),
    path("admin/", admin.site.urls),
    path("api/accounts/", include("accounts.urls")),
    path("api/catalog/", include("catalog.urls")),
    path("api/token/", ThrottledTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/token/blacklist/", TokenBlacklistView.as_view(), name="token_blacklist"),
    path("api/orders/", include("orders.urls")),
    path("api/billing/", include("billing.urls")),
    # Fallback routes without /api/ prefix
    path("accounts/", include("accounts.urls")),
    path("catalog/", include("catalog.urls")),
    path("token/", ThrottledTokenObtainPairView.as_view()),
    path("token/refresh/", TokenRefreshView.as_view()),
    path("token/blacklist/", TokenBlacklistView.as_view()),
    path("orders/", include("orders.urls")),
    path("billing/", include("billing.urls")),
    
   
    
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
