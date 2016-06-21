from django.conf import settings
from django.utils.log import getLogger
from sis_provisioner.cache import RestClientsCache
from restclients.kws import KWS
from restclients.exceptions import DataFailureException
from events.models import EnrollmentLog
from aws_message.crypto import aes128cbc, Signature, CryptoException
from base64 import b64decode
from time import time
from math import floor
import json
import re


class EventException(Exception):
    pass


class EventBase(object):
    """
    UW Course Enrollment Event Handler
    """

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
        self._re_guid = re.compile(
            r'^[\da-f]{8}(-[\da-f]{4}){3}-[\da-f]{12}$', re.I)
        if self._header['MessageType'] != self._enrollmentMessageType:
            raise EnrollmentException(
                'Unknown Message Type: %s' % (self._header['MessageType']))

        self._log = getLogger(__name__)

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
            key = None
            if 'KeyURL' in self._header:
                key = self._kws._key_from_json(
                    self._kws._get_resource(self._header['KeyURL']))
            elif 'KeyId' in self._header:
                key = self._kws.get_key(self._header['KeyId'])
            else:
                try:
                    key = self._kws.get_current_key(
                        self._header['MessageType'])
                    if not re.match(r'^\s*{.+}\s*$', body):
                        raise CryptoException()
                except (ValueError, CryptoException) as err:
                    RestClientsCache().delete_cached_kws_current_key(
                        self._header['MessageType'])
                    key = self._kws.get_current_key(
                        self._header['MessageType'])

            cipher = aes128cbc(b64decode(key.key),
                               b64decode(self._header['IV']))
            body = cipher.decrypt(b64decode(self._body))
            return(json.loads(rx.sub(r'\g<1>', body)))
        except KeyError as err:
            self._log.error(
                "Key Error: %s\nHEADER: %s" % (err, self._header))
            raise
        except (ValueError, CryptoException) as err:
            raise EnrollmentException('Cannot decrypt: %s' % (err))
        except DataFailureException as err:
            msg = "Request failure for %s: %s (%s)" % (
                err.url, err.msg, err.status)
            self._log.error(msg)
            raise EnrollmentException(msg)
        except Exception as err:
            raise EnrollmentException('Cannot read: %s' % (err))

    def recordSuccess(self, log_model, events):
        minute = int(floor(time() / 60))
        count = len(events)
        try:
            e = log_model.objects.get(minute=minute)
            e.event_count += count
        except log_model.DoesNotExist:
            e = log_model(minute=minute, event_count=count)

        e.save()

        if e.event_count <= 5:
            limit = self._settings.get(
                'EVENT_COUNT_PRUNE_AFTER_DAY', 7) * 24 * 60
            prune = minute - limit
            log_model.objects.filter(minute__lt=prune).delete()

