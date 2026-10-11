from django.urls import path
from .views import RegisterView, MeView, RegisterPushTokenView, ChangePasswordView, UpdateProfileView
from .views import RegisterView, MeView, RegisterPushTokenView, ChangePasswordView, UpdateProfileView, RequestPasswordResetView, ConfirmPasswordResetView, NotificationListView, MarkNotificationReadView, MarkNotificationsReadView, DeleteNotificationView, ClearNotificationsView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("me/", MeView.as_view(), name="me"),
    path("push-token/", RegisterPushTokenView.as_view(), name="register-push-token"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("update-profile/", UpdateProfileView.as_view(), name="update-profile"),
    path("request-password-reset/", RequestPasswordResetView.as_view(), name="request-password-reset"),
    path("confirm-password-reset/", ConfirmPasswordResetView.as_view(), name="confirm-password-reset"),
    path("notifications/", NotificationListView.as_view(), name="notifications"),
    path("notifications/read/", MarkNotificationsReadView.as_view(), name="notifications-read"),
    path("notifications/<int:notification_id>/read/", MarkNotificationReadView.as_view(), name="notification-read"),
    path("notifications/<int:notification_id>/", DeleteNotificationView.as_view(), name="notification-delete"),
    path("notifications/clear/", ClearNotificationsView.as_view(), name="notifications-clear"),
]
