from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0019_message_edited_at")]

    operations = [
        migrations.AddField(model_name="conversation", name="customer_typing_until", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="conversation", name="artist_typing_until", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="conversation", name="blocked_by", field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="blocked_conversations", to=settings.AUTH_USER_MODEL)),
    ]
