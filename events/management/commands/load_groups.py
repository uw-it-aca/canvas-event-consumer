from django.core.management.base import CommandError
from django.conf import settings
from sis_provisioner.management.commands import SISProvisionerCommand
from aws_message.gather import Gather, GatherException
from events.group import Group, GroupException
from sis_provisioner.pidfile import Pidfile, ProcessRunningException
import os
import errno


class Command(SISProvisionerCommand):
    help = "Loads group events from SQS"

    def handle(self, *args, **options):
        try:
            with Pidfile():
                Gather(settings.AWS_SQS.get('GROUP'),
                       Group, GroupException).gather_events()
                self.update_job()
        except ProcessRunningException as err:
            pass
        except GatherException as err:
            raise CommandError(err)
        except Exception as err:
            raise CommandError('FAIL: %s' % (err))
