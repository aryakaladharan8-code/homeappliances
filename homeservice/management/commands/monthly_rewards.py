from django.core.management.base import BaseCommand
from homeservice.utils import give_monthly_rewards


class Command(BaseCommand):
    help = 'Give monthly rewards to top technicians'

    def handle(self, *args, **options):
        give_monthly_rewards()
        self.stdout.write(self.style.SUCCESS('Monthly rewards given successfully'))