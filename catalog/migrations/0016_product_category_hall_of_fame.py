from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0015_alter_conversation_unique_together_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='category',
            field=models.CharField(choices=[('painting', 'Peinture'), ('drawing', 'Dessin'), ('abstract', 'Art abstrait'), ('sculpture', 'Sculpture'), ('portrait', 'Portrait'), ('contemporary', 'Contemporary Art'), ('calligraphy', 'Calligraphy'), ('artisan_crafts', 'Artisan Crafts'), ('hall_of_fame', 'Hall of Fame'), ('other', 'Autre')], default='other', max_length=20),
        ),
        migrations.AlterField(
            model_name='commissionrequest',
            name='category',
            field=models.CharField(choices=[('painting', 'Peinture'), ('drawing', 'Dessin'), ('abstract', 'Art abstrait'), ('sculpture', 'Sculpture'), ('portrait', 'Portrait'), ('contemporary', 'Contemporary Art'), ('calligraphy', 'Calligraphy'), ('artisan_crafts', 'Artisan Crafts'), ('hall_of_fame', 'Hall of Fame'), ('other', 'Autre')], default='other', max_length=20),
        ),
    ]