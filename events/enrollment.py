import re
import json
from base64 import b64decode
from time import time
from math import floor
import dateutil.parser
from django.conf import settings
from django.utils.log import getLogger
from sis_provisioner.loader import Loader
from sis_provisioner.models import Enrollment as EnrollmentModel
from restclients.models.sws import Term, Section
from events.models import EnrollmentLog
from aws_message.crypto import aes128cbc, Signature, CryptoException


class EnrollmentException(Exception):
    pass


class Enrollment(object):
    """
    UW Course Enrollment Event Handler
    """

    # What we expect in an enrollment message
    _enrollmentMessageType = 'uw-student-registration'
    _enrollmentMessageVersion = '1'

    _header = None
    _body = None

    def __init__(self, settings, message):
        """
        UW Enrollment Event object

        Takes an object representing a UW Course Enrollment Message

        Raises EnrollmentException
        """
        self._settings = settings
        self._keys = self._settings.get('KEYS', {})
        self._message = message
        self._header = message['Header']
        self._body = message['Body']
        if self._header['MessageType'] != self._enrollmentMessageType:
            raise EnrollmentException('Unknown Message Type: '
                                      + str(self._header['MessageType']))

        self._log = getLogger(__name__)

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

            if 'PrimarySection' in event and 'Course' in event['PrimarySection']:
                primary_course = event['PrimarySection']['Course']
                if primary_course:
                    section.is_primary_section = False
                    section.primary_section_curriculum_abbr = primary_course['CurriculumAbbreviation']
                    section.primary_section_course_number = primary_course['CourseNumber']
                    section.primary_section_id = event['PrimarySection']['SectionID']

            code = event['Action']['Code'].upper()

            if code == 'A':
                status = EnrollmentModel.ACTIVE_STATUS
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
                'InstructorUWRegID': event['Instructor']['UWRegID'] if (
                    'Instructor' in event) else None
            }

            enrollments.append(data)

        loader = Loader()
        for enrollment in enrollments:
            try:
                loader.load_enrollment(enrollment)
            except Exception, err:
                raise EnrollmentException('Load enrollment failed: %s' % (
                    str(err)))

        self._recordSuccess(enrollments)

    def validate(self):
        t = self._header['Version']
        if t != self._enrollmentMessageVersion:
            raise EnrollmentException('Unknown Version: ' + t)

        to_sign = self._header['MessageType'] + '\n' \
            + self._header['MessageId'] + '\n' \
            + self._header['TimeStamp'] + '\n' \
            + self._body + '\n'

        sig_conf = {
            'cert': {
                'type': 'url',
                'reference': self._header['SigningCertURL']
            }
        }

        try:
            Signature(sig_conf).validate(to_sign.encode('ascii'),
                                         b64decode(self._header['Signature']))
        except CryptoException, err:
            raise EnrollmentException('Crypto: ' + str(err))
        except Exception, err:
            raise EnrollmentException('Invalid signature: ' + str(err))

    def _extract(self):
        try:
            t = self._header['Encoding']
            if str(t).lower() != 'base64':
                raise EnrollmentException('Unkown encoding: ' + t)

            t = self._header.get('Algorithm', 'aes128cbc')
            if str(t).lower() != 'aes128cbc':
                raise EnrollmentException('Unsupported algorithm: ' + t)

            t = self._header['KeyId']
            key = self._keys.get(t, None)
            if key is None:
                # no valid events
                self._log.error("Invalid KeyId: %s\nDROPPING: %s", (t, self._message))
                return { "Events": [] }

            # regex removes cruft around JSON
            rx = re.compile(r'[^{]*({.*})[^}]*')
            cipher = aes128cbc(b64decode(key), b64decode(self._header['IV']))
            b = cipher.decrypt(b64decode(self._body))
            return(json.loads(rx.sub(r'\g<1>', b)))
        except KeyError as err:
            self._log.error("Key Error: %s\nHEADER: %s" % (err, self._header));
            raise
        except CryptoException, err:
            raise EnrollmentException('Cannot decrypt: ' + str(err))
        except Exception, err:
            raise EnrollmentException('Cannot read: ' + str(err))

    def _recordSuccess(self, enrollments):
        minute = int(floor(time() / 60))
        count = len(enrollments)
        try:
            e = EnrollmentLog.objects.get(minute=minute)
            e.event_count += count
        except EnrollmentLog.DoesNotExist:
            e = EnrollmentLog(minute=minute, event_count=count)

        e.save()

        if e.event_count <= 5:
            limit = self._settings.get('EVENT_COUNT_PRUNE_AFTER_DAY', 7) * 24 * 60
            prune = minute - limit
            EnrollmentLog.objects.filter(minute__lt=prune).delete()
