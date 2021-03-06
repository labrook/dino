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

from dino import api
from test.base import BaseTest


class ApiMessageTest(BaseTest):
    def test_send_message(self):
        self.create_and_join_room()
        act = self.activity_for_message()
        response_data = api.on_message(act, as_parser(act))
        self.assertEqual(200, response_data[0])
