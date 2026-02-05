import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'homeappliances.settings')
import django
django.setup()

from django.conf import settings
from homeservice.models import Technician

qs = Technician.objects.all()
print('Technicians:', qs.count())
for t in qs:
    name = getattr(t, 'name', None)
    ip = getattr(t, 'idproof', '')
    ipname = ip.name if ip else ''
    path = os.path.join(settings.MEDIA_ROOT, ipname) if ipname else ''
    exists = os.path.exists(path) if path else False
    print(t.id, name, '| idproof name:', repr(ipname), '| exists:', exists, '| path:', path)
