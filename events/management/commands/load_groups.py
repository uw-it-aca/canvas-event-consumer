from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from aws_message.gather import Gather, GatherException
from events.group import Group, GroupException
from sis_provisioner.pidfile import Pidfile, ProcessRunningException
import os
import errno


class Command(BaseCommand):
    help = "Loads group events from SQS"

    def handle(self, *args, **options):
        try:
            with Pidfile():
                Gather(settings.AWS_SQS.get('GROUP'),
                       Group, GroupException).gather_events()
        except ProcessRunningException as err:
            pass
        except GatherException, err:
            raise CommandError(err)
        except Exception, err:
            raise CommandError('FAIL: %s' % (err))
