from sis_provisioner.models import Enrollment as EnrollmentModel
from sis_provisioner.policy import CoursePolicy
from events.event import EventBase, EventException
from events.models import InstructorLog
from restclients.models.sws import Section
from restclients.sws.term import get_term_by_year_and_quarter
from dateutil.parser import parse as date_parse
from datetime import date


class InstructorEventBase(EventBase):
    def process_events(self, event):
        self._previous_instructors = self._instructors_from_section_json(
            event['Previous'])
        self._current_instructors = self._instructors_from_section_json(
            event['Current'])
        self._last_modified = date_parse(event['EventDate'])

        section_data = event['Current']
        course_data = section_data['Course']

        term_year = section_data['Term']['Year']
        if term_year < date.today().year:
            return

        term = get_term_by_year_and_quarter(
            term_year, section_data['Term']['Quarter'])

        section = Section(
            term=term,
            course_campus=section_data['CourseCampus'],
            curriculum_abbr=course_data['CurriculumAbbreviation'],
            course_number=course_data['CourseNumber'],
            section_id=section_data['SectionID'])

        if CoursePolicy().is_time_schedule_construction(section):
            self._log_tsc_ignore(section.canvas_section_sis_id())
            return

        sections = []
        primary_section = section_data["PrimarySection"]
        if (primary_section is not None and
                primary_section["SectionID"] != section.section_id):
            section.is_primary_section = False
            sections.append(section)
        else:
            if len(section_data["LinkedSectionTypes"]):
                for linked_section_type in section_data["LinkedSectionTypes"]:

                    for linked_section_data in \
                            linked_section_type["LinkedSections"]:
                        lsd_data = linked_section_data['Section']
                        section = Section(
                            term=term,
                            curriculum_abbr=lsd_data['CurriculumAbbreviation'],
                            course_number=lsd_data['CourseNumber'],
                            section_id=lsd_data['SectionID'],
                            is_primary_section=False)
                        sections.append(section)
            else:
                section.is_primary_section = True
                section.primary_section_curriculum_abbr = \
                    primary_section['CurriculumAbbreviation']
                section.primary_section_course_number = \
                    primary_section['CourseNumber']
                section.primary_section_id = primary_section['SectionID']
                section.is_independent_study = section_data['IndependentStudy']
                sections.append(section)

        for section in sections:
            self.load_instructors(section)

    def enrollments(self, reg_id_list, status, section):
        enrollments = []
        enrollment_data = {
            'Section': section,
            'Role': EnrollmentModel.INSTRUCTOR_ROLE,
            'Status': status,
            'LastModified': self._last_modified,
            'InstructorUWRegID': None
        }

        for reg_id in reg_id_list:
            enrollment_data['UWRegID'] = reg_id
            enrollment_data['InstructorUWRegID'] = reg_id \
                if section.is_independent_study else None

            enrollments.append(enrollment_data)

        return enrollments

    def load_instructors(self, section):
        raise Exception('No load_instructors method')

    def _instructors_from_section_json(self, section):
        instructors = {}
        if section:
            for meeting in section['Meetings']:
                for instructor in meeting['Instructors']:
                    instructors[instructor['Person']['RegID']] = instructor

        return instructors.keys()

    def record_success(self, event_count):
        self.record_success_to_log(InstructorLog, event_count)


class InstructorAdd(InstructorEventBase):
    """
    UW Course Instructor Add Event Handler
    """
    SETTINGS_NAME = 'INSTRUCTOR_ADD'
    EXCEPTION_CLASS = EventException

    # What we expect in an enrollment message
    _eventMessageType = 'uw-instructor-add'
    _eventMessageVersion = '1'

    def load_instructors(self, section):
        add = [reg_id for reg_id in self._current_instructors
               if reg_id not in self._previous_instructors]
        enrollments = self.enrollments(
            add, EnrollmentModel.ACTIVE_STATUS, section)
        self.load_enrollments(enrollments)

    def _log_tsc_ignore(self, section_id):
        self._log.info("IGNORE ADD: TSC on for %s" % (section_id))


class InstructorDrop(InstructorEventBase):
    """
    UW Course Instructor Drop Event Handler
    """
    SETTINGS_NAME = 'INSTRUCTOR_DROP'
    EXCEPTION_CLASS = EventException

    # What we expect in an enrollment message
    _eventMessageType = 'uw-instructor-drop'
    _eventMessageVersion = '1'

    def load_instructors(self, section):
        drop = [reg_id for reg_id in self._previous_instructors
                if reg_id not in self._current_instructors]
        enrollments = self.enrollments(
            drop, EnrollmentModel.DELETED_STATUS, section)
        self.load_enrollments(enrollments)

    def _log_tsc_ignore(self, section_id):
        self._log.info("IGNORE DROP: TSC on for %s" % (section_id))
