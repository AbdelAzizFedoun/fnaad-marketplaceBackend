try:
	from django.contrib import admin  # type: ignore
except Exception:  # pragma: no cover - allow static analysis / editor without Django
	# Provide a minimal stub for environments without Django available
	from types import SimpleNamespace

	class _StubAdmin(SimpleNamespace):
		def __init__(self):
			super().__init__()
			self.site = SimpleNamespace(register=lambda *a, **k: None)

	admin = _StubAdmin()

from .models import StorefrontSettings, SocialLink


admin.site.register(StorefrontSettings)
admin.site.register(SocialLink)