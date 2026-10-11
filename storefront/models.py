from django.db import models  # type: ignore
from accounts.models import ArtistProfile


class StorefrontSettings(models.Model):
    THEME_NIGHT_GOLD = "night_gold"
    THEME_IVORY = "ivory"
    THEME_TERRACOTTA = "terracotta"

    THEME_CHOICES = [
        (THEME_NIGHT_GOLD, "Nuit & Or"),
        (THEME_IVORY, "Ivoire"),
        (THEME_TERRACOTTA, "Terre Cuite"),
    ]

    LAYOUT_GRID = "grid"
    LAYOUT_LIST = "list"

    LAYOUT_CHOICES = [
        (LAYOUT_GRID, "Grille"),
        (LAYOUT_LIST, "Liste"),
    ]

    artist = models.OneToOneField(ArtistProfile, on_delete=models.CASCADE, related_name="storefront_settings")
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default=THEME_NIGHT_GOLD)
    layout = models.CharField(max_length=10, choices=LAYOUT_CHOICES, default=LAYOUT_GRID)
    accent_color = models.CharField(max_length=7, default="#C9A24B")
    banner_image = models.ImageField(upload_to="storefronts/banners/", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Storefront Setting"
        verbose_name_plural = "Storefront Settings"

    def __str__(self):
        return f"Apparence de {self.artist.brand_name}"


class SocialLink(models.Model):
    PLATFORM_CHOICES = [
        ("facebook", "Facebook"),
        ("instagram", "Instagram"),
        ("tiktok", "TikTok"),
        ("x", "X (Twitter)"),
    ]

    artist = models.ForeignKey(ArtistProfile, on_delete=models.CASCADE, related_name="social_links")
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    url = models.URLField()

    class Meta:
        unique_together = ("artist", "platform")

    def __str__(self):
        return f"{self.artist.brand_name} - {self.platform}"