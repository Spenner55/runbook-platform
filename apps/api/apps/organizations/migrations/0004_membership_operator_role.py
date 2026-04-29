from django.db import migrations, models


def forwards(apps, schema_editor):
    Membership = apps.get_model("organizations", "Membership")
    Membership.objects.filter(role="member").update(role="operator")


def backwards(apps, schema_editor):
    Membership = apps.get_model("organizations", "Membership")
    Membership.objects.filter(role="operator").update(role="member")


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0003_membership"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="membership",
            name="role",
            field=models.CharField(
                choices=[
                    ("owner", "Owner"),
                    ("admin", "Admin"),
                    ("operator", "Operator"),
                    ("viewer", "Viewer"),
                ],
                default="operator",
                max_length=16,
            ),
        ),
    ]
