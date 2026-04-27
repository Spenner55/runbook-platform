from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("executions", "0004_alter_executionstep_error_message_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="execution",
            name="claim_token",
            field=models.UUIDField(blank=True, null=True, unique=True),
        ),
    ]
