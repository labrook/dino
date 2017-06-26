#!/usr/bin/env python

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

from activitystreams import parse as as_parser

from unittest import TestCase
from uuid import uuid4 as uuid

from dino import environ
from dino.auth.redis import AuthRedis
from dino.config import ConfigKeys
from dino.config import SessionKeys
from dino.config import RedisKeys
from dino.config import ApiTargets
from dino.exceptions import ValidationException
from dino.validation.acl import AclPatternValidator
from dino.validation.acl import AclStrInCsvValidator
from dino.validation.acl import AclRangeValidator
from dino.validation.acl import AclIsAdminValidator
from dino.validation.acl import AclIsSuperUserValidator
from dino.validation.acl import AclDisallowValidator
from dino.validation.acl import AclSameRoomValidator
from dino.validation.acl import AclSameChannelValidator
from dino.validation.acl import AclConfigValidator
from dino.validation.acl import BaseAclValidator

__author__ = 'Oscar Eriksson <oscar.eriks@gmail.com>'


class CustomPatternAclValidatorTest(TestCase):
    CHANNEL_ID = '8765'
    ROOM_ID = '4567'
    USER_ID = '1234'
    USER_NAME = 'Joe'
    AGE = '61'
    GENDER = 'f'
    MEMBERSHIP = 'n'
    IMAGE = 'y'
    HAS_WEBCAM = 'y'
    FAKE_CHECKED = 'n'
    COUNTRY = 'cn'
    CITY = 'Shanghai'
    TOKEN = str(uuid())

    def setUp(self):
        environ.env.session = {
            SessionKeys.user_id.value: CustomPatternAclValidatorTest.USER_ID,
            SessionKeys.user_name.value: CustomPatternAclValidatorTest.USER_NAME,
            SessionKeys.age.value: CustomPatternAclValidatorTest.AGE,
            SessionKeys.gender.value: CustomPatternAclValidatorTest.GENDER,
            SessionKeys.membership.value: CustomPatternAclValidatorTest.MEMBERSHIP,
            SessionKeys.image.value: CustomPatternAclValidatorTest.IMAGE,
            SessionKeys.has_webcam.value: CustomPatternAclValidatorTest.HAS_WEBCAM,
            SessionKeys.fake_checked.value: CustomPatternAclValidatorTest.FAKE_CHECKED,
            SessionKeys.country.value: CustomPatternAclValidatorTest.COUNTRY,
            SessionKeys.city.value: CustomPatternAclValidatorTest.CITY,
            SessionKeys.token.value: CustomPatternAclValidatorTest.TOKEN
        }
        environ.env.config = {
            ConfigKeys.ACL: {
                'room': {
                    'join': {
                    },
                    'message': {
                    }
                },
                'available': {
                },
                'validation': {
                }
            }
        }
        environ.env.config = {
            ConfigKeys.ACL: {
                'room': {
                    'join': {
                        'excludes': [],
                        'acls': [
                            'gender',
                            'age',
                            'country'
                        ]
                    },
                    'message': {
                        'excludes': [],
                        'acls': [
                            'gender',
                            'age'
                        ]
                    }
                },
                'available': {
                    'acls': [
                        'gender',
                        'age',
                        'custom',
                        'membership'
                    ]
                },
                'validation': {
                    'gender': {
                        'type': 'str_in_csv',
                        'value': AclStrInCsvValidator('m,f,ts')
                    },
                    'membership': {
                        'type': 'str_in_csv',
                        'value': AclStrInCsvValidator('n,tg,tg-p')
                    },
                    'custom': {
                        'type': 'accepted_pattern',
                        'value': AclPatternValidator('^[0-9a-z!\|,\(\):=-]*$')
                    },
                    'age': {
                        'type': 'range',
                        'value': AclRangeValidator()
                    }
                }
            }
        }
        self.validator = AclPatternValidator('^[0-9a-z!\|,\(\):=-]*$')

    def test_new_pattern(self):
        self.validator.validate_new_acl('gender=f,(membership=tg-p|membership=tg),(age=34:40|age=21:25)')

    def test_joining_as_gender_female_is_ok(self):
        is_valid, _ = self.validator(self.activity_for_join(), environ.env, 'custom', 'gender=f')
        self.assertTrue(is_valid)

    def test_joining_as_gender_female_and_not_membership_tg_not_ok(self):
        is_valid, _ = self.validator(self.activity_for_join(), environ.env, 'custom', 'gender=f,membership=tg')
        self.assertFalse(is_valid)

    def test_joining_as_gender_female_and_membership_normal_is_ok(self):
        is_valid, _ = self.validator(self.activity_for_join(), environ.env, 'custom', 'gender=f,membership=n')
        self.assertTrue(is_valid)

    def test_joining_as_gender_female_and_not_membership_tg_but_good_age_is_ok(self):
        is_valid, _ = self.validator(self.activity_for_join(), environ.env, 'custom', 'age=60:|gender=f,membership=tg')
        self.assertTrue(is_valid)

    def test_joining_as_gender_female_and_not_membership_tg_also_bad_age_is_not_ok(self):
        is_valid, _ = self.validator(self.activity_for_join(), environ.env, 'custom', 'age=65:|gender=f,membership=tg')
        self.assertFalse(is_valid)

    def test_joining_as_gender_ok_and_membership_ok_but_age_bad_is_ok(self):
        is_valid, _ = self.validator(self.activity_for_join(), environ.env, 'custom', 'age=65:|gender=f,membership=n')
        self.assertTrue(is_valid)

    def test_joining_as_gender_not_ok_and_membership_ok_but_age_bad_is_not_ok(self):
        is_valid, _ = self.validator(self.activity_for_join(), environ.env, 'custom', 'age=65:|gender=m,membership=n')
        self.assertFalse(is_valid)

    def test_joining_as_gender_male_not_ok(self):
        is_valid, _ = self.validator(self.activity_for_join(), environ.env, 'custom', 'gender=m')
        self.assertFalse(is_valid)

    def activity_for_join(self):
        return {
            'actor': {
                'id': '1234'
            },
            'verb': 'join',
            'object': {
                'url': str(uuid())
            },
            'target': {
                'id': str(uuid()),
                'objectType': 'room'
            }
        }