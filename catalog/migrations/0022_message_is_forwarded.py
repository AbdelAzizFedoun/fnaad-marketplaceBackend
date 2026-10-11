from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("catalog", "0021_message_audio")]
    operations = [migrations.AddField(model_name="message", name="is_forwarded", field=models.BooleanField(default=False))]
