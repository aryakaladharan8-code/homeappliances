from django.core.management.base import BaseCommand
from django.conf import settings
from homeservice.models import Technician
import os

class Command(BaseCommand):
    help = 'Inspect Technician idproof fields and check file existence'

    def handle(self, *args, **kwargs):
        qs = Technician.objects.all()
        self.stdout.write(f'Technicians: {qs.count()}')
        for t in qs:
            name = getattr(t, 'name', None)
            ip = getattr(t, 'idproof', '')
            ipname = ip.name if ip else ''
            path = os.path.join(settings.MEDIA_ROOT, ipname) if ipname else ''
            exists = os.path.exists(path) if path else False
            self.stdout.write(f"{t.id} | {name} | idproof name: {repr(ipname)} | exists: {exists} | path: {path}")
