from django.conf.urls import url
from django.views.decorators.csrf import csrf_exempt
from events.consume import EnrollmentEvent


urlpatterns = [
    url(r'^enrollment', csrf_exempt(EnrollmentEvent().run)),
]
