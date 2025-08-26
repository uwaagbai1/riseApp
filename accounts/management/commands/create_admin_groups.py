from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Create admin role groups'

    def handle(self, *args, **kwargs):
        for role in ['Director', 'Secretary', 'Principal']:
            group, created = Group.objects.get_or_create(name=role)
            self.stdout.write(
                f'Group {role} {"created" if created else "already exists"}'
            )