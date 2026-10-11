from io import BytesIO
from uuid import uuid4

from django.core.files.base import ContentFile
from PIL import Image, ImageOps


THUMBNAIL_SIZE = (640, 640)


def generate_product_thumbnail(product_image):
    if not product_image.image:
        return

    with product_image.image.open("rb") as source:
        with Image.open(source) as original:
            thumbnail = ImageOps.exif_transpose(original)
            thumbnail.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            if thumbnail.mode not in ("RGB", "RGBA"):
                thumbnail = thumbnail.convert("RGBA" if "transparency" in thumbnail.info else "RGB")
            output = BytesIO()
            thumbnail.save(output, format="WEBP", quality=78, method=6)

    product_image.thumbnail.save(
        f"{uuid4().hex}.webp",
        ContentFile(output.getvalue()),
        save=False,
    )
    product_image.save(update_fields=["thumbnail"])