from django.core.management.base import CommandError
from sis_provisioner.management.commands import SISProvisionerCommand
from aws_message.gather import Gather, GatherException
from events.instructor import InstructorAdd, InstructorDrop
from events.models import InstructorLog
from time import time
from math import floor


class InstructorProvisionerCommand(SISProvisionerCommand):
    def health_check(self):
        # squawk if no new events in the last 24 hours
        # TODO: vary acceptability by where we are in the term
        acceptable_silence = (24 * 60)
        recent = InstructorLog.objects.all().order_by('-minute')[:1]
        if len(recent):
            delta = int(floor(time() / 60)) - recent[0].minute
            if (delta > acceptable_silence):
                self.squawk(
                    "No instructor add events in the last " +
                    "%s hrs and %s mins" % (
                        int(floor((delta/60))), (delta % 60)))


class Command(InstructorProvisionerCommand):
    help = "Loads enrollment events from SQS"

    def handle(self, *args, **options):
        try:
            Gather(processor=InstructorAdd).gather_events()
            Gather(processor=InstructorDrop).gather_events()
            self.update_job()
        except GatherException as err:
            raise CommandError(err)
        except Exception as err:
            raise CommandError('FAIL: %s' % (err))
