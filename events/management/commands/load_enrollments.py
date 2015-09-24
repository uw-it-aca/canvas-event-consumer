from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from aws_message.gather import Gather, GatherException
from events.enrollment import Enrollment, EnrollmentException


class Command(BaseCommand):
    help = "Loads enrollment events from SQS"

    def handle(self, *args, **options):
        try:
            Gather(settings.AWS_SQS.get('ENROLLMENT'),
                   Enrollment, EnrollmentException).gather_events()
        except GatherException, err:
            raise CommandError(err)
        except Exception, err:
            raise CommandError('FAIL: %s' % (err))
