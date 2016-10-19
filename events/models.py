from django.db import models


class GroupEvent(models.Model):
    """ Representation of a UW GWS Update Event
    """
    group_id = models.CharField(max_length=256)
    reg_id = models.CharField(max_length=32, unique=True)


class GroupRename(models.Model):
    """ Representation of a UW GWS Update Event
    """
    old_name = models.CharField(max_length=256)
    new_name = models.CharField(max_length=256)


class EnrollmentLog(models.Model):
    """ Record Event Frequency
    """
    minute = models.IntegerField(default=0)
    event_count = models.SmallIntegerField(default=0)


class GroupLog(models.Model):
    """ Record Event Frequency
    """
    minute = models.IntegerField(default=0)
    event_count = models.SmallIntegerField(default=0)


class InstructorLog(models.Model):
    """ Record Event Frequency
    """
    minute = models.IntegerField(default=0)
    event_count = models.SmallIntegerField(default=0)


class PersonLog(models.Model):
    """ Record Person Change Event Frequency
    """
    minute = models.IntegerField(default=0)
    event_count = models.SmallIntegerField(default=0)
