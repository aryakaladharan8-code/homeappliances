from django.core.management.base import BaseCommand
from homeservice.utils import check_subscriptions


class Command(BaseCommand):
    help = 'Check and deactivate technicians with expired subscriptions'

    def handle(self, *args, **options):
        check_subscriptions()
        self.stdout.write(self.style.SUCCESS('Subscriptions checked successfully'))