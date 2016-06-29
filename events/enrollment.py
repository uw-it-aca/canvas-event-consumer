from sis_provisioner.loader import Loader
from events import EventBase, EventException
from sis_provisioner.models import Enrollment as EnrollmentModel
from restclients.models.sws import Term, Section
import dateutil.parser


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

            term = Term(quarter=course_data['Quarter'],
                        year=course_data['Year'])

            section = Section(
                term=term,
                curriculum_abbr=course_data['CurriculumAbbreviation'],
                course_number=course_data['CourseNumber'],
                section_id=section_data['SectionID'],
                is_primary_section=True
            )

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

            # Canvas "active" corresponds to Action codes:
            #   "A" == ADDED and
            #   "S" == STANDBY (EO only status)
            code = event['Action']['Code'].upper()
            if code == 'A':
                status = EnrollmentModel.ACTIVE_STATUS
            elif code == 'S':
                status = EnrollmentModel.ACTIVE_STATUS
                self._log.debug("Add standby %s to %s" % (
                    event['Person']['UWRegID'],
                    section.canvas_section_sis_id()))
            elif code == 'D':
                status = EnrollmentModel.DELETED_STATUS
            else:
                self._log.warning("Got %s for %s at %s" % (
                    code, event['Person']['UWRegID'], event['LastModified']))
                return

            data = {
                'Section': section,
                'UWRegID': event['Person']['UWRegID'],
                'Status': status,
                'LastModified': dateutil.parser.parse(event['LastModified']),
                'Auditor': event['Auditor'],
                'RequestDate': dateutil.parser.parse(event['RequestDate']),
                'InstructorUWRegID': event['Instructor']['UWRegID'] if (
                    'Instructor' in event and event['Instructor']
                    and 'UWRegID' in event['Instructor']) else None
            }

            enrollments.append(data)

        loader = Loader()
        for enrollment in enrollments:
            try:
                loader.load_enrollment(enrollment)
            except Exception as err:
                raise EventException('Load enrollment failed: %s' % (err))

        self.recordSuccess(EnrollmentLog, enrollments)
