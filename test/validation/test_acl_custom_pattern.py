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
                        'value': AclStrInCsvValidator('n,tg,tg_p')
                    },
                    'custom': {
                        'type': 'accepted_pattern',
                        'value': AclPatternValidator()
                    },
                    'age': {
                        'type': 'range',
                        'value': AclRangeValidator()
                    }
                }
            }
        }
        self.validator = AclPatternValidator()

    def test_new_pattern(self):
        self.new_acl_ok('gender=f,(membership=tg_p|membership=tg),(age=34:40|age=21:25)')

    def test_pattern_missing_comma(self):
        self.new_acl_bad('gender=f(membership=tg_p|membership=tg),(age=34:40|age=21:25)')

    def test_pattern_missing_comma_2(self):
        self.new_acl_bad('gender=f,(membership=tg_p|membership=tg)(age=34:40|age=21:25)')

    def test_pattern_missing_parenthesis(self):
        self.new_acl_bad('gender=f,membership=tg_p|membership=tg),(age=34:40|age=21:25)')

    def test_pattern_missing_parenthesis_2(self):
        self.new_acl_bad('gender=f,(membership=tg_p|membership=tg,(age=34:40|age=21:25)')

    def test_pattern_missing_pipe(self):
        self.new_acl_bad('gender=f,(membership=tg_pmembership=tg),(age=34:40|age=21:25)')

    def test_pattern_missing_equals(self):
        self.new_acl_bad('gender=f,(membership=tg_p|membership=tg),(age34:40|age=21:25)')

    def test_pattern_nested_parenthesis(self):
        self.new_acl_bad('gender=f,(membership=tg_p|membership=tg,(age34:40|age=21:25))')

    def test_pattern_missing_value(self):
        self.new_acl_bad('gender=')

    def test_pattern_missing_value_and_equals(self):
        self.new_acl_bad('gender')

    def test_pattern_blank(self):
        self.new_acl_bad('')

    def test_joining_as_gender_female_is_ok(self):
        self.true('gender=f')

    def test_joining_as_gender_negated_female_is_not_ok(self):
        self.false('gender=!f')

    def test_joining_as_gender_ok_age_ok(self):
        self.true('gender=f,age=55:65')

    def test_joining_as_gender_ok_negated_age_not_ok(self):
        self.false('gender=f,age=!55:65')

    def test_joining_as_negated_gender_ok_negated_age_ok(self):
        self.true('gender=!m,age=!:35')

    def test_joining_as_negated_gender_ok_negated_age_range_ok(self):
        self.true('gender=!m,age=!25:35')

    def test_joining_as_gender_female_and_not_membership_tg_not_ok(self):
        self.false('gender=f,membership=tg')

    def test_joining_as_gender_female_and_negated_membership_tg_is_ok(self):
        self.true('gender=f,membership=!tg')

    def test_joining_as_gender_female_and_membership_normal_is_ok(self):
        self.true('gender=f,membership=n')

    def test_joining_as_gender_female_and_negated_membership_normal_is_not_ok(self):
        self.false('gender=f,membership=!n')

    def test_joining_as_gender_female_and_not_membership_tg_but_good_age_is_ok(self):
        self.true('age=60:|gender=f,membership=tg')

    def test_joining_as_gender_female_and_not_membership_tg_and_good_negated_age_is_not_ok(self):
        self.false('age=!60:|gender=f,membership=tg')

    def test_joining_as_gender_female_and_not_membership_tg_also_bad_age_is_not_ok(self):
        self.false('age=65:|gender=f,membership=tg')

    def test_joining_as_gender_ok_and_membership_ok_but_age_bad_is_ok(self):
        self.true('age=65:|gender=f,membership=n')

    def test_joining_as_negated_gender_ok_and_membership_ok_but_age_bad_is_not_ok(self):
        self.false('age=65:|gender=!f,membership=n')

    def test_joining_as_gender_not_ok_and_membership_ok_but_age_bad_is_not_ok(self):
        self.false('age=65:|gender=m,membership=n')

    def test_joining_as_gender_not_ok_and_membership_ok_but_negated_age_is(self):
        self.true('age=!65:|gender=m,membership=n')

    def test_joining_as_gender_male_not_ok(self):
        self.false('gender=m')

    def test_joining_as_gender_not_male_ok(self):
        self.true('gender=!m')

    def test_joining_as_gender_not_and_male_above_25_ok(self):
        self.true('gender=!m,age=25:')

    def test_joining_as_gender_male_and_above_25_not_ok(self):
        self.false('gender=m,age=25:')

    def test_joining_as_gender_male_and_below_25_not_ok(self):
        self.false('gender=m,age=:25')

    def test_joining_as_gender_male_or_below_25_not_ok(self):
        self.false('gender=m|age=:25')

    def test_joining_as_gender_male_or_above_25_ok(self):
        self.true('gender=m|age=25:')

    def test_tg_p_w_ok(self):
        pattern = 'gender=!w|gender=w,membership=tg_p'
        environ.env.session[SessionKeys.gender.value] = 'w'
        environ.env.session[SessionKeys.membership.value] = 'tg_p'
        self.true(pattern)

    def test_tg_p_m_ok(self):
        pattern = 'gender=!w|gender=w,membership=tg_p'
        environ.env.session[SessionKeys.gender.value] = 'm'
        environ.env.session[SessionKeys.membership.value] = 'tg_p'
        self.true(pattern)

    def test_tg_non_p_w_not_ok(self):
        pattern = 'gender=!w|gender=w,membership=tg_p'
        environ.env.session[SessionKeys.gender.value] = 'w'
        environ.env.session[SessionKeys.membership.value] = 'tg'
        self.false(pattern)

    def test_tg_non_p_ts_ok(self):
        pattern = 'gender=!w|gender=w,membership=tg_p'
        environ.env.session[SessionKeys.gender.value] = 'ts'
        environ.env.session[SessionKeys.membership.value] = 'tg'
        self.true(pattern)

    def test_tg_multiple(self):
        pattern = 'gender=!w,membership=!tg|gender=w,membership=tg_p'

        environ.env.session[SessionKeys.gender.value] = 'ts'
        environ.env.session[SessionKeys.membership.value] = 'tg'
        self.false(pattern)
        environ.env.session[SessionKeys.gender.value] = 'ts'
        environ.env.session[SessionKeys.membership.value] = 'tg_p'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'ts'
        environ.env.session[SessionKeys.membership.value] = 'normal'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'ts'
        environ.env.session[SessionKeys.membership.value] = 'premium'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'ts'
        environ.env.session[SessionKeys.membership.value] = 'vip'
        self.true(pattern)

        environ.env.session[SessionKeys.gender.value] = 'w'
        environ.env.session[SessionKeys.membership.value] = 'tg_p'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'w'
        environ.env.session[SessionKeys.membership.value] = 'tg'
        self.false(pattern)
        environ.env.session[SessionKeys.gender.value] = 'w'
        environ.env.session[SessionKeys.membership.value] = 'vip'
        self.false(pattern)
        environ.env.session[SessionKeys.gender.value] = 'w'
        environ.env.session[SessionKeys.membership.value] = 'normal'
        self.false(pattern)
        environ.env.session[SessionKeys.gender.value] = 'w'
        environ.env.session[SessionKeys.membership.value] = 'premium'
        self.false(pattern)

        environ.env.session[SessionKeys.gender.value] = 'm'
        environ.env.session[SessionKeys.membership.value] = 'tg'
        self.false(pattern)
        environ.env.session[SessionKeys.gender.value] = 'm'
        environ.env.session[SessionKeys.membership.value] = 'tg_p'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'm'
        environ.env.session[SessionKeys.membership.value] = 'vip'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'm'
        environ.env.session[SessionKeys.membership.value] = 'normal'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'm'
        environ.env.session[SessionKeys.membership.value] = 'premium'
        self.true(pattern)

        environ.env.session[SessionKeys.gender.value] = 'p'
        environ.env.session[SessionKeys.membership.value] = 'tg'
        self.false(pattern)
        environ.env.session[SessionKeys.gender.value] = 'p'
        environ.env.session[SessionKeys.membership.value] = 'tg_p'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'p'
        environ.env.session[SessionKeys.membership.value] = 'vip'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'p'
        environ.env.session[SessionKeys.membership.value] = 'normal'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'p'
        environ.env.session[SessionKeys.membership.value] = 'premium'
        self.true(pattern)

        environ.env.session[SessionKeys.gender.value] = 'tv'
        environ.env.session[SessionKeys.membership.value] = 'tg'
        self.false(pattern)
        environ.env.session[SessionKeys.gender.value] = 'tv'
        environ.env.session[SessionKeys.membership.value] = 'tg_p'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'tv'
        environ.env.session[SessionKeys.membership.value] = 'vip'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'tv'
        environ.env.session[SessionKeys.membership.value] = 'normal'
        self.true(pattern)
        environ.env.session[SessionKeys.gender.value] = 'tv'
        environ.env.session[SessionKeys.membership.value] = 'premium'
        self.true(pattern)

    def false(self, pattern):
        is_valid, _ = self.validator(self.act(), environ.env, 'custom', pattern)
        self.assertFalse(is_valid)

    def true(self, pattern):
        is_valid, _ = self.validator(self.act(), environ.env, 'custom', pattern)
        self.assertTrue(is_valid)

    def new_acl_ok(self, pattern):
        self.validator.validate_new_acl(pattern)

    def new_acl_bad(self, pattern):
        with self.assertRaises(ValidationException):
            self.new_acl_ok('gender=f(membership=tg_p|membership=tg),(age=34:40|age=21:25)')

    def act(self):
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
