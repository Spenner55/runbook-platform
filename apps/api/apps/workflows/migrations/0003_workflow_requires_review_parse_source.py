from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0002_alter_workflow_definition_schema_version_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflow",
            name="requires_review",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="workflow",
            name="parse_source",
            field=models.CharField(
                choices=[("manual", "Manual"), ("ai_parse", "AI Parse")],
                default="manual",
                max_length=16,
            ),
        ),
    ]
