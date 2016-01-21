# Copyright 2016 - Alcatel-Lucent
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import datetime

from oslo_log import log as logging

from vitrage.common.constants import EdgeLabels
from vitrage.common.constants import EntityTypes
from vitrage.common.constants import EventAction
from vitrage.common.constants import SyncMode
from vitrage.common.constants import VertexProperties
from vitrage.entity_graph.transformer import base as tbase
from vitrage.entity_graph.transformer.base import TransformerBase
from vitrage.entity_graph.transformer.host_transformer import HostTransformer
from vitrage.entity_graph.transformer.instance_transformer import \
    InstanceTransformer

from vitrage.tests.mocks import mock_syncronizer as mock_sync
from vitrage.tests.unit import base

LOG = logging.getLogger(__name__)


class NovaInstanceTransformerTest(base.BaseTest):

    def setUp(self):
        super(NovaInstanceTransformerTest, self).setUp()

        self.transformers = {}
        host_transformer = HostTransformer(self.transformers)
        self.transformers['nova.host'] = host_transformer

    def test_create_placeholder_vertex(self):
        LOG.debug('Test create placeholder vertex')

        # Tests setup
        instance_id = 'Instance123'
        timestamp = datetime.datetime.utcnow()

        # Test action
        instance_transformer = InstanceTransformer(self.transformers)
        placeholder = instance_transformer.create_placeholder_vertex(
            instance_id,
            timestamp
        )

        # Test assertions
        observed_id_values = placeholder.vertex_id.split(
            TransformerBase.KEY_SEPARATOR)
        expected_id_values = instance_transformer._key_values(
            [instance_id]
        )
        self.assertEqual(observed_id_values, expected_id_values)

        observed_time = placeholder.get(VertexProperties.UPDATE_TIMESTAMP)
        self.assertEqual(observed_time, timestamp)

        observed_type = placeholder.get(VertexProperties.TYPE)
        self.assertEqual(observed_type, InstanceTransformer.INSTANCE_TYPE)

        observed_entity_id = placeholder.get(VertexProperties.ID)
        self.assertEqual(observed_entity_id, instance_id)

        observed_category = placeholder.get(VertexProperties.CATEGORY)
        self.assertEqual(observed_category, EntityTypes.RESOURCE)

        is_placeholder = placeholder.get(VertexProperties.IS_PLACEHOLDER)
        self.assertEqual(is_placeholder, True)

    def test_snapshot_event_transform(self):
        LOG.debug('Test tactual transform action for '
                  'snapshot and snapshot init events')

        # Test setup
        spec_list = mock_sync.simple_instance_generators(
            host_num=1,
            vm_num=1,
            snapshot_events=10,
            update_events=0
        )
        instance_events = mock_sync.generate_random_events_list(spec_list)

        for event in instance_events:
            # Test action
            instance_transformer = InstanceTransformer(self.transformers)
            wrapper = instance_transformer.transform(event)

            # Test assertions
            self._validate_vertex_props(wrapper.vertex, event)

            # Validate the neighbors: only one  valid host neighbor
            self.assertEqual(
                1,
                len(wrapper.neighbors),
                'Instance has only one host neighbor'
            )
            host_neighbor = wrapper.neighbors[0]
            self._validate_host_neighbor(host_neighbor, event)

            sync_mode = event['sync_mode']

            if sync_mode == SyncMode.INIT_SNAPSHOT:
                self.assertEqual(EventAction.CREATE, wrapper.action)
            elif sync_mode == SyncMode.SNAPSHOT:
                self.assertEqual(EventAction.UPDATE, wrapper.action)

    def test_update_event_transform(self):
        LOG.debug('Test tactual transform action for update events')

        # Test setup
        spec_list = mock_sync.simple_instance_generators(
            host_num=1,
            vm_num=1,
            snapshot_events=0,
            update_events=10
        )
        instance_events = mock_sync.generate_random_events_list(spec_list)

        for event in instance_events:
            # Test action
            instance_transformer = InstanceTransformer(self.transformers)
            wrapper = instance_transformer.transform(event)

            # Test assertions
            self._validate_vertex_props(wrapper.vertex, event)

            # Validate the neighbors: only one  valid host neighbor
            self.assertEqual(
                1,
                len(wrapper.neighbors),
                'Instance has only one host neighbor'
            )
            host_neighbor = wrapper.neighbors[0]
            self._validate_host_neighbor(host_neighbor, event)

            event_type = event['event_type']
            if event_type == 'compute.instance.delete.end':
                self.assertEqual(EventAction.DELETE, wrapper.action)
            elif event_type == 'compute.instance.create.start':
                self.assertEqual(EventAction.CREATE, wrapper.action)
            else:
                self.assertEqual(EventAction.UPDATE, wrapper.action)

    def _validate_vertex_props(self, vertex, event):

        self.assertEqual(9, vertex.properties.__len__())

        sync_mode = event['sync_mode']

        extract_value = tbase.extract_field_value
        expected_id = extract_value(
            event,
            InstanceTransformer.INSTANCE_ID[sync_mode]
        )
        observed_id = vertex[VertexProperties.ID]
        self.assertEqual(expected_id, observed_id)

        self.assertEqual(
            EntityTypes.RESOURCE,
            vertex[VertexProperties.CATEGORY]
        )

        self.assertEqual(
            InstanceTransformer.INSTANCE_TYPE,
            vertex[VertexProperties.TYPE]
        )

        expected_project = extract_value(
            event,
            InstanceTransformer.PROJECT_ID[sync_mode]
        )
        observed_project = vertex[VertexProperties.PROJECT_ID]
        self.assertEqual(expected_project, observed_project)

        expected_state = extract_value(
            event,
            InstanceTransformer.INSTANCE_STATE[sync_mode]
        )
        observed_state = vertex[VertexProperties.STATE]
        self.assertEqual(expected_state, observed_state)

        expected_timestamp = extract_value(
            event,
            InstanceTransformer.TIMESTAMP[sync_mode]
        )
        observed_timestamp = vertex[VertexProperties.UPDATE_TIMESTAMP]
        self.assertEqual(expected_timestamp, observed_timestamp)

        expected_name = extract_value(
            event,
            InstanceTransformer.INSTANCE_NAME[sync_mode]
        )
        observed_name = vertex[VertexProperties.NAME]
        self.assertEqual(expected_name, observed_name)

        is_placeholder = vertex[VertexProperties.IS_PLACEHOLDER]
        self.assertFalse(is_placeholder)

        is_deleted = vertex[VertexProperties.IS_DELETED]
        self.assertFalse(is_deleted)

    def _validate_host_neighbor(self, h_neighbor, event):

        it = InstanceTransformer(self.transformers)
        sync_mode = event['sync_mode']

        host_name = tbase.extract_field_value(event, it.HOST_NAME[sync_mode])
        time = tbase.extract_field_value(event, it.TIMESTAMP[sync_mode])

        ht = self.transformers['nova.host']
        expected_neighbor = ht.create_placeholder_vertex(host_name, time)
        self.assertEqual(expected_neighbor, h_neighbor.vertex)

        # Validate neighbor edge
        edge = h_neighbor.edge
        self.assertEqual(edge.source_id, h_neighbor.vertex.vertex_id)
        self.assertEqual(edge.target_id, it.extract_key(event))
        self.assertEqual(edge.label, EdgeLabels.CONTAINS)

    def test_extract_key(self):
        LOG.debug('Test get key from nova instance transformer')

        # Test setup
        spec_list = mock_sync.simple_instance_generators(
            host_num=1,
            vm_num=1,
            snapshot_events=1,
            update_events=0
        )
        instance_events = mock_sync.generate_random_events_list(spec_list)

        instance_transformer = InstanceTransformer(self.transformers)
        for event in instance_events:
            # Test action
            observed_key = instance_transformer.extract_key(event)

            # Test assertions
            observed_key_fields = observed_key.split(
                TransformerBase.KEY_SEPARATOR)

            self.assertEqual(EntityTypes.RESOURCE, observed_key_fields[0])
            self.assertEqual(
                InstanceTransformer.INSTANCE_TYPE,
                observed_key_fields[1]
            )

            instance_id = tbase.extract_field_value(
                event,
                instance_transformer.INSTANCE_ID[event['sync_mode']]
            )

            self.assertEqual(instance_id, observed_key_fields[2])

            key_values = instance_transformer._key_values([instance_id])
            expected_key = tbase.build_key(key_values)

            self.assertEqual(expected_key, observed_key)

    def test_build_instance_key(self):
        LOG.debug('Test build instance key')

        # Test setup
        instance_id = '456'
        expected_key = 'RESOURCE:nova.instance:%s' % instance_id

        instance_transformer = InstanceTransformer(self.transformers)
        # Test action
        key_fields = instance_transformer._key_values([instance_id])

        # Test assertions
        observed_key = tbase.build_key(key_fields)
        self.assertEqual(expected_key, observed_key)

    def test_create_host_neighbor(self):
        LOG.debug('Test create host neighbor')

        # Test setup
        vertex_id = 'RESOURCE:nova.instance:456'
        host_name = 'host123'
        time = datetime.datetime.utcnow()

        # Test action
        neighbor = InstanceTransformer(self.transformers).create_host_neighbor(
            vertex_id,
            host_name,
            time,
            self.transformers['nova.host']
        )

        # Test assertions
        host_vertex_id = 'RESOURCE:nova.host:host123'
        self.assertEqual(host_vertex_id, neighbor.vertex.vertex_id)
        self.assertEqual(
            time,
            neighbor.vertex.get(VertexProperties.UPDATE_TIMESTAMP)
        )

        # test relation edge
        self.assertEqual(host_vertex_id, neighbor.edge.source_id)
        self.assertEqual(vertex_id, neighbor.edge.target_id)
        self.assertEqual(EdgeLabels.CONTAINS, neighbor.edge.label)
