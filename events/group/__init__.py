import json
from base64 import b64decode
from time import time
from math import floor
import dateutil.parser
from django.utils.log import getLogger
from events.models import GroupLog
from events.group.dispatch import ImportGroupDispatch, CourseGroupDispatch
from events.group.dispatch import UWGroupDispatch, Dispatch
from aws_message.extract import ExtractException


class GroupException(Exception):
    pass


class Group(object):
    """
    UW GWS Group Event Processor
    """

    # What we expect in a UW Group event message
    _groupMessageType = 'gws'
    _groupMessageVersion = 'UWIT-1'

    def __init__(self, config, message):
        """
        UW Group Event object

        Takes an object representing a UW Group Event Message

        Raises GroupException
        """
        self._log = getLogger(__name__)
        self._settings = config

        header = message['header']

        if header['messageType'] != self._groupMessageType:
            raise GroupException('Unknown Group Message Type: '
                                 + str(header['messageType']))

        if header['version'] != self._groupMessageVersion:
            raise GroupException('Unknown Group Message Version: '
                                 + str(header['version']))

        context = json.loads(b64decode(header['messageContext']))
        self._action = context['action']
        self._groupname = context['group']

        for dispatch in [ImportGroupDispatch,
                         CourseGroupDispatch,
                         UWGroupDispatch,
                         Dispatch]:
            self._dispatch = dispatch(config, message)
            if self._dispatch.mine(self._groupname):
                break

    def process(self):
        try:
            n = self._dispatch.run(self._action, self._groupname)
            if n:
                self._recordSuccess(n)
        except ExtractException as err:
            raise GroupException('Cannot process: %s' % (err))

    def _recordSuccess(self, count):
        minute = int(floor(time() / 60))
        try:
            e = GroupLog.objects.get(minute=minute)
            e.event_count += count
        except GroupLog.DoesNotExist:
            e = GroupLog(minute=minute, event_count=count)

        e.save()

        if e.event_count <= 5:
            prune = minute - (self._settings.get(
                'EVENT_COUNT_PRUNE_AFTER_DAY', 7) * 24 * 60)
            GroupLog.objects.filter(minute__lt=prune).delete()
