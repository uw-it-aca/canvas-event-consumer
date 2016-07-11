from django.http import HttpResponse
from django.conf import settings
from django.utils.log import getLogger
from sis_provisioner.views.rest_dispatch import RESTDispatch
from aws_message.aws import SNS, SNSException
from events import EventException
from events.enrollment import Enrollment
import json


log = getLogger('events.consume')


class EnrollmentEvent(RESTDispatch):
    """
    AWS SNS delivered UW Course Registration Event handler
    """

    _topicArn = None
    _keys = []

    def __init__(self):
        self._topicArn = settings.AWS_SQS['ENROLLMENT']['TOPIC_ARN']

    def POST(self, request, **kwargs):
        try:
            aws_msg = json.loads(request.body)
            log.info(aws_msg['Type'] + ' on ' + aws_msg['TopicArn'])
            if aws_msg['TopicArn'] == self._topicArn:
                aws = SNS(aws_msg)

                if settings.EVENT_VALIDATE_SNS_SIGNATURE:
                    aws.validate()

                if aws_msg['Type'] == 'Notification':
                    enrollment = Enrollment(aws.extract())

                    if settings.EVENT_VALIDATE_ENROLLMENT_SIGNATURE:
                        enrollment.validate()

                    enrollment.process()
                elif aws_msg['Type'] == 'SubscriptionConfirmation':
                    log.info('SubscribeURL: ' + aws_msg['SubscribeURL'])
                    aws.subscribe()
            else:
                log.error('Unrecognized TopicARN : ' + aws_msg['TopicArn'])
                return self.error_response(400, "Invalid TopicARN")
        except ValueError as err:
            log.error('JSON : %s' % err)
            return self.error_response(400, "Invalid JSON")
        except EventException, err:
            log.error("ENROLLMENT: " + str(err))
            return self.error_response(500, "Internal Server Error")
        except SNSException, err:
            log.error("SNS: " + str(err))
            return self.error_response(401, "Authentication Failure")
        except Exception, err:
            log.error(str(err))
            return self.error_response(500, "Internal Server Error")

        return HttpResponse()
