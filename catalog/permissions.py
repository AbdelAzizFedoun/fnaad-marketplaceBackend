from rest_framework import permissions


class IsSuperAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return bool(
            user
            and getattr(user, "is_authenticated", False)
            and (
                getattr(user, "role", None) == "superadmin"
                or getattr(user, "is_staff", False)
            )
        )
