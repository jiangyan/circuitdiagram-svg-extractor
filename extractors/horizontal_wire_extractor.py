"""
Horizontal wire connection extractor.

Extracts connections from horizontal wires with wire specifications (diameter, color).
Uses the wire-centric approach: group connection points by horizontal line,
then create connections between all adjacent pairs on each line.
"""
from typing import List, Set, Tuple
from models import Connection, TextElement, WireSpec
from connector_finder import (
    is_connector_id,
    is_splice_point,
    find_connector_above_pin
)


class HorizontalWireExtractor:
    """Extracts connections from horizontal wires with specifications."""

    def __init__(self, text_elements: List[TextElement], wire_specs: List[WireSpec], polylines: List[str] = None):
        self.text_elements = text_elements
        self.wire_specs = wire_specs
        self.seen_pin_pairs: Set[Tuple] = set()

        # CRITICAL: Identify splices on vertical polyline segments
        # These should NOT create horizontal wire connections
        self.splices_on_vertical_segments = self._find_splices_on_vertical_segments(text_elements, polylines or [])

    def _find_splices_on_vertical_segments(self, text_elements: List[TextElement], polylines: List[str]) -> Set[str]:
        """Find splice points that are on vertical polyline segments."""
        splices_on_vertical = set()

        # Get all splice positions
        splices = [(e.content, e.x, e.y) for e in text_elements if is_splice_point(e.content)]

        for polyline in polylines:
            points = polyline.split()
            parsed_points = []
            for point in points:
                if ',' in point:
                    parts = point.split(',')
                    if len(parts) == 2:
                        try:
                            px = float(parts[0])
                            py = float(parts[1])
                            parsed_points.append((px, py))
                        except:
                            pass

            # Check each segment
            for i in range(len(parsed_points) - 1):
                x1, y1 = parsed_points[i]
                x2, y2 = parsed_points[i + 1]

                # Check if this is a vertical segment
                if abs(x1 - x2) < 5:  # Vertical segment
                    # Check if any splice is on this segment
                    for sp_id, sp_x, sp_y in splices:
                        if abs(sp_x - x1) < 10 and min(y1, y2) < sp_y < max(y1, y2):
                            splices_on_vertical.add(sp_id)

        return splices_on_vertical

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

        # Process each horizontal line (or group of lines with specs at similar Y)
        for line_y, specs_on_line in wire_lines.items():
            # CRITICAL: Use the wire spec that is CLOSEST in Y to the connection points
            # Wire specs are typically positioned directly above the wires they describe
            # First, find all connection points for this group
            connection_points = []
            for elem in self.text_elements:
                # IMPORTANT: Check if element is within ±10 of ANY spec in the group
                # (not just the first spec, since specs in a group can have different Y positions)
                # Include: pins (digits), splice points, AND ground connectors (with parentheses)
                is_ground_connector = is_connector_id(elem.content) and '(' in elem.content
                if elem.content.isdigit() or is_splice_point(elem.content) or is_ground_connector:
                    for spec in specs_on_line:
                        if abs(elem.y - spec.y) < 10:
                            connection_points.append(elem)
                            break  # Don't add the same element multiple times

            if len(connection_points) < 2:
                # Need at least 2 connection points
                continue

            # CRITICAL: Filter out pins that are too far apart in Y from each other
            # Pins on the same horizontal wire should be within ±15 of EACH OTHER
            # Not just within ±15 of the wire spec (which can group pins from different lines)
            # Increased from 10 to 15 to handle splice points that are vertically offset
            # Example: SP082 at Y=427.71 with pins at Y=440.56 (13 units apart, same wire)
            if connection_points:
                # Find the Y-range of connection points
                y_values = [p.y for p in connection_points]
                y_range = max(y_values) - min(y_values)

                if y_range > 15:
                    # Pins are spread across > 10 Y units - likely from different horizontal lines
                    # Cluster points into groups within ±3 Y units of each other
                    # Process EACH cluster separately (multiple horizontal wires in same spec group)
                    connection_points.sort(key=lambda p: p.y)

                    clusters = []
                    current_cluster = [connection_points[0]]

                    for i in range(1, len(connection_points)):
                        # If this point is within 3 units of the current cluster's range, add it
                        cluster_y_min = min(p.y for p in current_cluster)
                        cluster_y_max = max(p.y for p in current_cluster)

                        if abs(connection_points[i].y - cluster_y_min) <= 3 or abs(connection_points[i].y - cluster_y_max) <= 3:
                            current_cluster.append(connection_points[i])
                        else:
                            # Start new cluster
                            clusters.append(current_cluster)
                            current_cluster = [connection_points[i]]

                    clusters.append(current_cluster)

                    # Process EACH cluster with at least 2 points
                    connection_point_clusters = [c for c in clusters if len(c) >= 2]
                else:
                    # All points are close together - process as one cluster
                    connection_point_clusters = [connection_points]

            else:
                connection_point_clusters = [connection_points]

            # Process each cluster (horizontal line)
            for connection_points in connection_point_clusters:
                if len(connection_points) < 2:
                    # Need at least 2 connection points
                    continue

                # Sort connection points by X coordinate (left to right)
                connection_points.sort(key=lambda p: p.x)

                # CRITICAL: Remove duplicate X positions (pins from different horizontal lines)
                # Keep the pin that is closest in Y to any spec in this group
                unique_x_points = []
                i = 0
                while i < len(connection_points):
                    current_x = connection_points[i].x
                    # Collect all points at this X position (within 0.5 units)
                    points_at_x = [connection_points[i]]
                    j = i + 1
                    while j < len(connection_points) and abs(connection_points[j].x - current_x) < 0.5:
                        points_at_x.append(connection_points[j])
                        j += 1

                    # If multiple points at same X, pick the one closest in Y to any spec
                    if len(points_at_x) > 1:
                        best_point = min(points_at_x, key=lambda p: min(abs(p.y - s.y) for s in specs_on_line))
                        unique_x_points.append(best_point)
                    else:
                        unique_x_points.append(points_at_x[0])

                    i = j

                connection_points = unique_x_points


                # Create connections between ALL ADJACENT pairs of connection points on this line
                # This handles: pin→splice, splice→splice, splice→pin, pin→pin
                for i in range(len(connection_points) - 1):
                    left_point = connection_points[i]
                    right_point = connection_points[i + 1]

                    # CRITICAL: Skip pairs where splice is on vertical segment AND no wire spec nearby
                    # Example: SP_CUSTOM_006 (vertical) → RS856,2 with no spec nearby = wrong
                    # But SP_CUSTOM_004 (vertical) → RS800,32 with spec between = correct
                    # Also allow: SP_CUSTOM_009 → pin 7 where spec is on the left side (part of horizontal bus)
                    between_specs_check = [s for s in specs_on_line if left_point.x < s.x < right_point.x]

                    # MODIFIED: Also check for specs near the left point (within 50 units) to allow horizontal bus continuations
                    nearby_specs_left = [s for s in specs_on_line if abs(s.x - left_point.x) < 50]

                    if not between_specs_check and not nearby_specs_left:  # No spec between OR nearby left
                        if (is_splice_point(left_point.content) and left_point.content in self.splices_on_vertical_segments) or \
                           (is_splice_point(right_point.content) and right_point.content in self.splices_on_vertical_segments):
                            continue

                    # CRITICAL: Select wire spec FOR THIS SPECIFIC PAIR
                    # 1. Find specs BETWEEN the two points (in X)
                    # 2. Of those, pick the one closest in Y to the pair's average Y
                    pair_avg_y = (left_point.y + right_point.y) / 2
                    between_specs = [
                        s for s in specs_on_line
                        if left_point.x < s.x < right_point.x
                    ]

                    if between_specs:
                        # Use spec between the points, closest in Y
                        wire_spec = min(between_specs, key=lambda s: abs(s.y - pair_avg_y))
                    else:
                        # No spec between - use closest in Y to the pair
                        wire_spec = min(specs_on_line, key=lambda s: abs(s.y - pair_avg_y))

                    # CRITICAL: Check if both points are on the same horizontal wire
                    # If one point is far from the wire spec (e.g., 6 units) and the other is very close (e.g., 0.1 units),
                    # they're likely on DIFFERENT horizontal wires at slightly different Y levels
                    # Example: MAIN42 pin 7 (dist=6.16) vs SP_CUSTOM_006 (dist=0.11) - different wires!
                    left_dist = abs(left_point.y - wire_spec.y)
                    right_dist = abs(right_point.y - wire_spec.y)
                    dist_diff = abs(left_dist - right_dist)

                    # If distance difference > 5 units, they're on different wires
                    # This filters: one at ~6 units, one at ~0.1 units (diff=5.9)
                    # But keeps: both at ~5 units (diff=0), or pin at ~5.4 + ground at ~1.1 (diff=4.3)
                    if dist_diff > 5:
                        # Points are at very different Y distances from spec - different wires
                        continue

                    # Find entities for both connection points
                    # Left is source - pass destination X to pick junction closer to destination
                    left_endpoint = self._find_endpoint(left_point, prefer_as_source=True, source_x=None, destination_x=right_point.x)
                    # Right is destination - pass source X to help with junction selection
                    right_endpoint = self._find_endpoint(right_point, prefer_as_source=False, source_x=left_point.x)

                    if not left_endpoint or not right_endpoint:
                        continue

                    left_id, left_pin, left_conn_x, left_conn_y = left_endpoint
                    right_id, right_pin, right_conn_x, right_conn_y = right_endpoint

                    # Skip if pins are too far apart horizontally (>220 units)
                    # UNLESS there's a wire spec between them (which indicates a valid long-distance connection)
                    x_distance = abs(right_point.x - left_point.x)
                    if x_distance > 220:
                        # Check if there's a spec between the pins
                        has_spec_between_pins = any(
                            left_point.x < s.x < right_point.x
                            for s in specs_on_line
                        )
                        if not has_spec_between_pins:
                            # No spec between pins - skip this connection
                            continue

                    # Skip self-connections (same connector, different pins on same line)
                    if left_id == right_id and left_pin != right_pin and not is_splice_point(left_id):
                        continue

                    # CRITICAL: Skip connections that bypass splice points
                    # If there's a splice point BETWEEN left and right, don't create a direct connection
                    # Example: If we have A → SP1 → SP2 on same line, create A→SP1 and SP1→SP2, but NOT A→SP2
                    # This is the "when it arrives SP, done" logic
                    #
                    # Two cases:
                    # 1. pin → pin: skip if splice between
                    # 2. pin → splice: skip if another splice between
                    if not is_splice_point(left_id):
                        # Left is a pin/connector, check if there's a splice between left and right
                        has_splice_between = any(
                            is_splice_point(point.content) and left_point.x < point.x < right_point.x
                            for point in connection_points
                        )
                        if has_splice_between:
                            # There's a splice between - skip this direct connection
                            continue

                    # Skip connections with different connector labels between (module boundary filter)
                    # Only applies to splice connections, allows own connector label
                    if is_splice_point(left_id) or is_splice_point(right_id):
                        # Collect connectors that own the endpoints (don't count these as boundaries)
                        own_connectors = set()
                        if not is_splice_point(left_id):
                            own_connectors.add(left_id)
                        if not is_splice_point(right_id):
                            own_connectors.add(right_id)

                        # Find connector labels between the connection points
                        connectors_between = [
                            elem.content
                            for elem in self.text_elements
                            if is_connector_id(elem.content) and not '(' in elem.content and  # Connector label (not ground)
                               elem.content not in own_connectors and  # Not the pin's own connector
                               left_point.x < elem.x < right_point.x and  # Between in X
                               abs(elem.y - pair_avg_y) < 15  # On same horizontal level (within ±15 units)
                        ]

                        if connectors_between:
                            # Allow passing through junction pair labels (e.g., MH2FL/FL2MH share pins)
                            def is_junction_pair(conn1, conn2):
                                """Check if two connectors are junction pairs (PREFIX1+2+PREFIX2 ↔ PREFIX2+2+PREFIX1)."""
                                if '2' not in conn1 or '2' not in conn2:
                                    return False
                                # Split on '2' and check if they're mirrors
                                parts1 = conn1.split('2', 1)
                                parts2 = conn2.split('2', 1)
                                if len(parts1) == 2 and len(parts2) == 2:
                                    # Check if parts are swapped: (A,B) vs (B,A)
                                    return parts1[0] == parts2[1] and parts1[1] == parts2[0]
                                return False

                            all_are_junction_pairs = all(
                                is_junction_pair(conn, right_id) or is_junction_pair(conn, left_id)
                                for conn in connectors_between
                            )

                            if not all_are_junction_pairs:
                                continue

                    # Skip connections between pins from distant connectors (separate modules)
                    if not is_splice_point(left_id) and not is_splice_point(right_id) and left_id != right_id:
                        # Check if connectors are far apart (>100 units)
                        if left_conn_x and right_conn_x:
                            conn_distance = abs(right_conn_x - left_conn_x)
                            if conn_distance > 100:
                                # Check if there's a wire spec between the connectors
                                # If yes, it's likely a valid inter-module connection
                                has_spec_between_connectors = any(
                                    min(left_conn_x, right_conn_x) < s.x < max(left_conn_x, right_conn_x)
                                    for s in specs_on_line
                                )
                                if not has_spec_between_connectors:
                                    # No wire spec between connectors - skip this connection
                                    continue

                    # Create a unique key for this connection
                    connection_key = tuple(sorted([
                        (left_id, left_pin, left_point.x, left_point.y),
                        (right_id, right_pin, right_point.x, right_point.y)
                    ]))

                    connection = Connection(
                        from_id=left_id,
                        from_pin=left_pin,
                        to_id=right_id,
                        to_pin=right_pin,
                        wire_dm=wire_spec.diameter,
                        wire_color=wire_spec.color
                    )


                    # CRITICAL: If this connection already exists, keep the one with spec BETWEEN the pins
                    if connection_key in self.seen_pin_pairs:
                        # Find the existing connection
                        existing_conn_idx = None
                        for idx, conn in enumerate(connections):
                            if (sorted([(conn.from_id, conn.from_pin, left_point.x, left_point.y),
                                        (conn.to_id, conn.to_pin, right_point.x, right_point.y)]) == list(connection_key)):
                                existing_conn_idx = idx
                                break

                        # If we found the existing connection, check if new one has spec between
                        if existing_conn_idx is not None and len(between_specs) > 0:
                            # New connection has spec between - replace the old one
                            connections[existing_conn_idx] = connection
                        # Otherwise skip (keep the existing connection)
                        continue

                    self.seen_pin_pairs.add(connection_key)
                    connections.append(connection)

        return connections

    def _find_endpoint(self, point: TextElement, prefer_as_source: bool, source_x: float = None, destination_x: float = None):
        """
        Find the connector/splice for a connection point.

        Args:
            point: The connection point (pin, splice, or ground connector)
            prefer_as_source: Whether to prefer FL2* for junctions
            source_x: X coordinate of source (for junction selection when this point is destination)
            destination_x: X coordinate of destination (for picking junction closer to destination)

        Returns:
            Tuple of (connector_id, pin, connector_x, connector_y) or None
            For splices: (splice_id, '', splice_x, splice_y)
            For ground connectors: (ground_id, '', ground_x, ground_y)
        """
        # If it's a splice point, return it directly
        if is_splice_point(point.content):
            return (point.content, '', point.x, point.y)

        # If it's a ground connector, return it directly (ground connector is the endpoint itself)
        if is_connector_id(point.content) and '(' in point.content:
            return (point.content, '', point.x, point.y)

        # It's a pin - find connector above it
        # If destination_x is provided, use it to pick the junction closer to the destination
        conn_result = find_connector_above_pin(
            point.x, point.y, self.text_elements,
            prefer_as_source=prefer_as_source,
            source_x=source_x,
            destination_x=destination_x
        )

        if conn_result:
            # conn_result is (connector_id, x, y)
            return (conn_result[0], point.content, conn_result[1], conn_result[2])

        return None
