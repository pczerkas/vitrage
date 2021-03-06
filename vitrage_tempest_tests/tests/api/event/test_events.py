# Copyright 2017 Nokia
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import six

from datetime import datetime
from oslo_log import log as logging

from vitrage.common.constants import EntityCategory
from vitrage.common.constants import EventProperties as EventProps
from vitrage.common.constants import VertexProperties as VProps
from vitrage_tempest_tests.tests.api.event.base import BaseTestEvents
from vitrage_tempest_tests.tests.api.event.base import DOWN
from vitrage_tempest_tests.tests.utils import wait_for_answer


LOG = logging.getLogger(__name__)


class TestEvents(BaseTestEvents):
    """Test class for Vitrage event API"""

    def test_send_doctor_event_without_resource_id(self):
        """Sending an event in Doctor format should result in an alarm"""
        self._test_send_doctor_event(
            self._create_doctor_event_details('host123', DOWN))

    def test_send_doctor_event_without_resource_id_v2(self):
        """Sending an event in Doctor format should result in an alarm"""
        self._test_send_doctor_event(
            self._create_doctor_event_details('host457', DOWN))

    def _test_send_doctor_event(self, details):
        try:
            # post an event to the message bus
            event_time = datetime.now()
            event_time_iso = event_time.isoformat()
            event_type = 'compute.host.down'
            self.vitrage_client.event.post(event_time_iso, event_type, details)
            api_alarms = wait_for_answer(2, 0.5, self._check_alarms)

            # expect to get a 'host down alarm', generated by Doctor datasource
            self.assertIsNotNone(api_alarms, 'Expected host down alarm')
            self.assertEqual(1, len(api_alarms), 'Expected host down alarm')

            alarm = api_alarms[0]
            event_time_tz = six.u(event_time.strftime('%Y-%m-%dT%H:%M:%SZ'))
            self._check_alarm(alarm, event_time_tz, event_type, details)

            event_time = datetime.now()
            event_time_iso = event_time.isoformat()
            details['status'] = 'up'
            self.vitrage_client.event.post(event_time_iso, event_type, details)

            api_alarms = wait_for_answer(2, 0.5, self._check_alarms)
            self.assertIsNotNone(api_alarms, 'Expected host down alarm')
            self.assertEqual(0, len(api_alarms), 'Expected host down alarm')

        except Exception as e:
            LOG.exception(e)
            raise
        finally:
            LOG.warning('done')

    def _check_alarm(self, alarm, event_time, event_type, details):
        self.assertEqual(EntityCategory.ALARM, alarm[VProps.VITRAGE_CATEGORY])
        self.assertEqual(event_type, alarm[VProps.NAME])
        self.assertEqual(event_time, alarm[EventProps.TIME])
        self.assertEqual(details['status'], alarm['status'])
        self.assertFalse(alarm[VProps.VITRAGE_IS_DELETED])
        self.assertFalse(alarm[VProps.VITRAGE_IS_PLACEHOLDER])
