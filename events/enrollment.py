from sis_provisioner.loader import Loader
from events import EventBase, EventException, EnrollmentLog
from sis_provisioner.models import Enrollment as EnrollmentModel
from restclients.models.sws import Term, Section
from dateutil.parser import parse as date_parse


class UnknownActionCodeException(Exception):
    pass


class Enrollment(EventBase):
    """
    Collects enrollment event described by
    https://wiki.cac.washington.edu/display/StudentEvents/UW+Course+Enrollment+v2
    """

    SETTINGS_NAME = 'ENROLLMENT_V2'
    EXCEPTION_CLASS = EventException

    # What we expect in an enrollment message
    _enrollmentMessageType = 'uw-student-registration-v2'
    _enrollmentMessageVersion = '2'

    def process(self):
        if self._settings.get('VALIDATE_MSG_SIGNATURE', True):
            self.validate()

        enrollments = []
        for event in self._extract()['Events']:
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
                    'UWRegID': event['Person']['UWRegID'],
                    'Status': self._enrollment_status(event, section),
                    'LastModified': date_parse(event['LastModified']),
                    'Auditor': event['Auditor'],
                    'RequestDate': date_parse(event['RequestDate']),
                    'InstructorUWRegID': event['Instructor']['UWRegID'] if (
                        'Instructor' in event and event['Instructor']
                        and 'UWRegID' in event['Instructor']) else None
                }

                enrollments.append(data)
            except UnknownActionCodeException:
                self._log.warning("Got %s for %s at %s" % (
                    event['Action']['Code'],
                    event['Person']['UWRegID'],
                    event['LastModified']))
                pass

        enrollment_count = len(enrollments)
        if enrollment_count:
            loader = Loader()
            for enrollment in enrollments:
                try:
                    loader.load_enrollment(enrollment)
                except Exception as err:
                    raise EventException('Load enrollment failed: %s' % (err))

            self.recordSuccess(EnrollmentLog, enrollment_count)

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

        if action_code == 'D':
            return EnrollmentModel.DELETED_STATUS

        raise UnknownActionCodeException()
