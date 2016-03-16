# Copyright 2016 - Nokia
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
from oslo_log import log as logging

from vitrage.common.exception import VitrageAlgorithmError
from vitrage.graph.filter import check_filter

LOG = logging.getLogger(__name__)

MAPPED_V_ID = 'mapped_v_id'
NEIGHBORS_MAPPED = 'neighbors_mapped'


def subgraph_matching(base_graph, subgraph, matches, validate=False):
    """Find all occurrences of subgraph in the graph

    In the following, a partial mapping is a copy of the sub-graph.
    As we go, vertices of curr_mapping graph will be updated with new
    fields used only for the traversal:

     - MAPPED_V_ID:
       The vertex_id of the corresponding vertex in the graph.
       If it is not empty, than this vertex is already mapped

     - NEIGHBORS_MAPPED:
       True or None. When set True it means all the
       neighbors of this vertex have already been mapped

    Implementation Details:
    ----------------------

    - Init Step:
      copy the sub-graph to create the first candidate mapping graph. In which
      known vertices mappings are added to vertices MAPPED_V_ID. So, we now
      have a sub-graph copy where some of the vertices already have a mapping

    Main loop steps:

    - Steps 1:
      Pop a partially mapped sub-graph from the queue.
      If all its vertices have a MAPPED_V_ID, add it to final mappings

    - Steps 2 & 3:
      Find one template vertex that is not mapped but has a mapped neighbor

    - Step 4: CHECK PROPERTIES
      In the graph find candidate vertices that are linked to that neighbor
      and match the template vertex properties

    - Step 5: CHECK STRUCTURE
      Filter candidate vertices according to edges
    """
    final_subgraphs = []
    initial_sg = _create_initial_subgraph(matches,
                                          base_graph,
                                          subgraph,
                                          validate)
    if not initial_sg:
        LOG.warning('subgraph_matching: Initial sub-graph creation failed')
        LOG.warning('subgraph_matching: Known matches: %s',
                    str(matches))
        return final_subgraphs
    queue = [initial_sg]

    while queue:
        curr_subgraph = queue.pop(0)

        # STEP 1: STOPPING CONDITION
        mapped_vertices = filter(
            lambda v: v.get(MAPPED_V_ID),
            curr_subgraph.get_vertices())
        if len(mapped_vertices) == subgraph.num_vertices():
            final_subgraphs.append(curr_subgraph)
            continue

        # STEP 2: CAN WE THROW THIS SUB-GRAPH?
        vertices_with_unmapped_neighbors = filter(
            lambda v: not v.get(NEIGHBORS_MAPPED),
            mapped_vertices)
        if not vertices_with_unmapped_neighbors:
            continue

        # STEP 3: FIND A SUB-GRAPH VERTEX TO MAP
        v_with_unmapped_neighbors = vertices_with_unmapped_neighbors.pop(0)
        unmapped_neighbors = filter(
            lambda v: not v.get(MAPPED_V_ID),
            curr_subgraph.neighbors(v_with_unmapped_neighbors.vertex_id))
        if not unmapped_neighbors:
            # Mark vertex as NEIGHBORS_MAPPED=True
            v_with_unmapped_neighbors[NEIGHBORS_MAPPED] = True
            curr_subgraph.update_vertex(v_with_unmapped_neighbors)
            queue.append(curr_subgraph)
            continue
        subgraph_vertex_to_map = unmapped_neighbors.pop(0)

        # STEP 4: PROPERTIES CHECK
        graph_candidate_vertices = base_graph.neighbors(
            v_id=v_with_unmapped_neighbors[MAPPED_V_ID],
            vertex_attr_filter=subgraph_vertex_to_map)

        # STEP 5: STRUCTURE CHECK
        edges = _get_edges_to_mapped_vertices(curr_subgraph,
                                              subgraph_vertex_to_map.vertex_id)
        for graph_vertex in graph_candidate_vertices:
            subgraph_vertex_to_map[MAPPED_V_ID] = graph_vertex.vertex_id
            curr_subgraph.update_vertex(subgraph_vertex_to_map)
            if _graph_contains_subgraph_edges(base_graph,
                                              curr_subgraph,
                                              edges):
                queue.append(curr_subgraph.copy())

    # Last thing: Convert results to the expected format!
    result = []
    for mapping in final_subgraphs:
        # TODO(ihefetz) If needed, Here we can easily extract the edge
        # matches from the mapping graph
        a = {v.vertex_id: v[MAPPED_V_ID] for v in mapping.get_vertices()}
        result.append(a)
    return result


def _get_edges_to_mapped_vertices(graph, vertex_id):
    """Get all edges (to/from) vertex where neighbor has a MAPPED_V_ID

    :type graph: driver.Graph
    :type vertex: driver.Vertex
    :rtype: set of driver.Edge
    """
    subgraph_edges_to_mapped_vertices = []
    for e in graph.get_edges(vertex_id):
        t_neighbor = graph.get_vertex(e.other_vertex(vertex_id))
        if not t_neighbor:
            raise VitrageAlgorithmError('Cant get vertex for edge' + str(e))
        if t_neighbor and t_neighbor.get(MAPPED_V_ID):
            subgraph_edges_to_mapped_vertices.append(e)
    return set(subgraph_edges_to_mapped_vertices)


def _graph_contains_subgraph_edges(graph, subgraph, subgraph_edges):
    """Check if graph contains all the expected edges

    For each (sub-graph) expected edge, check if a corresponding edge exists
    in the graph with relevant properties check

    :type graph: driver.Graph
    :type subgraph: driver.Graph
    :type subgraph_edges: set of driver.Edge
    :rtype: bool
    """
    for e in subgraph_edges:
        graph_v_id_source = subgraph.get_vertex(e.source_id).get(MAPPED_V_ID)
        graph_v_id_target = subgraph.get_vertex(e.target_id).get(MAPPED_V_ID)
        if not graph_v_id_source or not graph_v_id_target:
            raise VitrageAlgorithmError('Cant get vertex for edge' + str(e))
        found_graph_edge = graph.get_edge(graph_v_id_source,
                                          graph_v_id_target,
                                          e.label)
        if not found_graph_edge or not check_filter(found_graph_edge, e):
            return False
    return True


def _create_initial_subgraph(known_matches, graph, subgraph, validate=False):
    """Create initial mapping graph from sub graph and known matches

    copy the sub-graph to create the first candidate mapping graph.
    In which known vertices mappings are added to vertices MAPPED_V_ID
    """
    mapping = subgraph.copy()
    for match in known_matches:
        if match.is_vertex:
            if not _update_mapping_for_vertex(match, mapping, graph, validate):
                return None
            subgraph_id = match.subgraph_element.vertex_id
            edges = _get_edges_to_mapped_vertices(mapping, subgraph_id)

        else:  # is edge
            if not _update_mapping_for_edge(match, mapping, graph, validate):
                return None
            edges = _get_related_edges(mapping, match, subgraph, validate)
        if not _graph_contains_subgraph_edges(graph, mapping, edges):
            return None
    return mapping


def _get_related_edges(mapping, match, subgraph, validate):
    sub_target_id = match.subgraph_element.target_id
    sub_source_id = match.subgraph_element.source_id
    edges = _get_edges_to_mapped_vertices(mapping, sub_source_id)
    edges.union(_get_edges_to_mapped_vertices(mapping, sub_target_id))
    if not validate:  # no need to check the mapped edge
        known_edge = subgraph.get_edge(
            sub_source_id,
            sub_target_id,
            match.subgraph_element.label
        )
        edges.remove(known_edge)
    return edges


def _update_mapping(subgraph, graph, subgraph_id, graph_id, validate):
    subgraph_vertex = subgraph.get_vertex(subgraph_id)
    if validate:
        graph_vertex = graph.get_vertex(graph_id)
        if not check_filter(graph_vertex, subgraph_vertex, MAPPED_V_ID):
            return False
    subgraph_vertex[MAPPED_V_ID] = graph_id
    subgraph.update_vertex(subgraph_vertex)
    return True


def _update_mapping_for_vertex(known_match, mapping, graph, validate):
    subgraph_id = known_match.subgraph_element.vertex_id
    graph_id = known_match.graph_element.vertex_id
    return _update_mapping(mapping, graph, subgraph_id, graph_id, validate)


def _update_mapping_for_edge(known_match, mapping, graph, validate):
    s_id = known_match.graph_element.source_id
    sub_s_id = known_match.subgraph_element.source_id
    if not _update_mapping(mapping, graph, sub_s_id, s_id, validate):
        return False

    t_id = known_match.graph_element.target_id
    sub_t_id = known_match.subgraph_element.target_id
    return _update_mapping(mapping, graph, sub_t_id, t_id, validate)