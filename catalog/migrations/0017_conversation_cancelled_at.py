from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0016_product_category_hall_of_fame'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='cancelled_at',
            field=models.DateTimeField(blank=True, help_text='Set when the conversation is cancelled — lets a customer resume it instead of starting a new one.', null=True),
        ),
    ]