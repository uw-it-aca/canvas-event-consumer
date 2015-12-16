from django.core.management.base import CommandError
from django.conf import settings
from sis_provisioner.management.commands import SISProvisionerCommand
from aws_message.gather import Gather, GatherException
from events.enrollment import Enrollment, EnrollmentException


class Command(SISProvisionerCommand):
    help = "Loads enrollment events from SQS"

    def handle(self, *args, **options):
        try:
            Gather(settings.AWS_SQS.get('ENROLLMENT'),
                   Enrollment, EnrollmentException).gather_events()
            self.update_job()
        except GatherException as err:
            raise CommandError(err)
        except Exception as err:
            raise CommandError('FAIL: %s' % (err))
