from events import EventBase, EventException
from events.models import EnrollmentLog
from sis_provisioner.models import Enrollment as EnrollmentModel
from restclients.models.sws import Term, Section
from dateutil.parser import parse as date_parse


class UnhandledActionCodeException(Exception):
    pass


class Enrollment(EventBase):
    """
    Collects enrollment event described by
    https://wiki.cac.washington.edu/display/StudentEvents/UW+Course+Enrollment+v2
    """

    # Enrollment Version 2 settings
    SETTINGS_NAME = 'ENROLLMENT_V2'
    EXCEPTION_CLASS = EventException

    ## What we expect in a v1 enrollment message
    #_eventMessageType = 'uw-student-registration'
    #_eventMessageVersion = '1'

    # What we expect in a v2 enrollment message
    _eventMessageType = 'uw-student-registration-v2'
    _eventMessageVersion = '2'

    def process_events(self, events):
        enrollments = []
        for event in events['Events']:
            section_data = event['Section']
            course_data = section_data['Course']

            section = Section()
            section.term = Term(quarter=course_data['Quarter'],
                                year=course_data['Year'])
            section.curriculum_abbr=course_data['CurriculumAbbreviation']
            section.course_number=course_data['CourseNumber']
            section.section_id=section_data['SectionID']
            section.is_primary_section=True
            section.linked_section_urls = []

            if ('PrimarySection' in event and
                    'Course' in event['PrimarySection']):
                primary_course = event['PrimarySection']['Course']
                if primary_course:
                    section.is_primary_section = False
                    section.primary_section_curriculum_abbr = \
                        primary_course['CurriculumAbbreviation']
                    section.primary_section_course_number = \
                        primary_course['CourseNumber']
                    section.primary_section_id = \
                        event['PrimarySection']['SectionID']

            try:
                data = {
                    'Section': section,
                    'Role' : EnrollmentModel.STUDENT_ROLE,
                    'UWRegID': event['Person']['UWRegID'],
                    'Status': self._enrollment_status(event, section),
                    'LastModified': date_parse(event['LastModified']),
                    'InstructorUWRegID': event['Instructor']['UWRegID'] if (
                        'Instructor' in event and event['Instructor']
                        and 'UWRegID' in event['Instructor']) else None
                }

                if 'Auditor' in event:
                    data['Role'] = EnrollmentModel.AUDITOR_ROLE

                if 'RequestDate' in event:
                    data['RequestDate'] = date_parse(event['RequestDate'])

                enrollments.append(data)
            except UnhandledActionCodeException:
                self._log.warning("Got %s for %s at %s" % (
                    event['Action']['Code'],
                    event['Person']['UWRegID'],
                    event['LastModified']))
                pass

        self.load(enrollments)

    def record_success(self, event_count):
        self.record_success_to_log(EnrollmentLog, event_count)

    def _enrollment_status(self, event, section):
        # Canvas "active" corresponds to Action codes:
        #   "A" == ADDED and
        #   "S" == STANDBY (EO only status)
        action_code = event['Action']['Code'].upper()

        if action_code == 'A':
            return EnrollmentModel.ACTIVE_STATUS

        if action_code == 'S':
            self._log.debug("Add standby %s to %s" % (
                event['Person']['UWRegID'],
                section.canvas_section_sis_id()))
            return EnrollmentModel.ACTIVE_STATUS

        if action_code == 'D':
            return EnrollmentModel.DELETED_STATUS

        raise UnhandledActionCodeException()
