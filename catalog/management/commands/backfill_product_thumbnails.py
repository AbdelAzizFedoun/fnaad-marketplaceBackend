from django.core.management.base import BaseCommand

from catalog.image_utils import generate_product_thumbnail
from catalog.models import ProductImage


class Command(BaseCommand):
    help = "Generate WebP thumbnails for product images that do not have one."

    def handle(self, *args, **options):
        images = ProductImage.objects.filter(thumbnail="").iterator()
        generated = 0
        failed = 0

        for product_image in images:
            try:
                generate_product_thumbnail(product_image)
                generated += 1
            except Exception as error:
                failed += 1
                self.stderr.write(f"Could not create thumbnail for image {product_image.pk}: {error}")

        self.stdout.write(self.style.SUCCESS(f"Generated {generated} thumbnails; {failed} failed."))