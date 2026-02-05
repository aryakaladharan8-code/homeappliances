import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','homeappliances.settings')
django.setup()
from homeservice.models import ServiceRequest
qs = ServiceRequest.objects.all().select_related('technician')
print('Total requests', qs.count())
for r in qs.order_by('id')[:50]:
    tech_user = r.technician.username if r.technician else None
    has_rating = hasattr(r, 'rating_obj') and getattr(r, 'rating_obj') is not None
    rating_stars = r.rating_obj.stars if has_rating else None
    print('id:{} status:{} status_lower:{} technician:{} has_rating:{} rating_field:{} rating_obj_stars:{} review:{}'.format(r.id, r.status, (r.status or '').lower(), tech_user, has_rating, r.rating, rating_stars, r.review))
