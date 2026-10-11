from rest_framework import serializers
from .models import User, ArtistProfile, PasswordResetCode, Notification


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    email = serializers.EmailField(required=True)
    region = serializers.ChoiceField(
        choices=ArtistProfile.REGION_CHOICES, required=False, allow_null=True
    )
    gender = serializers.ChoiceField(
        choices=ArtistProfile.GENDER_CHOICES,
        required=False,
        default=ArtistProfile.GENDER_UNSPECIFIED,
    )
    national_id_number = serializers.CharField(required=False, allow_blank=True, max_length=20)

    class Meta:
        model = User
        fields = ["id", "username", "phone_number", "email", "password", "role", "region", "gender", "national_id_number"]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("This email address is already in use.")
        return value

    def validate_national_id_number(self, value):
        if value and (not value.isdigit() or len(value) < 9):
            raise serializers.ValidationError(
                "The National ID number must have at least 9 digits."
            )
        return value

    def validate(self, attrs):
        role = attrs.get("role", User.ROLE_CUSTOMER)
        if role == User.ROLE_ARTIST and not attrs.get("region"):
            raise serializers.ValidationError(
                {"region": "Region is required for artists."}
            )
        if role == User.ROLE_ARTIST and not attrs.get("national_id_number"):
            raise serializers.ValidationError(
                {"national_id_number": "National ID number is required for artists."}
            )
        return attrs

    def create(self, validated_data):
        region = validated_data.pop("region", None)
        gender = validated_data.pop("gender", ArtistProfile.GENDER_UNSPECIFIED)
        national_id_number = validated_data.pop("national_id_number", "")

        user = User.objects.create_user(
            username=validated_data["username"],
            phone_number=validated_data["phone_number"],
            email=validated_data["email"],
            role=validated_data.get("role", User.ROLE_CUSTOMER),
            password=validated_data["password"],
        )
        if user.role == User.ROLE_ARTIST:
            user.is_artist = True
            user.save()

            ArtistProfile.objects.get_or_create(
                user=user,
                defaults={
                    "brand_name": user.username,
                    "mobile_money_number": user.phone_number or "0000000000",
                    "mobile_money_provider": "orange",
                    "region": region,
                    "gender": gender,
                    "national_id_number": national_id_number,
                },
            )
        return user


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "phone_number", "profile_photo", "role", "is_staff", "is_artist", "date_joined_platform"]

class PushTokenSerializer(serializers.Serializer):
    expo_push_token = serializers.CharField(max_length=255)

    def save(self, **kwargs):
        user = self.context["request"].user
        user.expo_push_token = self.validated_data["expo_push_token"]
        user.save(update_fields=["expo_push_token"])
        return user


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "body", "notification_type", "data", "is_read", "created_at"]

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=6)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Incorrect old password.")
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


class UpdateProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["username", "email", "phone_number", "profile_photo"]
        extra_kwargs = {"profile_photo": {"required": False, "allow_null": True}}

    def validate_username(self, value):
        user = self.context["request"].user
        if User.objects.exclude(id=user.id).filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_email(self, value):
        user = self.context["request"].user
        if User.objects.exclude(id=user.id).filter(email__iexact=value).exists():
            raise serializers.ValidationError("This email address is already in use.")
        return value

    def validate_phone_number(self, value):
        user = self.context["request"].user
        if User.objects.exclude(id=user.id).filter(phone_number=value).exists():
            raise serializers.ValidationError("This phone number is already in use.")
        return value


class RequestPasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        if not User.objects.filter(email=value).exists():
            # Don't reveal whether the email exists — respond the same either way
            pass
        return value


class ConfirmPasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)
    new_password = serializers.CharField(min_length=6)

    def validate(self, attrs):
        try:
            user = User.objects.get(email=attrs["email"])
        except User.DoesNotExist:
            raise serializers.ValidationError({"email": "No account associated with this email."})

        try:
            reset_code = user.reset_codes.filter(code=attrs["code"]).latest("created_at")
        except PasswordResetCode.DoesNotExist:
            raise serializers.ValidationError({"code": "Invalid code."})

        if not reset_code.is_valid():
            raise serializers.ValidationError({"code": "This code has expired or has already been used."})

        attrs["user"] = user
        attrs["reset_code"] = reset_code
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        reset_code = self.validated_data["reset_code"]

        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])

        reset_code.used = True
        reset_code.save(update_fields=["used"])

        return user
