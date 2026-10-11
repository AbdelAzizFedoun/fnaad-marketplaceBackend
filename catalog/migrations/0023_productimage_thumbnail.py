from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0022_message_is_forwarded"),
    ]

    operations = [
        migrations.AddField(
            model_name="productimage",
            name="thumbnail",
            field=models.ImageField(blank=True, upload_to="products/thumbnails/"),
        ),
    ]