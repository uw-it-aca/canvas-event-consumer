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
from sis_provisioner.cache import RestClientsCache
from restclients.models.sws import Term, Section
from restclients.kws import KWS
from restclients.exceptions import DataFailureException
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
        self._kws = KWS()
        self._settings = settings
        self._message = message
        self._header = message['Header']
        self._body = message['Body']
        self._re_guid = re.compile(r'^[\da-f]{8}(-[\da-f]{4}){3}-[\da-f]{12}$', re.I)
        if self._header['MessageType'] != self._enrollmentMessageType:
            raise EnrollmentException(
                'Unknown Message Type: %s' % (self._header['MessageType']))

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
            except Exception as err:
                raise EnrollmentException('Load enrollment failed: %s' % (err))

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
        except CryptoException as err:
            raise EnrollmentException('Crypto: %s' % (err))
        except Exception as err:
            raise EnrollmentException('Invalid signature: %s' % (err))

    def _extract(self):
        try:
            t = self._header['Encoding']
            if str(t).lower() != 'base64':
                raise EnrollmentException('Unkown encoding: ' + t)

            t = self._header.get('Algorithm', 'aes128cbc')
            if str(t).lower() != 'aes128cbc':
                raise EnrollmentException('Unsupported algorithm: ' + t)

            # regex removes cruft around JSON
            rx = re.compile(r'[^{]*({.*})[^}]*')
            key_id = self._header['KeyId']
            if key_id and re.match(self._re_guid, key_id):
                key = self._kws.get_key(key_id).key
                body = self._decryptBody(key)
            else:
                try:
                    key = self._kws.get_current_key(
                        self._header['MessageType']).key
                    body = self._decryptBody(key)
                    # look like json?
                    if not re.match(r'^\s*{.+}\s*$', body):
                        raise CryptoException()
                except (ValueError, CryptoException) as err:
                    RestClientsCache().delete_cached_kws_current_key(
                        self._header['MessageType'])
                    key = self._kws.get_current_key(
                        self._header['MessageType']).key
                    body = self._decryptBody(key)

            return(json.loads(rx.sub(r'\g<1>', body)))
        except KeyError as err:
            self._log.error("Key Error: %s\nHEADER: %s" % (err, self._header));
            raise
        except (ValueError, CryptoException) as err:
            raise EnrollmentException('Cannot decrypt: %s' % (err))
        except DataFailureException as err:
            msg = "Request failure for %s: %s (%s)" % (
                self.url, self.msg, self.status)
            self._log.error(msg)
            raise EnrollmentException(msg)
        except Exception as err:
            raise EnrollmentException('Cannot read: %s' % (err))

    def _decryptBody(self, key):
        cipher = aes128cbc(b64decode(key), b64decode(self._header['IV']))
        return cipher.decrypt(b64decode(self._body))

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
