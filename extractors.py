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
            # CRITICAL: Use the wire spec that is CLOSEST in Y to the connection points
            # Wire specs are typically positioned directly above the wires they describe
            # First, find all connection points for this group
            connection_points = []
            for elem in self.text_elements:
                # IMPORTANT: Check if element is within ±10 of ANY spec in the group
                # (not just the first spec, since specs in a group can have different Y positions)
                if elem.content.isdigit() or is_splice_point(elem.content):
                    for spec in specs_on_line:
                        if abs(elem.y - spec.y) < 10:
                            connection_points.append(elem)
                            break  # Don't add the same element multiple times

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

                # Find entities for both connection points
                # Left is source
                left_endpoint = self._find_endpoint(left_point, prefer_as_source=True, source_x=None)
                # Right is destination - pass source X to help with junction selection
                right_endpoint = self._find_endpoint(right_point, prefer_as_source=False, source_x=left_point.x)

                if not left_endpoint or not right_endpoint:
                    continue

                left_id, left_pin = left_endpoint
                right_id, right_pin = right_endpoint

                # Skip if pins are too far apart horizontally (>220 units)
                # This prevents false connections between pins on opposite sides of the diagram
                x_distance = abs(right_point.x - left_point.x)
                if x_distance > 220:
                    continue

                # Skip self-connections (same connector, different pins on same line)
                if left_id == right_id and left_pin != right_pin and not is_splice_point(left_id):
                    continue

                # CRITICAL: Skip connections between pins from different, distant connectors
                # This prevents false connections between separate modules on the same line
                if not is_splice_point(left_id) and not is_splice_point(right_id) and left_id != right_id:
                    # Find the connector labels for left and right pins
                    left_conn_x, left_conn_y = None, None
                    right_conn_x, right_conn_y = None, None

                    for elem in self.text_elements:
                        if elem.content == left_id:
                            # Check if this connector is above the left pin (within 50 Y units)
                            if abs(elem.x - left_point.x) < 50 and abs(left_point.y - elem.y) < 50:
                                left_conn_x, left_conn_y = elem.x, elem.y
                        if elem.content == right_id:
                            # Check if this connector is above the right pin (within 50 Y units)
                            if abs(elem.x - right_point.x) < 50 and abs(right_point.y - elem.y) < 50:
                                right_conn_x, right_conn_y = elem.x, elem.y

                    # If both connectors found and they're far apart (>100 units), skip
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
    """Extracts connections from vertical routing arrows (st17 polylines) and st1 path routing wires."""

    def __init__(self, polylines: List[str], st1_paths: List[str], text_elements: List[TextElement], wire_specs: List = None, horizontal_connections: List = None):
        self.polylines = polylines
        self.st1_paths = st1_paths
        self.text_elements = text_elements
        self.wire_specs = wire_specs or []
        self.horizontal_connections = horizontal_connections or []

        # Build a set of (connector_id, pin) tuples that already have horizontal wire connections
        # Only track PINS (not splice points), as splice points can have multiple connections
        self.pins_with_horizontal_wires = set()
        for conn in self.horizontal_connections:
            # Only add if it's a real pin (has a pin number), not a splice point
            if conn.from_pin and not is_splice_point(conn.from_id):
                self.pins_with_horizontal_wires.add((conn.from_id, conn.from_pin))

        # Also track splice points that have horizontal connections on BOTH sides
        # These are "pass-through" splices that shouldn't have additional routing
        splice_incoming = {}  # splice_id -> count of incoming horizontal wires
        splice_outgoing = {}  # splice_id -> count of outgoing horizontal wires

        for conn in self.horizontal_connections:
            if is_splice_point(conn.from_id):
                splice_outgoing[conn.from_id] = splice_outgoing.get(conn.from_id, 0) + 1
            if is_splice_point(conn.to_id):
                splice_incoming[conn.to_id] = splice_incoming.get(conn.to_id, 0) + 1

        # Track splice points with connections on both sides (bidirectional pass-through)
        self.passthrough_splices = set()
        for splice_id in set(splice_incoming.keys()) | set(splice_outgoing.keys()):
            if splice_incoming.get(splice_id, 0) >= 1 and splice_outgoing.get(splice_id, 0) >= 1:
                self.passthrough_splices.add(splice_id)

    def _find_wire_spec_near_path(self, path_points: List[Tuple[float, float]], source_point: Tuple[float, float] = None) -> Tuple[str, str]:
        """
        Find the wire spec closest to a routing path.

        CRITICAL: Wire specs are positioned above the INITIAL horizontal segment of the wire,
        near where the wire originates (source). NOT scattered along the entire path!

        For L-shaped or complex paths, we find the horizontal segment closest to the SOURCE endpoint.

        Args:
            path_points: List of (x, y) coordinates along the routing path
            source_point: (x, y) coordinates of the source endpoint (where wire originates)

        Returns:
            Tuple of (diameter, color) or ('', '') if no spec found
        """
        if not self.wire_specs or len(path_points) < 2:
            return ('', '')

        # Find ALL horizontal segments of the path
        horizontal_segments = []
        for i in range(len(path_points) - 1):
            x1, y1 = path_points[i]
            x2, y2 = path_points[i + 1]

            # Check if this segment is horizontal (Y change < 5 units)
            if abs(y2 - y1) < 5:
                horizontal_segments.append((i, x1, y1, x2, y2))

        # If we know the source point, find the horizontal segment closest to it
        target_segment_points = []
        if source_point and horizontal_segments:
            source_x, source_y = source_point
            min_dist_to_source = float('inf')
            closest_segment = None

            for idx, x1, y1, x2, y2 in horizontal_segments:
                # Distance from source to segment midpoint
                mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
                dist = math.sqrt((mid_x - source_x)**2 + (mid_y - source_y)**2)
                if dist < min_dist_to_source:
                    min_dist_to_source = dist
                    closest_segment = (x1, y1, x2, y2)

            if closest_segment:
                target_segment_points = [(closest_segment[0], closest_segment[1]),
                                        (closest_segment[2], closest_segment[3])]

        # Fallback: use first horizontal segment if no source point provided
        if not target_segment_points and horizontal_segments:
            idx, x1, y1, x2, y2 = horizontal_segments[0]
            target_segment_points = [(x1, y1), (x2, y2)]

        # Fallback: use first few points if no horizontal segments found
        if not target_segment_points:
            target_segment_points = path_points[:min(3, len(path_points))]

        # Find the wire spec closest to the target segment
        # CRITICAL: Only consider specs BETWEEN the segment's X endpoints
        if len(target_segment_points) >= 2:
            seg_x_min = min(p[0] for p in target_segment_points)
            seg_x_max = max(p[0] for p in target_segment_points)
        else:
            seg_x_min, seg_x_max = None, None

        min_distance = float('inf')
        closest_spec = None

        for spec in self.wire_specs:
            # Filter: spec must be STRICTLY between segment's X endpoints
            # (specs are positioned above the wire, not at the ends)
            if seg_x_min is not None and seg_x_max is not None:
                if not (seg_x_min < spec.x < seg_x_max):
                    continue

            # Check distance from spec to each point in the target segment
            for px, py in target_segment_points:
                x_dist = abs(spec.x - px)
                y_dist = spec.y - py  # Negative if spec is above (lower Y)

                # Only consider specs that are ABOVE the path (within 50 Y units above)
                if -50 < y_dist < 0:  # Must be above (spec.y < path.y)
                    # Euclidean distance, strongly prioritize specs directly above (close in Y)
                    # Weight Y-distance MORE to prefer specs just above the wire
                    distance = math.sqrt(x_dist**2 + (y_dist * 2.0)**2)  # Weight Y more

                    if distance < min_distance:
                        min_distance = distance
                        closest_spec = spec

        if closest_spec and min_distance < 150:  # Within 150 units
            return (closest_spec.diameter, closest_spec.color)

        return ('', '')

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

            # Parse all points for wire spec detection
            path_points = []
            for point_str in point_pairs:
                try:
                    x, y = map(float, point_str.split(','))
                    path_points.append((x, y))
                except (ValueError, IndexError):
                    continue

            # Find nearest connection points to both endpoints
            endpoint1 = find_nearest_connection_point(start_x, start_y, self.text_elements, max_distance=100)
            endpoint2 = find_nearest_connection_point(end_x, end_y, self.text_elements, max_distance=100)

            if not endpoint1 or not endpoint2:
                continue

            # Skip if either endpoint is a ground connector (handled by ground extractor)
            ep1_is_ground = is_connector_id(endpoint1.connector_id) and '(' in endpoint1.connector_id
            ep2_is_ground = is_connector_id(endpoint2.connector_id) and '(' in endpoint2.connector_id

            if ep1_is_ground or ep2_is_ground:
                continue

            ep1_is_splice = is_splice_point(endpoint1.connector_id)
            ep2_is_splice = is_splice_point(endpoint2.connector_id)

            # Check if this is a multi-segment polyline with splice in the middle
            # Allow checking even if one endpoint is a splice (e.g., pin -> splice1 -> splice2)
            if len(point_pairs) > 2:
                # Strategy: Check for splices ON line segments (not just near vertices)
                # This prevents false matches to distant splices
                splice_found = None

                # Parse all points first
                parsed_points = []
                for point_str in point_pairs:
                    try:
                        x, y = map(float, point_str.split(','))
                        parsed_points.append((x, y))
                    except (ValueError, IndexError):
                        continue

                # Check each line segment for splice points
                for i in range(len(parsed_points) - 1):
                    x1, y1 = parsed_points[i]
                    x2, y2 = parsed_points[i + 1]

                    # Check all splice points to see if any are ON this segment
                    for elem in self.text_elements:
                        if not is_splice_point(elem.content):
                            continue

                        sx, sy = elem.x, elem.y

                        # Check if splice is on this line segment
                        # For horizontal segments: Y within 10 units, X between endpoints
                        # For vertical segments: X within 10 units, Y between endpoints
                        is_on_segment = False

                        if abs(y1 - y2) < 5:  # Horizontal segment
                            if abs(sy - y1) < 10 and min(x1, x2) < sx < max(x1, x2):
                                is_on_segment = True
                        elif abs(x1 - x2) < 5:  # Vertical segment
                            if abs(sx - x1) < 10 and min(y1, y2) < sy < max(y1, y2):
                                is_on_segment = True

                        if is_on_segment:
                            splice_found = find_nearest_connection_point(sx, sy, self.text_elements, max_distance=20)
                            if splice_found and is_splice_point(splice_found.connector_id):
                                break

                    if splice_found:
                        break

                # If no splice found on segments, check vertices (for T-junctions)
                # But use strict distance threshold to avoid false matches
                if not splice_found:
                    for i in range(1, len(parsed_points) - 1):  # Skip first and last
                        px, py = parsed_points[i]
                        intermediate = find_nearest_connection_point(px, py, self.text_elements, max_distance=100)
                        if intermediate and is_splice_point(intermediate.connector_id):
                            splice_found = intermediate
                            break

                # If we found a splice in the middle, create connections
                # For a chain (ep1 -> splice -> ep2), we need:
                #   ep1 -> splice and splice -> ep2
                if splice_found:
                    # For multi-segment paths, source is endpoint1 (first point)
                    wire_dm, wire_color = self._find_wire_spec_near_path(path_points, (start_x, start_y))

                    # Connection 1: endpoint1 -> splice (skip if self-loop or has horizontal wire)
                    ep1_key = (endpoint1.connector_id, endpoint1.pin)
                    if not (endpoint1.connector_id == splice_found.connector_id and
                            endpoint1.pin == splice_found.pin) and \
                       ep1_key not in self.pins_with_horizontal_wires:
                        # Skip if both endpoints are pass-through splices
                        if not (endpoint1.connector_id in self.passthrough_splices and
                                splice_found.connector_id in self.passthrough_splices):
                            connections.append(Connection(
                                from_id=endpoint1.connector_id,
                                from_pin=endpoint1.pin,
                                to_id=splice_found.connector_id,
                                to_pin=splice_found.pin,
                                wire_dm=wire_dm,
                                wire_color=wire_color
                            ))

                    # Connection 2: splice -> endpoint2 (skip if self-loop)
                    # This creates a chain: endpoint1 -> splice -> endpoint2
                    if not (endpoint2.connector_id == splice_found.connector_id and
                            endpoint2.pin == splice_found.pin):
                        # Skip if both endpoints are pass-through splices
                        if not (splice_found.connector_id in self.passthrough_splices and
                                endpoint2.connector_id in self.passthrough_splices):
                            connections.append(Connection(
                                from_id=splice_found.connector_id,
                                from_pin=splice_found.pin,
                                to_id=endpoint2.connector_id,
                                to_pin=endpoint2.pin,
                                wire_dm=wire_dm,
                                wire_color=wire_color
                            ))
                    continue

            # Normal case: determine direction
            # Splice points are ALWAYS destinations
            if ep1_is_splice and not ep2_is_splice:
                source_endpoint = endpoint2
                dest_endpoint = endpoint1
                source_point = (end_x, end_y)
            elif ep2_is_splice and not ep1_is_splice:
                source_endpoint = endpoint1
                dest_endpoint = endpoint2
                source_point = (start_x, start_y)
            else:
                # Neither or both are splices - use Y coordinate
                # Lower Y value = higher up = destination
                if start_y > end_y:
                    source_endpoint = endpoint1
                    dest_endpoint = endpoint2
                    source_point = (start_x, start_y)
                else:
                    source_endpoint = endpoint2
                    dest_endpoint = endpoint1
                    source_point = (end_x, end_y)

            # Now find wire spec near this routing path, using the SOURCE point
            wire_dm, wire_color = self._find_wire_spec_near_path(path_points, source_point)

            # Skip self-loops (short polylines where both endpoints resolve to same pin)
            if (source_endpoint.connector_id == dest_endpoint.connector_id and
                source_endpoint.pin == dest_endpoint.pin):
                continue

            # Skip if source pin already has a horizontal wire connection
            # (Horizontal wires take precedence over routing paths)
            source_key = (source_endpoint.connector_id, source_endpoint.pin)
            if source_key in self.pins_with_horizontal_wires:
                continue

            # Skip routing connections between two pass-through splice points
            # (Avoids false connections like SP184 → SP113 where both have horizontal wires)
            # But allow connections from pass-through splices to pins (e.g., SP025 → FL7611,9)
            if (source_endpoint.connector_id in self.passthrough_splices and
                dest_endpoint.connector_id in self.passthrough_splices):
                continue

            # Create connection
            connections.append(Connection(
                from_id=source_endpoint.connector_id,
                from_pin=source_endpoint.pin,
                to_id=dest_endpoint.connector_id,
                to_pin=dest_endpoint.pin,
                wire_dm=wire_dm,
                wire_color=wire_color
            ))

        # Process st1 path elements (white routing wires)
        from svg_parser import extract_path_all_points

        for d_attr in self.st1_paths:
            # Extract ALL points along the path (not just endpoints)
            path_points = extract_path_all_points(d_attr)
            if len(path_points) < 2:
                continue

            # Find connection points along the entire path
            # For each segment, check for connection points near the line
            connection_points_on_path = []

            for i in range(len(path_points)):
                px, py = path_points[i]

                # Check for connection points AT this path point
                cp = find_nearest_connection_point(px, py, self.text_elements, max_distance=100)
                if cp:
                    # Skip ground connectors (handled by ground extractor)
                    if is_connector_id(cp.connector_id) and '(' in cp.connector_id:
                        continue

                    # Add if not already added (avoid duplicates)
                    if not any(existing.connector_id == cp.connector_id and existing.pin == cp.pin
                              for existing in connection_points_on_path):
                        connection_points_on_path.append(cp)

                # If not the last point, check for connection points BETWEEN this point and next
                if i < len(path_points) - 1:
                    next_px, next_py = path_points[i + 1]

                    # Check all text elements to see if any are on/near this line segment
                    for elem in self.text_elements:
                        # Check if element is a connection point (pin or splice)
                        if not (elem.content.isdigit() or is_splice_point(elem.content)):
                            continue

                        # Check if point is near the line segment
                        ex, ey = elem.x, elem.y

                        # For horizontal or vertical segments, use simple distance check
                        is_horizontal = abs(py - next_py) < 5
                        is_vertical = abs(px - next_px) < 5

                        if is_horizontal:
                            # Horizontal segment: check if Y is close and X is between endpoints
                            if abs(ey - py) < 15:  # Within 15 units vertically
                                min_x, max_x = min(px, next_px), max(px, next_px)
                                if min_x - 5 < ex < max_x + 5:  # Between endpoints horizontally
                                    # This element is on the line segment
                                    cp = find_nearest_connection_point(ex, ey, self.text_elements, max_distance=20)
                                    if cp:
                                        if is_connector_id(cp.connector_id) and '(' in cp.connector_id:
                                            continue
                                        if not any(existing.connector_id == cp.connector_id and existing.pin == cp.pin
                                                  for existing in connection_points_on_path):
                                            connection_points_on_path.append(cp)
                        elif is_vertical:
                            # Vertical segment: check if X is close and Y is between endpoints
                            if abs(ex - px) < 15:  # Within 15 units horizontally
                                min_y, max_y = min(py, next_py), max(py, next_py)
                                if min_y - 5 < ey < max_y + 5:  # Between endpoints vertically
                                    cp = find_nearest_connection_point(ex, ey, self.text_elements, max_distance=20)
                                    if cp:
                                        if is_connector_id(cp.connector_id) and '(' in cp.connector_id:
                                            continue
                                        if not any(existing.connector_id == cp.connector_id and existing.pin == cp.pin
                                                  for existing in connection_points_on_path):
                                            connection_points_on_path.append(cp)

            # Need at least 2 connection points to form connections
            if len(connection_points_on_path) < 2:
                continue

            # Sort connection points by their position along the path
            # For now, sort by X coordinate (works for horizontal paths) or Y coordinate (for vertical)
            # Determine path orientation based on first segment
            if len(path_points) >= 2:
                first_segment_horizontal = abs(path_points[0][1] - path_points[1][1]) < abs(path_points[0][0] - path_points[1][0])
                if first_segment_horizontal:
                    # Sort by X coordinate
                    connection_points_on_path.sort(key=lambda cp: cp.x)
                else:
                    # Sort by Y coordinate
                    connection_points_on_path.sort(key=lambda cp: cp.y)

            # Find wire spec near this path, using first connection point as source
            first_cp = connection_points_on_path[0]
            wire_dm, wire_color = self._find_wire_spec_near_path(path_points, (first_cp.x, first_cp.y))

            # Create connections between ALL ADJACENT PAIRS along the path
            # This is similar to how we handle horizontal wires
            for i in range(len(connection_points_on_path) - 1):
                cp1 = connection_points_on_path[i]
                cp2 = connection_points_on_path[i + 1]

                # Skip self-loops
                if cp1.connector_id == cp2.connector_id and cp1.pin == cp2.pin:
                    continue

                # Determine direction based on splice points
                cp1_is_splice = is_splice_point(cp1.connector_id)
                cp2_is_splice = is_splice_point(cp2.connector_id)

                # Check if cp1 or cp2 is at an endpoint (first or last in list)
                cp1_at_endpoint = (i == 0)
                cp2_at_endpoint = (i + 1 == len(connection_points_on_path) - 1)

                if cp1_is_splice and not cp2_is_splice:
                    # Splice at position cp1
                    if cp1_at_endpoint:
                        # cp1 is a splice at an endpoint → it's a destination
                        source, dest = cp2, cp1
                    else:
                        # cp1 is a splice in the middle → use path order
                        source, dest = cp1, cp2
                elif cp2_is_splice and not cp1_is_splice:
                    # Splice at position cp2
                    if cp2_at_endpoint:
                        # cp2 is a splice at an endpoint → it's a destination
                        source, dest = cp1, cp2
                    else:
                        # cp2 is a splice in the middle → use path order
                        source, dest = cp1, cp2
                else:
                    # Both splices, both non-splices, or other cases → use path order
                    source, dest = cp1, cp2

                # Create connection
                connections.append(Connection(
                    from_id=source.connector_id,
                    from_pin=source.pin,
                    to_id=dest.connector_id,
                    to_pin=dest.pin,
                    wire_dm=wire_dm,
                    wire_color=wire_color
                ))

        # Deduplicate connections (same from/to, regardless of order)
        return deduplicate_connections(connections)


class GroundConnectionExtractor:
    """Extracts ground connections from st17 path elements."""

    def __init__(self, paths: List[str], text_elements: List[TextElement], wire_specs: List = None, horizontal_connections: List[Connection] = None):
        self.paths = paths
        self.text_elements = text_elements
        self.wire_specs = wire_specs or []
        self.horizontal_connections = horizontal_connections or []

        # Build set of (connector_id, pin) tuples that already have horizontal connections
        self.pins_with_horizontal_wires = set()
        for conn in self.horizontal_connections:
            if conn.wire_dm:  # Has wire specs
                self.pins_with_horizontal_wires.add((conn.from_id, conn.from_pin))
                if conn.to_pin:  # If destination also has a pin
                    self.pins_with_horizontal_wires.add((conn.to_id, conn.to_pin))

    def _find_wire_spec_for_ground(self, pin_x: float, pin_y: float, arrow_x: float, arrow_y: float) -> Tuple[str, str]:
        """
        Find wire spec for a ground connection.

        Ground wires are typically horizontal from pin to ground arrow.
        Spec should be above this horizontal line, between the pin and arrow.

        Args:
            pin_x, pin_y: Pin coordinates
            arrow_x, arrow_y: Arrow/ground coordinates

        Returns:
            Tuple of (diameter, color) or ('', '') if no spec found
        """
        if not self.wire_specs:
            return ('', '')

        # X range between pin and arrow
        x_min = min(pin_x, arrow_x)
        x_max = max(pin_x, arrow_x)

        # Y position is typically at the arrow level
        target_y = arrow_y

        min_distance = float('inf')
        closest_spec = None

        for spec in self.wire_specs:
            # Spec must be between pin and arrow in X
            if not (x_min < spec.x < x_max):
                continue

            # Spec must be above the wire (lower Y value)
            y_dist = spec.y - target_y  # Negative if above

            if -50 < y_dist < 0:  # Within 50 units above
                # Calculate distance with Y-weighting
                x_dist = abs(spec.x - pin_x)  # Distance from pin
                distance = math.sqrt(x_dist**2 + (y_dist * 2.0)**2)

                if distance < min_distance:
                    min_distance = distance
                    closest_spec = spec

        if closest_spec and min_distance < 150:
            return (closest_spec.diameter, closest_spec.color)

        return ('', '')

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

            # Find all ground connectors within reasonable distance of this arrow
            # Ground connectors can be vertically offset (between multiple arrows)
            nearby_ground_connectors = []
            for elem in self.text_elements:
                if is_connector_id(elem.content) and '(' in elem.content:
                    y_dist = abs(elem.y - path_y)
                    x_dist = abs(elem.x - path_x)

                    # Use 20-unit Y threshold and 210-unit X threshold
                    if y_dist < 20 and x_dist < 210:
                        nearby_ground_connectors.append((elem.x, elem.y, elem.content))

            if not nearby_ground_connectors:
                continue

            # For each nearby ground connector, process it
            for gx, gy, ground_id in nearby_ground_connectors:
                # Find pins near the arrow
                pins_with_connectors = []

                for elem in self.text_elements:
                    if elem.content.isdigit():
                        y_dist = abs(elem.y - path_y)
                        x_dist = abs(elem.x - path_x)

                        # Pins must be within ±10 Y units of arrow
                        if y_dist < 10 and x_dist < 210:
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

                                pins_with_connectors.append((elem.x, chosen_connector, elem.content, elem.y))

                if not pins_with_connectors:
                    continue

                # Find all pins near the arrow (within 10 units)
                candidate_pins = [p for p in pins_with_connectors if abs(p[0] - path_x) < 10]

                if not candidate_pins:
                    continue

                # For each candidate pin, find the connector label position
                pins_with_label_positions = []
                for px, pin_conn, pin_num, py in candidate_pins:
                    # Find the connector label in text_elements
                    connector_label = next((elem for elem in self.text_elements
                                          if elem.content == pin_conn and is_connector_id(elem.content)), None)
                    if connector_label:
                        # Calculate distance from connector label to ground connector label
                        label_distance = abs(connector_label.x - gx)
                        pins_with_label_positions.append((px, pin_conn, pin_num, py, label_distance))

                if not pins_with_label_positions:
                    # No connector labels found, fall back to closest pin to arrow
                    closest_pin = min(candidate_pins, key=lambda p: abs(p[0] - path_x))
                    px, pin_conn, pin_num, py = closest_pin

                    if not is_splice_point(pin_conn):
                        # Find wire spec for this ground connection
                        # Use ground connector position (gx, gy) not arrow position
                        wire_dm, wire_color = self._find_wire_spec_for_ground(px, py, gx, gy)

                        connections.append(Connection(
                            from_id=pin_conn,
                            from_pin=pin_num,
                            to_id=ground_id,
                            to_pin='',
                            wire_dm=wire_dm,
                            wire_color=wire_color
                        ))
                    continue

                # Pick the pin whose connector label is CLOSEST to the ground connector
                closest_pin_by_label = min(pins_with_label_positions, key=lambda p: p[4])
                px, pin_conn, pin_num, py, label_dist = closest_pin_by_label

                # Skip if this pin already has a horizontal wire connection
                if (pin_conn, pin_num) in self.pins_with_horizontal_wires:
                    continue

                # Only create connection if the connector label is reasonably close to ground
                # when there are multiple candidates (prevents false positives)
                unique_connectors = set(p[1] for p in pins_with_label_positions)

                # Find wire spec for this ground connection
                # Use ground connector position (gx, gy) not arrow position
                wire_dm, wire_color = self._find_wire_spec_for_ground(px, py, gx, gy)

                if len(unique_connectors) == 1:
                    # Only one connector candidate - always accept
                    connections.append(Connection(
                        from_id=pin_conn,
                        from_pin=pin_num,
                        to_id=ground_id,
                        to_pin='',
                        wire_dm=wire_dm,
                        wire_color=wire_color
                    ))
                elif label_dist < 150:
                    # Multiple connectors - only accept if closest is within 150 units
                    connections.append(Connection(
                        from_id=pin_conn,
                        from_pin=pin_num,
                        to_id=ground_id,
                        to_pin='',
                        wire_dm=wire_dm,
                        wire_color=wire_color
                    ))

        # Deduplicate connections (same from/to, regardless of order)
        return deduplicate_connections(connections)


def deduplicate_connections(connections: List[Connection]) -> List[Connection]:
    """
    Remove duplicate connections.

    When duplicates exist (same from/to), prefer the one WITH wire specs.
    This happens when both horizontal wire and routing extractors find the same connection.

    Args:
        connections: List of Connection objects

    Returns:
        List of unique Connection objects
    """
    seen = {}  # key -> Connection

    for conn in connections:
        key = (conn.from_id, conn.from_pin, conn.to_id, conn.to_pin)

        if key not in seen:
            # First time seeing this connection
            seen[key] = conn
        else:
            # Duplicate found - prefer connection WITH wire specs
            existing = seen[key]
            # If new connection has wire spec and existing doesn't, replace
            if conn.wire_dm and not existing.wire_dm:
                seen[key] = conn
            # If existing has wire spec, keep it (don't replace)

    return list(seen.values())
