from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models


class UserManager(BaseUserManager):
    def _create_user(self, email, phone_number, password, role=None, **extra_fields):
        if not email:
            raise ValueError("L'email est requis")
        email = self.normalize_email(email)
        user = self.model(
            email=email,
            phone_number=phone_number,
            role=role or "customer",
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, phone_number=None, password=None, role=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, phone_number, password, role, **extra_fields)

    def create_superuser(self, email, phone_number=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "superadmin")
        return self._create_user(email, phone_number, password, extra_fields.pop("role"), **extra_fields)


class User(AbstractUser):
    ROLE_CUSTOMER = "customer"
    ROLE_ARTIST = "artist"
    ROLE_SUPERADMIN = "superadmin"

    ROLE_CHOICES = [
        (ROLE_CUSTOMER, "Client"),
        (ROLE_ARTIST, "Artiste"),
        (ROLE_SUPERADMIN, "Super Admin"),
    ]

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "phone_number"]

    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20, unique=True)
    profile_photo = models.ImageField(upload_to="users/profile_photos/", null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_CUSTOMER)
    is_artist = models.BooleanField(default=False)
    date_joined_platform = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    expo_push_token = models.CharField(max_length=255, blank=True, null=True)

    objects = UserManager()

    def __str__(self):
        return f"{self.email} ({self.role})"


class ArtistProfile(models.Model):
    REGION_ADAMAOUA = "adamaoua"
    REGION_CENTRE = "centre"
    REGION_EST = "est"
    REGION_EXTREME_NORD = "extreme_nord"
    REGION_LITTORAL = "littoral"
    REGION_NORD = "nord"
    REGION_NORD_OUEST = "nord_ouest"
    REGION_OUEST = "ouest"
    REGION_SUD = "sud"
    REGION_SUD_OUEST = "sud_ouest"

    REGION_CHOICES = [
        (REGION_ADAMAOUA, "Adamaoua"),
        (REGION_CENTRE, "Centre"),
        (REGION_EST, "East"),
        (REGION_EXTREME_NORD, "Far North"),
        (REGION_LITTORAL, "Littoral"),
        (REGION_NORD, "North"),
        (REGION_NORD_OUEST, "Northwest"),
        (REGION_OUEST, "West"),
        (REGION_SUD, "South"),
        (REGION_SUD_OUEST, "Southwest"),
    ]

    GENDER_MALE = "male"
    GENDER_FEMALE = "female"
    GENDER_UNSPECIFIED = "unspecified"

    GENDER_CHOICES = [
        (GENDER_MALE, "Male"),
        (GENDER_FEMALE, "Female"),
        (GENDER_UNSPECIFIED, "Prefer not to say"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="artist_profile")
    brand_name = models.CharField(max_length=120)
    bio = models.TextField(blank=True)
    artistic_practice = models.CharField(max_length=120, blank=True)
    instagram_handle = models.CharField(max_length=60, blank=True)
    portfolio_url = models.URLField(blank=True)
    avatar = models.ImageField(upload_to="artists/avatars/", null=True, blank=True)
    region = models.CharField(max_length=20, choices=REGION_CHOICES, null=True, blank=True)
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, default=GENDER_UNSPECIFIED)
    mobile_money_number = models.CharField(max_length=20)
    mobile_money_provider = models.CharField(
        max_length=20,
        choices=[("orange", "Orange Money"), ("mtn", "MTN MoMo")],
    )
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    national_id_number = models.CharField(
        max_length=20,
        blank=True,
        validators=[RegexValidator(r'^\d{9,}$', 'The National ID number must have at least 9 digits.')],
        help_text="Cameroon National ID Card (CNI) number — at least 9 digits.",
    )
    is_suspended = models.BooleanField(default=False)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.brand_name


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=140)
    body = models.CharField(max_length=400)
    notification_type = models.CharField(max_length=40)
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username}: {self.title}"

import random
import string
from django.utils import timezone
from datetime import timedelta


def generate_reset_code():
    return "".join(random.choices(string.digits, k=6))


class PasswordResetCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reset_codes")
    code = models.CharField(max_length=6, default=generate_reset_code)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    def is_valid(self):
        expiry = self.created_at + timedelta(minutes=15)
        return not self.used and timezone.now() < expiry

    def __str__(self):
        return f"Code for {self.user.username} ({'used' if self.used else 'active'})"
