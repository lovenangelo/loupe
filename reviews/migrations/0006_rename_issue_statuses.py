from django.db import migrations, models


def rename_statuses_forward(apps, schema_editor):
    Issue = apps.get_model("reviews", "Issue")
    Issue.objects.filter(status="approved").update(status="valid")
    Issue.objects.filter(status="dismissed").update(status="invalid")


def rename_statuses_backward(apps, schema_editor):
    Issue = apps.get_model("reviews", "Issue")
    Issue.objects.filter(status="valid").update(status="approved")
    Issue.objects.filter(status="invalid").update(status="dismissed")


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0005_chatmessage"),
    ]

    operations = [
        migrations.RunPython(rename_statuses_forward, rename_statuses_backward),
        migrations.AlterField(
            model_name="issue",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("valid", "Valid"),
                    ("invalid", "Invalid"),
                ],
                max_length=9,
            ),
        ),
    ]
