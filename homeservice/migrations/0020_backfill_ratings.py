from django.db import migrations


def backfill_ratings(apps, schema_editor):
    ServiceRequest = apps.get_model('homeservice', 'ServiceRequest')
    Technician = apps.get_model('homeservice', 'Technician')
    Rating = apps.get_model('homeservice', 'Rating')

    created_count = 0
    synced_count = 0

    # Only consider completed jobs with a technician assigned
    qs = ServiceRequest.objects.filter(status='completed').exclude(technician__isnull=True)
    for sr in qs:
        # If Rating already exists for this job, ensure ServiceRequest.rating is synced
        try:
            rating_obj = Rating.objects.get(job=sr)
            if sr.rating != rating_obj.stars:
                sr.rating = rating_obj.stars
                sr.save(update_fields=['rating'])
                synced_count += 1
        except Rating.DoesNotExist:
            # Find Technician profile for the assigned user
            try:
                tech = Technician.objects.get(user=sr.technician)
            except Technician.DoesNotExist:
                # Can't create a Rating without a Technician profile; skip
                continue

            # Determine stars to use: prefer existing ServiceRequest.rating if present, otherwise default to 5
            stars = sr.rating if sr.rating else 5
            Rating.objects.create(job=sr, technician=tech, stars=stars)

            # Sync the ServiceRequest.rating field
            if sr.rating != stars:
                sr.rating = stars
                sr.save(update_fields=['rating'])

            created_count += 1

    # For visibility when running migration manually
    print(f"Backfill ratings: created={created_count}, synced={synced_count}")


class Migration(migrations.Migration):

    dependencies = [
        ('homeservice', '0019_alter_rating_technician_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_ratings, migrations.RunPython.noop),
    ]
