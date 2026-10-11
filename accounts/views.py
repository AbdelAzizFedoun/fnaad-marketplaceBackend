from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from .serializers import RegisterSerializer, MeSerializer, PushTokenSerializer
from .serializers import ChangePasswordSerializer, UpdateProfileSerializer
from .models import User, ArtistProfile, PasswordResetCode
from .serializers import RegisterSerializer, MeSerializer, PushTokenSerializer, ChangePasswordSerializer, UpdateProfileSerializer, RequestPasswordResetSerializer, ConfirmPasswordResetSerializer, NotificationSerializer
import logging

from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView

logger = logging.getLogger(__name__)



class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"


class MeView(generics.RetrieveAPIView):
    serializer_class = MeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class RegisterPushTokenView(generics.GenericAPIView):
    serializer_class = PushTokenSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Token registered."}, status=status.HTTP_200_OK)
    
class ChangePasswordView(generics.GenericAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password changed successfully."})


class UpdateProfileView(generics.UpdateAPIView):
    serializer_class = UpdateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user    


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.request.user.notifications.all()[:60]


class MarkNotificationsReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        request.user.notifications.filter(is_read=False).update(is_read=True)
        return Response({"detail": "Notifications marked as read."})


class MarkNotificationReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, notification_id, *args, **kwargs):
        notification = get_object_or_404(request.user.notifications, pk=notification_id)
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read"])
        return Response({"detail": "Notification marked as read."})


class DeleteNotificationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, notification_id, *args, **kwargs):
        notification = get_object_or_404(request.user.notifications, pk=notification_id)
        notification.delete()
        return Response({"detail": "Notification deleted."})


class ClearNotificationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        request.user.notifications.all().delete()
        return Response({"detail": "All notifications cleared."})


class RequestPasswordResetView(generics.GenericAPIView):
    serializer_class = RequestPasswordResetSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        user = User.objects.filter(email=email).first()
        if user is not None:
            reset_code = PasswordResetCode.objects.create(user=user)
            try:
                sent_count = send_mail(
                    subject="FNAAD password reset code",
                    message=f"Your reset code is: {reset_code.code}\n\nThis code expires in 15 minutes.",
                    from_email=None,
                    recipient_list=[email],
                    fail_silently=False,
                )
                if sent_count != 1:
                    raise RuntimeError("Password reset email was not accepted by the mail server.")
            except Exception:
                reset_code.delete()
                logger.exception("Unable to send password reset email.")
                return Response(
                    {"detail": "Unable to send the reset code right now. Please try again later."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        # Always return the same response, whether or not the email exists —
        # this prevents leaking which emails are registered
        return Response({"detail": "If an account exists with this email, a reset code has been sent."})


class ConfirmPasswordResetView(generics.GenericAPIView):
    serializer_class = ConfirmPasswordResetSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset_confirm"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password reset successfully."})    
