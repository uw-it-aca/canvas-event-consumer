import re
import datetime
from django.conf import settings
from logging import getLogger
from django.utils.timezone import utc
from sis_provisioner.dao.user import valid_net_id, valid_gmail_id
from sis_provisioner.dao.group import get_effective_members
from sis_provisioner.dao.course import group_section_sis_id,\
    valid_academic_course_sis_id
from sis_provisioner.exceptions import UserPolicyException,\
    GroupPolicyException, GroupNotFoundException, GroupUnauthorizedException,\
    CoursePolicyException
from sis_provisioner.models import Group as GroupModel
from sis_provisioner.models import CourseMember as CourseMemberModel
from sis_provisioner.models import GroupMemberGroup as GroupMemberGroupModel
from sis_provisioner.models import User as UserModel
from sis_provisioner.models import Enrollment as EnrollmentModel
from sis_provisioner.models import PRIORITY_NONE, PRIORITY_DEFAULT,\
    PRIORITY_HIGH, PRIORITY_IMMEDIATE
from restclients.gws import GWS
from restclients.canvas.enrollments import Enrollments
from restclients.exceptions import DataFailureException
from events.group.extract import ExtractUpdate, ExtractDelete, ExtractChange


class Dispatch(object):
    """
    Base class for dispatching on actions within a UW GWS Event
    """
    def __init__(self, config, message):
        self._log = getLogger(__name__)

        self._settings = config
        self._message = message

    def mine(self, group):
        return True

    def run(self, action, group):
        try:
            return {
                'update-members': self.update_members,
                'put-group': self.put_group,
                'delete-group': self.delete_group,
                'put-members': self.put_members,
                'change-subject-name': self.change_subject_name,
                'no-action': self.no_action
            }[action](group)
        except KeyError:
            self._log.info('UNKNOWN ACTION "%s" on "%s"' % (action, group))
            return 0

    def update_members(self, group_id):
        # event = ExtractUpdate(self._settings, self._message).extract()
        self._log.info('ignoring update-members: %s' % group_id)
        return 0

    def put_group(self, group_id):
        # event = ExtractPutGroup(self._settings, self._message).extract()
        self._log.info('ignoring put-group: %s' % group_id)
        return 0

    def delete_group(self, group_id):
        # event = ExtractDelete(self._settings, self._message).extract()
        self._log.info('ignoring delete-group: %s' % group_id)
        return 0

    def put_members(self, group_id):
        # event = ExtractPutMembers(self._settings, self._message).extract()
        self._log.info('ignoring put-members: %s' % group_id)
        return 0

    def change_subject_name(self, group_id):
        # event = ExtractChange(self._settings, self._message).extract()
        self._log.info('ignoring change-subject-name: %s' % group_id)
        return 0

    def no_action(self, group_id):
        self._log.info('no-action')
        return 0


class UWGroupDispatch(Dispatch):
    """
    Canvas Enrollment Group Event Dispatcher
    """
    def __init__(self, config, message):
        super(UWGroupDispatch, self).__init__(config, message)
        self._enrollments = Enrollments()
        self._gws = GWS()
        self._valid_members = []

    def mine(self, group):
        self._groups = GroupModel.objects.filter(group_id=group)
        self._membergroups = GroupMemberGroupModel \
            .objects.filter(group_id=group)
        return len(self._groups) > 0 or len(self._membergroups) > 0

    def update_members(self, group_id):
        # body contains list of members to be added or removed
        event = ExtractUpdate(self._settings, self._message).extract()

        self._log.info('update_members: "%s"' % (event.group_id))
        updates = [{
            'members': event.add_members,
            'is_deleted': None
        }, {
            'members': event.delete_members,
            'is_deleted': True
        }]

        for update in updates:
            for member in update['members']:
                for group in self._groups:
                    if not group.is_deleted:
                        self._update_group(group, member, update['is_deleted'])

                for member_group in self._membergroups:
                    if not member_group.is_deleted:
                        for group in GroupModel.objects.filter(
                                group_id=member_group.root_group_id,
                                is_deleted__isnull=True):
                            self._update_group(group, member,
                                               update['is_deleted'])

        return len(event.add_members) + len(event.delete_members)

    def delete_group(self, group_id):
        event = ExtractDelete(self._settings, self._message).extract()
        self._log.info('DELETE: "%s"' % (event.group_id))

        now = datetime.datetime.utcnow().replace(tzinfo=utc)
        # mark group as delete and ready for import
        GroupModel.objects \
                  .filter(group_id=event.group_id,
                          is_deleted__isnull=True) \
                  .update(is_deleted=True,
                          deleted_date=now,
                          deleted_by='gws-event',
                          priority=PRIORITY_IMMEDIATE)

        # mark member groups
        membergroups = GroupMemberGroupModel.objects.filter(
            group_id=event.group_id, is_deleted__isnull=True)
        membergroups.update(is_deleted=True)

        # mark associated root groups for import
        for membergroup in membergroups:
            GroupModel.objects.filter(group_id=membergroup.root_group_id,
                                      is_deleted__isnull=True) \
                              .update(priority=PRIORITY_IMMEDIATE)

        return 1

    def change_subject_name(self, group_id):
        event = ExtractChange(self._settings, self._message).extract()

        self._log.info('change_subject_name: "%s" to "%s"' % (
            event.old_name, event.new_name))

        GroupModel.objects \
                  .filter(group_id=event.old_name) \
                  .update(group_id=event.new_name)
        GroupMemberGroupModel.objects \
                             .filter(group_id=event.old_name) \
                             .update(group_id=event.new_name)
        GroupMemberGroupModel.objects \
                             .filter(root_group_id=event.old_name) \
                             .update(root_group_id=event.new_name)
        return 1

    def _update_group(self, group, member, is_deleted):
        if member.is_group():
            self._update_group_member_group(group, member.name, is_deleted)
        elif member.is_uwnetid() or member.is_eppn():
            try:
                if member.name not in self._valid_members:
                    if member.is_uwnetid():
                        valid_net_id(member.name)
                    elif member.is_eppn():
                        valid_gmail_id(member.name)
                    self._valid_members.append(member.name)

                self._update_group_member(group, member, is_deleted)
            except UserPolicyException:
                self._log.info('policy fail: %s' % (member.name))
        else:
            self._log.info('unused type %s (%s)' % (
                member.member_type, member.name))

    def _update_group_member_group(self, group, member_group, is_deleted):
        try:
            # validity is confirmed by act_as
            (valid, invalid, member_groups) = get_effective_members(
                member_group, act_as=group.added_by)
        except GroupNotFoundException as err:
            GroupMemberGroupModel.objects \
                                 .filter(group_id=member_group) \
                                 .update(is_deleted=True)
            self._log.error("Member group %s NOT in %s" % (
                member_group, group.group_id))
            return
        except (GroupPolicyException, GroupUnauthorizedException) as err:
            self._log.error(err)
            return

        for member in valid:
            self._update_group_member(group, member, is_deleted)

        for mg in [member_group] + member_groups:
            (gmg, created) = GroupMemberGroupModel.objects.get_or_create(
                group_id=mg, root_group_id=group.group_id)
            gmg.is_deleted = is_deleted
            gmg.save()

    def _update_group_member(self, group, member, is_deleted):
        # validity is assumed if the course model exists
        if member.is_uwnetid():
            user_id = member.name
        elif member.is_eppn():
            user_id = valid_gmail_id(member.name)
        else:
            return

        try:
            (cm, created) = CourseMemberModel.objects.get_or_create(
                name=user_id, member_type=member.member_type,
                course_id=group.course_id, role=group.role)
        except CourseMemberModel.MultipleObjectsReturned:
            models = CourseMemberModel.objects.filter(
                name=user_id, member_type=member.member_type,
                course_id=group.course_id, role=group.role)
            self._log.debug('MULTIPLE (%s): %s in %s as %s'
                            % (len(models), user_id,
                               group.course_id, group.role))
            cm = models[0]
            created = False
            for m in models[1:]:
                m.delete()

        if is_deleted:
            # user in other member groups not deleted
            if self._user_in_member_group(group, member):
                is_deleted = None
        elif self._user_in_course(group, member):
            # official student/instructor not added via group
            is_deleted = True

        cm.is_deleted = is_deleted
        cm.priority = PRIORITY_DEFAULT if not cm.queue_id else PRIORITY_HIGH
        cm.save()

        self._log.info('groups: %s %s to %s as %s' % (
            'deleted' if is_deleted else 'active',
            user_id, group.course_id, group.role))

    def _user_in_member_group(self, group, member):
        if self._has_member_groups(group):
            self._gws.actas = group.added_by
            return self._gws.is_effective_member(group.group_id, member.name)

        return False

    def _user_in_course(self, group, member):
        # academic course?
        try:
            valid_academic_course_sis_id(group.course_id)
        except CoursePolicyException:
            return False

        # provisioned to academic section?
        try:
            user = UserModel.objects.get(net_id=member.name)
            EnrollmentModel.objects.get(
                reg_id=user.reg_id,
                course_id__startswith=group.course_id,
                status='active')
            return True
        except UserModel.DoesNotExist:
            return False
        except EnrollmentModel.DoesNotExist:
            pass

        # inspect Canvas Enrollments
        try:
            params = {'user_id': self._enrollments.sis_user_id(user.reg_id)}
            for e in self._enrollments.get_enrollments_for_course_by_sis_id(
                    group.course_id, params=params):
                if e.sis_section_id != group_section_sis_id(group.course_id):
                    return True
        except DataFailureException as err:
            if err.status == 404:
                pass            # No enrollment
            else:
                raise

        return False

    def _has_member_groups(self, group):
        return GroupMemberGroupModel.objects.filter(
            root_group_id=group.group_id,
            is_deleted__isnull=True).count() > 0


class ImportGroupDispatch(Dispatch):
    """
    Import Group Dispatcher
    """
    def mine(self, group):
        return True if group in settings.SIS_IMPORT_GROUPS else False

    def update_members(self, group):
        # body contains list of members to be added or removed
        self._log.info('ignoring Canvas user update: %s' % (group))
        return 0


class CourseGroupDispatch(Dispatch):
    """
    Course Group Dispatcher
    """
    def mine(self, group):
        course = ('course_' in group and re.match(
            (r'^course_(20[0-9]{2})'
             r'([a-z]{3})-([a-z\-]+)'
             r'([0-9]{3})([a-z][a-z0-9]?)$'), group))
        if course:
            self._course_sis_id = '-'.join([
                course.group(1),
                {'win': 'winter', 'spr': 'spring', 'sum': 'summer',
                    'aut': 'autumn'}[course.group(2)],
                re.sub('\-', ' ', course.group(3).upper()),
                course.group(4), course.group(5).upper()
            ])
            return True

        return False

    def update_members(self, group):
        # body contains list of members to be added or removed
        self._log.info('ignoring Course Group update: %s' % (
            self._course_sis_id))
        return 0

    def put_group(self, group_id):
        self._log.info('ignoring Course Group put-group: %s' % group_id)
        return 0
