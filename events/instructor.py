from sis_provisioner.models import Enrollment as EnrollmentModel
from events import EventBase, EventException
from events.models import InstructorLog
from restclients.models.sws import Section
from restclients.sws.term import get_term_by_year_and_quarter
from dateutil.parser import parse as date_parse


class InstructorEventBase(EventBase):
    def process_events(self, event):
        self._previous_instructors = self._instructors_from_section_json(
            event['Previous'])
        self._current_instructors = self._instructors_from_section_json(
            event['Current'])
        self._last_modified = date_parse(event['LastModified'])

        section_data = event['Current']
        course_data = section_data['Course']

        term = get_term_by_year_and_quarter(
            section_data['Term']['Year'], section_data['Term']['Quarter'])

        section = Section(
            term=term,
            curriculum_abbr=course_data['CurriculumAbbreviation'],
            course_number=course_data['CourseNumber'],
            section_id=section_data['SectionID'])

        campus = section_data['CourseCampus'].lower()
        tsc = dict((t.campus.lower(),
                    t.is_on) for t in term.time_schedule_construction)
        if campus not in tsc or tsc[campus]:
            message = "Ignoring: TSC not ready: %s" % (
                section.canvas_section_sis_id())
            if self._eventMessageType == 'uw-instructor-drop':
                self._log.error(message)
            else:
                self._log.warning(message)

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
                    for linked_section_data in linked_section_type["LinkedSections"]:
                        section = Section(
                            term=term,
                            curriculum_abbr=linked_section_data['Section']['CurriculumAbbreviation'],
                            course_number=linked_section_data['Section']['CourseNumber'],
                            section_id=linked_section_data['Section']['SectionID'],
                            is_primary_section=False)
                        sections.append(section)
            else:
                section.is_primary_section = True
                section.primary_section_curriculum_abbr = primary_section['CurriculumAbbreviation']
                section.primary_section_course_number = primary_section['CourseNumber']
                section.primary_section_id = primary_section['SectionID']
                sections.append(section)

        for section in sections:
            self.load_instructors(section)

    def gather(self, reg_id_list, status, section):
        enrollments = []
        for reg_id in reg_id_list:
            enrollments.append({
                'UWRegID': reg_id,
                'Section': section,
                'Role': EnrollmentModel.INSTRUCTOR_ROLE,
                'Status': status,
                'LastModified': self._last_modified
            })

        return enrollments

    def load_instructors(self, section):
        raise Exception('No load_instructors method')

    def _instructors_from_section_json(self, section):
        instructors = {}
        for meeting in section['Meetings']:
            for instructor in meeting['Instructors']:
                instructors[instructor['RegID']] = instructor

        return instructors.keys()


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
        add = [reg_id for reg_id in self._current_instructors \
               if reg_id not in self._previous_instructors]
        enrollments = self.gather(
            add, EnrollmentModel.ACTIVE_STATUS, section)
        self.load(enrollments)

    def record_success(self, event_count):
        self.record_success_to_log(InstructorLog, event_count)


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
        drop = [reg_id for reg_id in self._previous_instructors \
                if reg_id not in self._current_instructors]
        enrollments = self.gather(
            drop, EnrollmentModel.DELETED_STATUS, section)
        self.load(enrollments)

    def record_success(self, event_count):
        self.record_success_to_log(InstructorLog, event_count)
