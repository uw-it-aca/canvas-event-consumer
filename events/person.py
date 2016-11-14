from events.event import EventBase
from events.models import PersonLog
from restclients.models.sws import Person as PersonModel
from sis_provisioner.models import User, PRIORITY_HIGH
from events.exceptions import EventException


log_prefix = 'PERSON:'


class Person(EventBase):
    """
    Collects Person Change Event described by

    """

    # Enrollment Version 2 settings
    SETTINGS_NAME = 'PERSON_V1'
    EXCEPTION_CLASS = EventException

    #  What we expect in a v1 enrollment message
    #  _eventMessageType = 'uw-student-registration'
    #   eventMessageVersion = '1'

    # What we expect in a v2 enrollment message
    _eventMessageType = 'uw-person-change-v1'
    _eventMessageVersion = '1'

    def process_events(self, event):
        current = event['Current']
        previous = event['Previous']
        net_id = current['UWNetID'] if current else previous['UWNetID']
        if not net_id:
            self._log.info('%s IGNORE missing uwnetid for %s' % (
                log_prefix,
                current['RegID'] if current else previous['RegID']))
            return

        # Preferred name, net_id or reg_id change?
        if (not (previous and current) or
                current['StudentName'] != previous['StudentName'] or
                current['FirstName'] != previous['FirstName'] or
                current['LastName'] != previous['LastName'] or
                current['UWNetID'] != previous['UWNetID'] or
                current['RegID'] != previous['RegID']):
            User.objects.add_user(PersonModel(uwregid=current['RegID'],
                                              uwnetid=net_id),
                                  priority=PRIORITY_HIGH)

    def record_success(self, event_count):
        self.record_success_to_log(PersonLog, event_count)
