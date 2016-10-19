from events.event import EventBase, EventException
from events.models import PersonLog
from sis_provisioner.models import User as UserModel
from sis_provisioner.models import PRIORITY_IMMEDIATE
from events.exceptions import EventException


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
            self._log.info('PERSON NULL UWNetID: %s' % (
                current['RegID'] if current else previous['RegID']))
            return

        # Preferred name, net_id or reg_id change?
        if not (previous and current) or \
           current['StudentName'] != previous['StudentName'] or \
           current['FirstName'] != previous['FirstName'] or \
           current['LastName'] != previous['LastName'] or \
           current['UWNetID'] != previous['UWNetID'] or \
           current['RegID'] != previous['RegID']:
            try:
                user = UserModel.objects.get(net_id=net_id)
                user.priority = PRIORITY_IMMEDIATE
            except UserModel.DoesNotExist:
                user = UserModel(net_id=net_id,
                                 reg_id=current['RegID'],
                                 priority=PRIORITY_IMMEDIATE)
            user.save()

    def record_success(self, event_count):
        self.record_success_to_log(PersonLog, event_count)
