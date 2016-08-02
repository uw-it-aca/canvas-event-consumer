from django.conf.urls import patterns, url
from django.views.decorators.csrf import csrf_exempt
from events.consume import EnrollmentEvent


urlpatterns = patterns(
    '',
    url(r'^enrollment', csrf_exempt(EnrollmentEvent().run)),
)
