from sis_provisioner.loader import Loader
from events import EventBase, EventException
from restclients.models.sws import Section


class InstructorEventBase(EventBase):
    def process_events(self, event):
        # raw Section json is lighter weight than restclient Section model
        self._previous_instructors = self._instructors_from_section_json(
            event['Previous'])

        self._current_instructors = self._instructors_from_section_json(
            event['Current'])

        self._course_id = self._course_id_from_section_json(event['Current'])

        self.load_instructors()

    def _instructors_from_section_json(self, section):
        instructors = {}
        for meeting in section['Meetings']:
            for instructor in meeting['Instructors']:
                instructors[instructor['RegID']] = instructor

        return instructors.keys()

    def _course_id_from_section_json(self, section):
        return "%s-%s-%s-%s" % (
            section['Course']['Year'],
            section['Course']['Quarter'],
            section['Course']['CurriculumAbbreviation'],
            section['Course']['CourseNumber'])


class InstructorAdd(InstructorEventBase):
    """
    UW Course Instructor Add Event Handler
    """
    SETTINGS_NAME = 'INSTRUCTOR_ADD'
    EXCEPTION_CLASS = EventException

    # What we expect in an enrollment message
    _eventMessageType = 'uw-instructor-add'
    _eventMessageVersion = '1'

    def load_instructors(self):
        add = [regid for regid in self._current_instructors \
               if regid not in self._previous_instructors]
        if len(add):
            Loader().load_added_instructors(add, self._course_id)
            self.recordSuccess(InstructorLog, 1)


class InstructorDrop(InstructorEventBase):
    """
    UW Course Instructor Drop Event Handler
    """
    SETTINGS_NAME = 'INSTRUCTOR_DROP'
    EXCEPTION_CLASS = EventException

    # What we expect in an enrollment message
    _eventMessageType = 'uw-instructor-drop'
    _eventMessageVersion = '1'

    def load_instructors(self):
        drop = [regid for regid in self._previous_instructors \
                if regid not in self._current_instructors]
        if len(drop):
            Loader().load_dropped_instructors(drop, self._course_id)
            self.recordSuccess(InstructorLog, 1)
