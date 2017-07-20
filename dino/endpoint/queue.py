# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import traceback
import time

from datetime import datetime
from uuid import uuid4 as uuid
from activitystreams.models.activity import Activity

from dino.config import ConfigKeys
from dino.exceptions import NoSuchUserException
from dino.environ import GNEnvironment
from dino import environ
from dino import utils

__author__ = 'Oscar Eriksson <oscar.eriks@gmail.com>'

logger = logging.getLogger(__name__)


class QueueHandler(object):
    def __init__(self, socketio, env: GNEnvironment):
        self.socketio = socketio
        self.env = env
        self.recently_delegated_events = list()
        self.recently_delegated_events_set = set()
        self.recently_handled_events = list()
        self.recently_handled_events_set = set()

    def user_is_on_this_node(self, activity: Activity) -> bool:
        if self.env.node != 'app':
            return False

        room_id = activity.target.id
        namespace = activity.target.url or '/ws'
        user_id = activity.object.id
        user_sid = utils.get_sid_for_user_id(user_id)
        users = list()

        try:
            if room_id is None:
                logger.debug('checking if we have user %s in namespace %s' % (user_id, namespace))
                if user_sid in self.socketio.server.manager.rooms[namespace]:
                    logger.debug('found users %s on this node' % user_id)
                    return True
                else:
                    logger.info('no user %s for namespace [%s] (or user not on this node)' % (room_id, namespace))
                    return False

            else:
                logger.debug('checking if we have room %s in namespace %s' % (room_id, namespace))
                if room_id in self.socketio.server.manager.rooms[namespace]:
                    users = self.socketio.server.manager.rooms[namespace][room_id]
                    logger.debug('found users for room %s: %s' % (room_id, str(users)))
                else:
                    logger.warning('no room %s for namespace [%s] (or room is empty/removed)' % (room_id, namespace))
                return user_sid in users

        except KeyError as e:
            logger.warn('namespace %s does not exist (maybe this is web/rest node?): %s' % (namespace, str(e)))
            return False
        except Exception as e:
            logger.error('could not get users for namespace "%s" and room "%s": %s' % (namespace, room_id, str(e)))
            logger.exception(traceback.format_exc())
            return False

    def create_ban_even_if_not_on_this_node(self, activity: Activity) -> None:
        """
        since bans can be created through the rest api we need to create the ban even though the user might not be on
        this node, since one reason could be that he's not even connected. So make sure the ban is created first.
        """
        banned_id = activity.object.id
        target_type = activity.target.object_type

        if target_type == 'room':
            target_id = activity.target.id
        elif target_type == 'channel':
            target_id = activity.target.id
        else:
            target_type = 'global'
            target_id = ''

        reason = None
        if hasattr(activity.object, 'content'):
            reason = activity.object.content

        try:
            ban_duration = activity.object.summary
            ban_timestamp = utils.ban_duration_to_timestamp(ban_duration)
            activity.object.updated = utils.ban_duration_to_datetime(ban_duration)\
                .strftime(ConfigKeys.DEFAULT_DATE_FORMAT)
            banner_id = activity.actor.id

            self.send_ban_event_to_external_queue(activity, target_type)

            if target_type == 'global':
                logger.info('banning user %s globally for %s' % (banned_id, ban_duration))
                self.env.db.ban_user_global(banned_id, ban_timestamp, ban_duration, reason, banner_id)
            elif target_type == 'channel':
                logger.info('banning user %s in channel %s for %s' % (banned_id, target_id, ban_duration))
                self.env.db.ban_user_channel(banned_id, ban_timestamp, ban_duration, target_id, reason, banner_id)
            else:
                logger.info('banning user %s in room %s for %s' % (banned_id, target_id, ban_duration))
                self.env.db.ban_user_room(banned_id, ban_timestamp, ban_duration, target_id, reason, banner_id)
        except KeyError as ke:
            logger.error('could not ban: %s' % str(ke))
            logger.exception(traceback.format_exc())

    def update_recently_delegated_events(self, activity_id: str) -> None:
        self.recently_delegated_events.append(activity_id)
        self.recently_delegated_events_set.add(activity_id)
        if len(self.recently_delegated_events) > 100:
            self.recently_delegated_events_set.remove(self.recently_delegated_events[0])
            del self.recently_delegated_events[0]

    def update_recently_handled_events(self, activity_id: str) -> None:
        self.recently_handled_events.append(activity_id)
        self.recently_handled_events_set.add(activity_id)
        if len(self.recently_handled_events) > 100:
            self.recently_handled_events_set.remove(self.recently_handled_events[0])
            del self.recently_handled_events[0]

    def handle_local_node_events(self, data: dict, activity: Activity):
        # do this first, since ban might occur even if user is not connected
        logger.info(data)
        if activity.verb == 'ban':
            user_is_on_node = True

            # delegate so we don't end up re-reading this event before adding to ignore list
            if not self.user_is_on_this_node(activity):
                logger.info('user is not on this node, will publish on queue for other nodes to try')
                self.update_recently_delegated_events(activity.id)
                environ.env.publish(data)
                user_is_on_node = False

            self.create_ban_even_if_not_on_this_node(activity)

            # no need to continue if the user is not on this node; event already delegated
            if not user_is_on_node:
                return

            try:
                self.handle_ban(activity)
            except Exception as e:
                logger.error('could not handle ban: %s' % str(e))
                logger.exception(traceback.format_exc())

        elif activity.verb == 'kick':
            try:
                self.handle_kick(activity)
            except Exception as e:
                logger.error('could not handle kick: %s' % str(e))
                logger.exception(traceback.format_exc())

        elif activity.verb == 'remove':
            try:
                self.handle_remove(data, activity)
            except Exception as e:
                logger.error('could not emit remove activity to clients: %s' % str(e))
                logger.exception(traceback.format_exc())

    def handle_server_activity(self, data: dict, activity: Activity) -> None:
        try:
            self._handle_server_activity(data, activity)
        except Exception as e:
            logger.error('could not handle server activity: %s' % str(e))
            logger.exception(traceback.format_exc())

    def _handle_server_activity(self, data: dict, activity: Activity) -> None:
        if activity.id in self.recently_delegated_events_set:
            logger.info('ignoring event with id %s since we delegated from this node' % activity.id)
            return
        if activity.id in self.recently_handled_events_set:
            logger.info('ignoring event with id %s since we already handled it on this node' % activity.id)
            return

        logger.debug('got internally published event with verb %s id %s' % (activity.verb, activity.id))
        self.update_recently_handled_events(activity.id)

        if activity.verb in ['ban', 'kick', 'remove']:
            self.handle_local_node_events(data, activity)
        else:
            # otherwise it's external events for possible analysis
            environ.env.publish(data, external=True)

    def kick(self, orig_data: dict, activity: Activity, room_id: str, user_id: str, user_sid: str, namespace: str) -> None:
        if room_id is None:
            raise RuntimeError('trying to kick when room is none')

        try:
            _users = list()
            if room_id in self.socketio.server.manager.rooms[namespace]:
                _users = self.socketio.server.manager.rooms[namespace][room_id]
            else:
                logger.warning('no room %s for namespace [%s] (or room is empty/removed)' % (room_id, namespace))
        except Exception as e:
            logger.error('could not get users for namespace "%s" and room "%s": %s' % (namespace, room_id, str(e)))
            logger.exception(traceback.format_exc())
            return

        data = orig_data.copy()
        data['target'] = {
            'id': room_id
        }

        self.env.out_of_scope_emit('gn_user_kicked', data, json=True, namespace=namespace, room=room_id, broadcast=True)
        self.send_kick_event_to_external_queue(activity)

        if user_sid in _users:
            logger.info('about to kick user %s' % user_sid)
            try:
                self.socketio.server.leave_room(user_sid, room_id, '/ws')
            except Exception as e:
                logger.error('could not kick user %s from room %s: %s' % (user_id, room_id, str(e)))
                logger.exception(traceback.format_exc())

            try:
                self.env.db.leave_room(user_id, room_id)
            except Exception as e:
                logger.warning('could not remove user from room in db (maybe room is already deleted): %s' % str(e))

        self.delete_for_user_in_room(user_id, room_id)

    def ban_room(self, data: dict, act: Activity, room_id: str, user_id: str, user_sid: str, namespace: str) -> None:
        self.env.out_of_scope_emit(
                'gn_user_banned', data, json=True, namespace=namespace, room=room_id, broadcast=True)
        if act.actor.id != '0':
            self.env.out_of_scope_emit(
                     'gn_user_banned', data, json=True, namespace=namespace, room=act.actor.id, broadcast=True)

        try:
            self.kick(data, act, room_id, user_id, user_sid, namespace)
        except Exception as e:
            logger.error('could not ban user %s from room %s: %s' % (user_id, room_id, str(e)))
            return

        self.delete_for_user_in_room(user_id, room_id)

    def ban_channel(self, data: dict, activity: Activity, rooms_in_channel, channel_id, user_id, user_sid, namespace):
        try:
            if activity.actor.id != '0':
                self.env.out_of_scope_emit(
                        'gn_user_banned', data, json=True, namespace=namespace, room=activity.actor.id, broadcast=True)
            for room_id in rooms_in_channel:
                self.env.out_of_scope_emit(
                        'gn_user_banned', data, json=True, namespace=namespace, room=room_id, broadcast=True)
                self.kick(data, activity, room_id, user_id, user_sid, namespace)
        except Exception as e:
            logger.error('could not ban user %s from channel %s: %s' % (user_id, channel_id, str(e)))
            logger.exception(traceback.format_exc(e))
            return

        for room_id in rooms_in_channel:
            self.delete_for_user_in_room(user_id, room_id)

    def ban_globally(self, data: dict, act: Activity, rooms: dict, user_id: str, user_sid: str, namespace: str) -> None:
        try:
            if len(rooms) == 0:
                logger.warn('rooms to ban globally for is empty for user %s' % user_id)
            for room_id, room_name in rooms.items():
                self.env.out_of_scope_emit(
                        'gn_user_banned', data, json=True, namespace=namespace, room=room_id, broadcast=True)
                self.kick(data, act, room_id, user_id, user_sid, namespace)
        except Exception as e:
            logger.error('could not ban user %s globally: %s' % (user_id, str(e)))
            logger.exception(traceback.format_exc(e))
            return

    def delete_for_user_in_room(self, user_id: str, room_id: str):
        try:
            before = time.time()
            messages = self.env.storage.get_undeleted_message_ids_for_user_and_room(user_id, room_id)
            logger.info('about to delete %s messages for user %s (fetching IDs took %.2fs)' % (len(messages), user_id, time.time()-before))
        except Exception as e:
            logger.error('could not get undeleted messages: %s' % str(e))
            logger.exception(traceback.format_exc())
            return
        self.delete_messages(user_id, messages)

    def delete_messages(self, user_id: str, messages: list) -> None:
        if messages is None or len(messages) == 0:
            return

        before = time.time()
        successes, failures = self.try_to_delete_messages(messages)
        elapsed = time.time() - before
        logger.info('finished deleting %s messages (%s/%s successes) for user %s (deletion took %.2fs)' %
                    (len(messages), successes, len(messages), user_id, elapsed))

    def try_to_delete_messages(self, messages) -> (int, int):
        try:
            failures = 0
            successes = 0

            for message_id in messages:
                try:
                    self.env.storage.delete_message(message_id)
                    successes += 1
                except Exception as e:
                    logger.error('could not delete message with id %s because: %s' % (message_id, str(e)))
                    logger.exception(traceback.format_exc())
                    failures += 1
            return successes, failures
        except Exception as e2:
            logger.error('could not delete messages: %s' % str(e2))
            logger.exception(traceback.format_exc())

        return 0, len(messages)

    def handle_kick(self, activity: Activity):
        kicker_id = activity.actor.id
        if kicker_id == '0':
            kicker_name = 'admin'
        else:
            try:
                kicker_name = activity.actor.display_name or utils.get_user_name_for(kicker_id)
            except NoSuchUserException:
                # if kicking from rest api the user might not exist
                logger.error('no such user when kicking: %s' % kicker_id)
                return

        kicked_id = activity.object.id
        kicked_name = activity.object.display_name or utils.get_user_name_for(kicked_id)
        kicked_sid = utils.get_sid_for_user_id(kicked_id)
        room_id = activity.target.id

        if room_id is not None:
            room_name = utils.get_room_name(room_id)
        else:
            room_name = activity.target.display_name
        namespace = activity.target.url

        if kicked_sid is None or kicked_sid == [None] or kicked_sid == '':
            logger.warning('no sid found for user id %s' % kicked_id)
            return

        reason = None
        if hasattr(activity.object, 'content'):
            reason = activity.object.content

        activity_json = utils.activity_for_user_kicked(
                kicker_id, kicker_name, kicked_id, kicked_name, room_id, room_name, reason)

        try:
            # user just got banned globally, kick from all rooms
            if room_id is None or room_id == '':
                room_keys = self.env.db.rooms_for_user(kicked_id).copy().keys()
                for room_key in room_keys:
                    self.kick(activity_json, activity, room_key, kicked_id, kicked_sid, namespace)
            else:
                self.kick(activity_json, activity, room_id, kicked_id, kicked_sid, namespace)
        except KeyError as e:
            logger.error('could not kick user %s: %s' % (kicked_id, str(e)))

    def handle_ban(self, activity: Activity):
        banner_id = activity.actor.id
        if banner_id == '0':
            banner_name = 'admin'
        else:
            try:
                banner_name = utils.get_user_name_for(banner_id)
            except NoSuchUserException:
                # if banning from rest api the user might not exist
                logger.error('no such user when banning: %s' % banner_id)
                return

        banned_id = activity.object.id
        banned_name = utils.get_user_name_for(banned_id)
        banned_sid = utils.get_sid_for_user_id(banned_id)
        namespace = activity.target.url or '/ws'
        target_type = activity.target.object_type

        if target_type == 'room':
            target_id = activity.target.id
            target_name = utils.get_room_name(target_id)
        elif target_type == 'channel':
            target_id = activity.target.id
            target_name = utils.get_channel_name(target_id)
        else:
            target_id = ''
            target_name = ''

        if banned_sid is None or banned_sid == [None] or banned_sid == '':
            logger.warn('no sid found for user id %s' % banned_id)
            return

        reason = None
        if hasattr(activity.object, 'content'):
            reason = activity.object.content

        activity_json = utils.activity_for_user_banned(
                banner_id, banner_name, banned_id, banned_name, target_id, target_name, reason)

        try:
            if target_id is None or target_id == '':
                rooms_for_user = self.env.db.rooms_for_user(banned_id)
                logger.info('user %s is in these rooms (will ban from all): %s' % (banned_id, str(rooms_for_user)))
                self.ban_globally(activity_json, activity, rooms_for_user, banned_id, banned_sid, namespace)
                self.env.db.set_user_offline(banned_id)
                disconnect_activity = utils.activity_for_disconnect(banned_id, banned_name)
                self.env.publish(disconnect_activity, external=True)

            elif target_type == 'channel':
                rooms_in_channel = self.env.db.rooms_for_channel(target_id)
                self.ban_channel(activity_json, activity, rooms_in_channel, target_id, banned_id, banned_sid, namespace)
            else:
                self.ban_room(activity_json, activity, target_id, banned_id, banned_sid, namespace)

            ban_activity = self.get_ban_activity(activity, target_type)
            self.env.out_of_scope_emit(
                    'gn_banned', ban_activity, json=True, namespace=namespace,
                    room=utils.get_sid_for_user_id(banned_id))

        except KeyError as ke:
            logger.error('could not ban: %s' % str(ke))
            logger.exception(traceback.format_exc())

    def get_ban_activity(self, activity: Activity, target_type: str) -> dict:
        ban_activity = {
            'actor': {
                'id': activity.actor.id,
                'displayName': activity.actor.display_name
            },
            'verb': 'ban',
            'object': {
                'id': activity.object.id,
                'displayName': activity.object.display_name,
                'summary': activity.object.summary,
                'updated': activity.object.updated
            },
            'id': str(uuid()),
            'published': datetime.utcnow().strftime(ConfigKeys.DEFAULT_DATE_FORMAT)
        }

        reason = None
        if activity.object is not None:
            reason = activity.object.content
        if reason is not None and len(reason.strip()) > 0:
            ban_activity['object']['content'] = reason

        ban_activity['target'] = {
            'objectType': target_type
        }

        # when banning globally, not target room is specified
        if activity.target is not None:
            ban_activity['target']['id'] = activity.target.id
            ban_activity['target']['displayName'] = activity.target.display_name
            ban_activity['target']['objectType'] = activity.target.object_type

        return ban_activity

    def send_ban_event_to_external_queue(self, activity: Activity, target_type: str) -> None:
        ban_activity = self.get_ban_activity(activity, target_type)
        logger.debug('publishing ban event to external queue: %s' % ban_activity)
        self.env.publish(ban_activity, external=True)

    def send_kick_event_to_external_queue(self, activity: Activity) -> None:
        kick_activity = {
            'actor': {
                'id': activity.actor.id,
                'displayName': activity.actor.display_name
            },
            'verb': 'kick',
            'object': {
                'id': activity.object.id,
                'displayName': activity.object.display_name
            },
            'id': str(uuid()),
            'published': datetime.utcnow().strftime(ConfigKeys.DEFAULT_DATE_FORMAT)
        }

        reason = None
        if hasattr(activity, 'object') and hasattr(activity.object, 'content'):
            reason = activity.object.content
        if reason is not None and len(reason.strip()) > 0:
            kick_activity['object']['content'] = reason

        if activity.target is not None:
            kick_activity['target'] = dict()
            kick_activity['target']['id'] = activity.target.id
            kick_activity['target']['displayName'] = activity.target.display_name

        logger.debug('publishing kick event to external queue: %s' % kick_activity)
        self.env.publish(kick_activity, external=True)

    def handle_remove(self, data: dict, activity: Activity):
        self.env.out_of_scope_emit(
                'gn_room_removed', data, json=True, namespace=activity.target.url, broadcast=True)
