"""
Connection extraction logic for different routing types.
"""
import re
import math
from typing import List, Set, Tuple
from models import Connection, TextElement, WireSpec, ConnectionPoint
from connector_finder import (
    is_connector_id,
    is_splice_point,
    find_connector_above_pin,
    find_nearest_connection_point,
    find_connector_above_pin_prefer_ground,
    find_all_connectors_above_pin
)


class HorizontalWireExtractor:
    """Extracts connections from horizontal wires with specifications."""

    def __init__(self, text_elements: List[TextElement], wire_specs: List[WireSpec]):
        self.text_elements = text_elements
        self.wire_specs = wire_specs
        self.seen_pin_pairs: Set[Tuple] = set()

    def extract_connections(self) -> List[Connection]:
        """
        Extract all horizontal wire connections.

        Uses the wire-centric approach: group connection points by horizontal line,
        then create connections between ALL ADJACENT PAIRS on each line.

        Returns:
            List of Connection objects
        """
        connections = []

        # Group wire specs by horizontal line (same Y coordinate within ±10 units)
        wire_lines = {}
        for wire_spec in self.wire_specs:
            # Round Y to nearest 10 to group wires on same horizontal line
            line_key = round(wire_spec.y / 10) * 10
            if line_key not in wire_lines:
                wire_lines[line_key] = []
            wire_lines[line_key].append(wire_spec)

        # Process each horizontal line
        for line_y, specs_on_line in wire_lines.items():
            # Use the first wire spec for diameter/color (they should all be the same on one line)
            wire_spec = specs_on_line[0]

            # Find all connection points on this horizontal line (±10 Y units)
            # Connection points can be: pins (numeric) OR splice points (SP*)
            connection_points = []
            for elem in self.text_elements:
                if abs(elem.y - wire_spec.y) < 10:
                    if elem.content.isdigit() or is_splice_point(elem.content):
                        connection_points.append(elem)

            if len(connection_points) < 2:
                # Need at least 2 connection points
                continue

            # Sort connection points by X coordinate (left to right)
            connection_points.sort(key=lambda p: p.x)

            # Create connections between ALL ADJACENT pairs of connection points on this line
            # This handles: pin→splice, splice→splice, splice→pin, pin→pin
            for i in range(len(connection_points) - 1):
                left_point = connection_points[i]
                right_point = connection_points[i + 1]

                # Find entities for both connection points
                # Left is source
                left_endpoint = self._find_endpoint(left_point, prefer_as_source=True, source_x=None)
                # Right is destination - pass source X to help with junction selection
                right_endpoint = self._find_endpoint(right_point, prefer_as_source=False, source_x=left_point.x)

                if not left_endpoint or not right_endpoint:
                    continue

                left_id, left_pin = left_endpoint
                right_id, right_pin = right_endpoint

                # Skip self-connections (same connector, different pins on same line)
                if left_id == right_id and left_pin != right_pin and not is_splice_point(left_id):
                    continue

                # Create a unique key for this connection
                connection_key = tuple(sorted([
                    (left_id, left_pin, left_point.x, left_point.y),
                    (right_id, right_pin, right_point.x, right_point.y)
                ]))

                # Skip if we've already created this connection
                if connection_key in self.seen_pin_pairs:
                    continue

                self.seen_pin_pairs.add(connection_key)

                connection = Connection(
                    from_id=left_id,
                    from_pin=left_pin,
                    to_id=right_id,
                    to_pin=right_pin,
                    wire_dm=wire_spec.diameter,
                    wire_color=wire_spec.color
                )
                connections.append(connection)

        return connections

    def _find_endpoint(self, point: TextElement, prefer_as_source: bool, source_x: float = None) -> Tuple[str, str]:
        """
        Find the connector/splice for a connection point.

        Args:
            point: The connection point (pin or splice)
            prefer_as_source: Whether to prefer FL2* for junctions
            source_x: X coordinate of source (for junction selection)

        Returns:
            Tuple of (connector_id, pin)
        """
        # If it's a splice point, return it directly
        if is_splice_point(point.content):
            return (point.content, '')

        # It's a pin - find connector above it
        conn_result = find_connector_above_pin(
            point.x, point.y, self.text_elements,
            prefer_as_source=prefer_as_source,
            source_x=source_x
        )

        if conn_result:
            return (conn_result[0], point.content)

        return None


class VerticalRoutingExtractor:
    """Extracts connections from vertical routing arrows (st17 polylines)."""

    def __init__(self, polylines: List[str], text_elements: List[TextElement]):
        self.polylines = polylines
        self.text_elements = text_elements

    def extract_connections(self) -> List[Connection]:
        """
        Extract all vertical routing connections.

        Returns:
            List of Connection objects
        """
        connections = []

        for points_str in self.polylines:
            # Parse points: "x1,y1 x2,y2 x3,y3 ..."
            point_pairs = points_str.strip().split()
            if len(point_pairs) < 2:
                continue

            # Extract first and last points
            try:
                first_point = point_pairs[0].split(',')
                last_point = point_pairs[-1].split(',')

                start_x, start_y = float(first_point[0]), float(first_point[1])
                end_x, end_y = float(last_point[0]), float(last_point[1])
            except (ValueError, IndexError):
                continue

            # Find nearest connection points to both endpoints
            endpoint1 = find_nearest_connection_point(start_x, start_y, self.text_elements, max_distance=100)
            endpoint2 = find_nearest_connection_point(end_x, end_y, self.text_elements, max_distance=100)

            if not endpoint1 or not endpoint2:
                continue

            ep1_is_splice = is_splice_point(endpoint1.connector_id)
            ep2_is_splice = is_splice_point(endpoint2.connector_id)

            # Check if this is a multi-segment polyline with splice in the middle
            if len(point_pairs) > 2 and not ep1_is_splice and not ep2_is_splice:
                # Check intermediate points for splice points
                splice_found = None
                for i in range(1, len(point_pairs) - 1):  # Skip first and last
                    try:
                        point = point_pairs[i].split(',')
                        px, py = float(point[0]), float(point[1])
                        intermediate = find_nearest_connection_point(px, py, self.text_elements, max_distance=100)
                        if intermediate and is_splice_point(intermediate.connector_id):
                            splice_found = intermediate
                            break
                    except (ValueError, IndexError):
                        continue

                # If we found a splice in the middle, create TWO connections
                if splice_found:
                    # Connection 1: endpoint1 -> splice
                    connections.append(Connection(
                        from_id=endpoint1.connector_id,
                        from_pin=endpoint1.pin,
                        to_id=splice_found.connector_id,
                        to_pin=splice_found.pin,
                        wire_dm='',
                        wire_color=''
                    ))

                    # Connection 2: endpoint2 -> splice
                    connections.append(Connection(
                        from_id=endpoint2.connector_id,
                        from_pin=endpoint2.pin,
                        to_id=splice_found.connector_id,
                        to_pin=splice_found.pin,
                        wire_dm='',
                        wire_color=''
                    ))
                    continue

            # Normal case: determine direction
            # Splice points are ALWAYS destinations
            if ep1_is_splice and not ep2_is_splice:
                source_endpoint = endpoint2
                dest_endpoint = endpoint1
            elif ep2_is_splice and not ep1_is_splice:
                source_endpoint = endpoint1
                dest_endpoint = endpoint2
            else:
                # Neither or both are splices - use Y coordinate
                # Lower Y value = higher up = destination
                if start_y > end_y:
                    source_endpoint = endpoint1
                    dest_endpoint = endpoint2
                else:
                    source_endpoint = endpoint2
                    dest_endpoint = endpoint1

            # Create connection
            connections.append(Connection(
                from_id=source_endpoint.connector_id,
                from_pin=source_endpoint.pin,
                to_id=dest_endpoint.connector_id,
                to_pin=dest_endpoint.pin,
                wire_dm='',
                wire_color=''
            ))

        # Deduplicate connections (same from/to, regardless of order)
        return deduplicate_connections(connections)


class GroundConnectionExtractor:
    """Extracts ground connections from st17 path elements."""

    def __init__(self, paths: List[str], text_elements: List[TextElement]):
        self.paths = paths
        self.text_elements = text_elements

    def extract_connections(self) -> List[Connection]:
        """
        Extract all ground connections.

        Returns:
            List of Connection objects
        """
        connections = []

        for d_attr in self.paths:
            # Parse M command to get arrow location
            m_match = re.match(r'M([\d.]+),([\d.]+)', d_attr)
            if not m_match:
                continue

            path_x, path_y = float(m_match.group(1)), float(m_match.group(2))

            # Find all connection points on the same horizontal line
            # Within ±10 Y units AND ±200 X units of arrow
            connection_points = []

            for elem in self.text_elements:
                is_connection_point = (elem.content.isdigit() or
                                     is_splice_point(elem.content) or
                                     is_connector_id(elem.content))
                if is_connection_point:
                    y_dist = abs(elem.y - path_y)
                    x_dist = abs(elem.x - path_x)

                    # Must be on same horizontal line AND reasonably close
                    # Use 100 unit threshold to avoid picking up distant splice points
                    if y_dist < 10 and x_dist < 120:
                        if elem.content.isdigit():
                            # For pins, find ALL connectors above it
                            connectors_above = find_all_connectors_above_pin(
                                elem.x, elem.y, self.text_elements
                            )

                            if connectors_above:
                                # For ground connections, prefer *2FL pattern
                                to_fl_variants = [c for c in connectors_above if c[1].endswith('2FL')]
                                if to_fl_variants:
                                    chosen_connector = to_fl_variants[0][1]
                                else:
                                    chosen_connector = connectors_above[0][1]

                                connection_points.append((elem.x, chosen_connector, elem.content, elem.y))
                        elif is_splice_point(elem.content) or is_connector_id(elem.content):
                            connection_points.append((elem.x, elem.content, '', elem.y))

            # Filter out duplicate connectors
            unique_connectors = {}
            for x, conn_id, pin, y in connection_points:
                dist_to_path = abs(x - path_x)
                key = (conn_id, pin) if pin else conn_id
                if key not in unique_connectors or dist_to_path < unique_connectors[key][4]:
                    unique_connectors[key] = (x, conn_id, pin, y, dist_to_path)

            # Rebuild connection_points from unique_connectors
            connection_points = [(x, conn_id, pin, y) for x, conn_id, pin, y, _ in unique_connectors.values()]
            connection_points.sort(key=lambda p: p[0])  # Sort by X

            # Find the pair with maximum distance
            # Only consider pairs where one is a GROUND connector
            if len(connection_points) >= 2:
                max_dist = 0
                best_pair = None

                for i in range(len(connection_points)):
                    for j in range(i + 1, len(connection_points)):
                        p1, p2 = connection_points[i], connection_points[j]
                        dist = abs(p2[0] - p1[0])

                        # Check if one is ground (has parentheses)
                        is_ground = (is_connector_id(p1[1]) and '(' in p1[1]) or \
                                   (is_connector_id(p2[1]) and '(' in p2[1])

                        if dist > max_dist and is_ground:
                            max_dist = dist
                            best_pair = (p1, p2)

                if best_pair:
                    left_point, right_point = best_pair
                    connections.append(Connection(
                        from_id=left_point[1],
                        from_pin=left_point[2],
                        to_id=right_point[1],
                        to_pin=right_point[2],
                        wire_dm='',
                        wire_color=''
                    ))

        # Deduplicate connections (same from/to, regardless of order)
        return deduplicate_connections(connections)


def deduplicate_connections(connections: List[Connection]) -> List[Connection]:
    """
    Remove duplicate connections.

    Args:
        connections: List of Connection objects

    Returns:
        List of unique Connection objects
    """
    seen = set()
    unique_connections = []

    for conn in connections:
        key = (conn.from_id, conn.from_pin, conn.to_id, conn.to_pin)
        if key not in seen:
            seen.add(key)
            unique_connections.append(conn)

    return unique_connections
