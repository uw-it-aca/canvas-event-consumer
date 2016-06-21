from django.core.management.base import CommandError
from django.conf import settings
from sis_provisioner.management.commands import SISProvisionerCommand
from aws_message.gather import Gather, GatherException
from events.enrollment import Enrollment
from events import EventException
from events.models import EnrollmentLog
from time import time
from math import floor


class EnrollmentProvisionerCommand(SISProvisionerCommand):
    def health_check(self):
        # squawk if no new events in the last 6 hours
        # TODO: vary acceptability by where we are in the term
        acceptable_silence = (6 * 60)
        recent = EnrollmentLog.objects.all().order_by('-minute')[:1]
        if len(recent):
            delta = int(floor(time() / 60)) - recent[0].minute
            if (delta > acceptable_silence):
                self.squawk(
                    "No enrollment events in the last %s hrs and %s mins" % (
                        int(floor((delta/60))), (delta % 60)))


class Command(EnrollmentProvisionerCommand):
    help = "Loads enrollment events from SQS"

    def handle(self, *args, **options):
        try:
            Gather(processor=Enrollment).gather_events()
            self.update_job()
        except GatherException as err:
            raise CommandError(err)
        except Exception as err:
            raise CommandError('FAIL: %s' % (err))
