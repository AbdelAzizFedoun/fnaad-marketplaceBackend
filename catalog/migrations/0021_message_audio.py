from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("catalog", "0020_conversation_typing_and_block")]
    operations = [
        migrations.AddField(model_name="message", name="audio", field=models.FileField(blank=True, null=True, upload_to="messages/audio/")),
        migrations.AlterField(model_name="message", name="message_type", field=models.CharField(choices=[("text", "Texte"), ("location", "Localisation"), ("image", "Image"), ("document", "Document"), ("audio", "Audio")], default="text", max_length=10)),
    ]
