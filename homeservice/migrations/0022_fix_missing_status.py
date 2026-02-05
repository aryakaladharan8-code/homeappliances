from django.db import migrations


def set_missing_status(apps, schema_editor):
    ServiceRequest = apps.get_model('homeservice', 'ServiceRequest')
    qs = ServiceRequest.objects.filter(status__isnull=True) | ServiceRequest.objects.filter(status='')
    count = qs.update(status='pending')
    print(f"Fixed {count} ServiceRequest rows with missing/empty status")


class Migration(migrations.Migration):
    dependencies = [
        ('homeservice', '0021_rating_auto_generated'),
    ]

    operations = [
        migrations.RunPython(set_missing_status, migrations.RunPython.noop),
    ]
