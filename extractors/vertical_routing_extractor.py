"""
Vertical routing connection extractor.

Extracts connections from vertical routing arrows (st17 polylines) and st1 path routing wires.
Handles multi-segment polylines with intermediate splices and tracks pass-through splices.
"""
import math
from typing import List, Tuple
from models import Connection, TextElement, WireSpec, ConnectionPoint
from connector_finder import (
    is_connector_id,
    is_splice_point,
    find_connector_above_pin,
    find_all_connectors_above_pin,
    find_nearest_connection_point
)
from .base_extractor import BaseExtractor, deduplicate_connections


class VerticalRoutingExtractor(BaseExtractor):
    """Extracts connections from vertical routing arrows (st17 polylines) and st1 path routing wires."""

    def __init__(self, polylines: List[str], st1_paths: List[str], text_elements: List[TextElement], wire_specs: List[WireSpec] = None, horizontal_connections: List[Connection] = None):
        # Initialize base class
        super().__init__(text_elements, wire_specs or [])

        self.polylines = polylines
        self.st1_paths = st1_paths

        # Calculate component bounds once (for filtering external routing wires)
        # Only include: pins (pure digits), connector IDs, splice points
        # Exclude: descriptive labels like "2Row RH Seat Memory Button Backlight"
        def is_component_element(content: str) -> bool:
            return (content.isdigit() or  # Pins
                   is_connector_id(content) or  # Connector IDs
                   is_splice_point(content))  # Splice points (SP001, SP_CUSTOM_001)

        component_xs = [e.x for e in text_elements if is_component_element(e.content)]
        component_ys = [e.y for e in text_elements if is_component_element(e.content)]

        if component_xs and component_ys:
            # Add 20-unit margin for boundary tolerance
            self.min_x = min(component_xs) - 20
            self.max_x = max(component_xs) + 20
            self.min_y = min(component_ys) - 20
            self.max_y = max(component_ys) + 20
        else:
            # No bounds - allow all polylines
            self.min_x = self.min_y = float('-inf')
            self.max_x = self.max_y = float('inf')

        self.horizontal_connections = horizontal_connections or []

        # Build a set of (connector_id, pin) tuples that already have horizontal wire connections
        # Only track PINS (not splice points), as splice points can have multiple connections
        self.pins_with_horizontal_wires = set()
        for conn in self.horizontal_connections:
            # Add BOTH FROM and TO pins (only if they're real pins, not splice points)
            if conn.from_pin and not is_splice_point(conn.from_id):
                self.pins_with_horizontal_wires.add((conn.from_id, conn.from_pin))
            if conn.to_pin and not is_splice_point(conn.to_id):
                self.pins_with_horizontal_wires.add((conn.to_id, conn.to_pin))

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

            # CRITICAL: Filter out bus/external routing wires that go outside diagram bounds
            # These polylines route around the perimeter where no components exist
            # Example: st27 polyline goes to X=43.8, but leftmost component is at X=62.1
            # Root cause: External/bus routing wires, not actual component-to-component connections
            #
            # IMPORTANT: Only check ENDPOINTS, not intermediate routing points
            # Intermediate points can legitimately go outside to route around components
            # Only filter if BOTH endpoints are outside bounds (true external routing)
            start_outside = (start_x < self.min_x or start_x > self.max_x or
                           start_y < self.min_y or start_y > self.max_y)
            end_outside = (end_x < self.min_x or end_x > self.max_x or
                         end_y < self.min_y or end_y > self.max_y)

            if start_outside and end_outside:
                # Both endpoints outside - this is external bus routing
                continue

            # CRITICAL: For rectangular routing polylines (4 points), find connection points at ALL corners
            # These represent rectangular wire paths (e.g., SR02 → SR03, UH07 → UH08)
            # Structure: point1 → point2 → point3 → point4 (3 sides of rectangle, 4th side is implicit)
            is_rectangular = (len(point_pairs) == 4 and
                            len(path_points) == 4 and
                            abs(path_points[0][1] - path_points[1][1]) < 5 and  # First segment horizontal
                            abs(path_points[1][0] - path_points[2][0]) < 5 and  # Second segment vertical
                            abs(path_points[2][1] - path_points[3][1]) < 5)     # Third segment horizontal

            if is_rectangular:
                # Find CONNECTORS (not just pins) near all 4 corners
                # Rectangular routing wires connect entire connectors, not specific pins

                # CRITICAL: For rectangular polylines, determine wire spec ONCE using longest segment
                # This will be reused for all connections created from this polyline
                rectangular_wire_spec = self._find_wire_spec_for_rectangular_polyline(path_points)

                corner_endpoints = []
                for px, py in path_points:
                    # Find nearest connector label or pin/splice
                    nearest_connector = None
                    min_dist = 15  # max distance (tight threshold to match only true endpoints, not incidental nearby labels)

                    for elem in self.text_elements:
                        dist = math.sqrt((elem.x - px)**2 + (elem.y - py)**2)
                        if dist < min_dist:
                            # Accept: connector IDs, pins (digits), or splice points
                            if is_connector_id(elem.content) or elem.content.isdigit() or is_splice_point(elem.content):
                                min_dist = dist
                                nearest_connector = elem

                    if nearest_connector:
                        # If it's a pin, find the connector above it
                        if nearest_connector.content.isdigit():
                            conn_result = find_connector_above_pin(
                                nearest_connector.x, nearest_connector.y, self.text_elements,
                                prefer_as_source=False
                            )
                            if conn_result:
                                # CRITICAL: Check if this connector+pin already has a horizontal wire
                                # If so, and the polyline will have a different wire spec, try alternative connectors
                                primary_connector = conn_result[0]
                                pin_num = nearest_connector.content

                                # Check existing horizontal wires from this connector+pin
                                existing_wire_spec = None
                                for conn in self.horizontal_connections:
                                    if conn.from_id == primary_connector and conn.from_pin == pin_num:
                                        existing_wire_spec = (conn.wire_dm, conn.wire_color)
                                        break

                                # Use the pre-calculated wire spec for this rectangular polyline
                                polyline_wire_spec = rectangular_wire_spec

                                # If wire specs conflict, try to find alternative connector
                                if existing_wire_spec and polyline_wire_spec != (None, None):
                                    if existing_wire_spec != polyline_wire_spec:
                                        # Try to find an alternative connector (not the primary one)
                                        all_connectors = find_all_connectors_above_pin(
                                            nearest_connector.x, nearest_connector.y, self.text_elements
                                        )
                                        # Filter out the primary connector and use the next available one
                                        # Note: find_all_connectors_above_pin returns (y_distance, connector_id, x, y)
                                        for y_dist, alt_conn_id, alt_x, alt_y in all_connectors:
                                            if alt_conn_id != primary_connector:
                                                # Found an alternative connector
                                                conn_result = (alt_conn_id, alt_x, alt_y)
                                                break

                                endpoint = ConnectionPoint(
                                    connector_id=conn_result[0],
                                    pin=nearest_connector.content,
                                    x=conn_result[1],
                                    y=conn_result[2]
                                )
                            else:
                                endpoint = None
                        else:
                            # It's a connector label or splice - use directly
                            endpoint = ConnectionPoint(
                                connector_id=nearest_connector.content,
                                pin='',
                                x=nearest_connector.x,
                                y=nearest_connector.y
                            )

                        if endpoint:
                            corner_endpoints.append(endpoint)

                # Create connections between adjacent corners
                if len(corner_endpoints) >= 2:
                    # Use the pre-calculated wire spec for rectangular polylines
                    wire_dm, wire_color = rectangular_wire_spec if rectangular_wire_spec != (None, None) else ('', '')

                    for i in range(len(corner_endpoints) - 1):
                        ep1 = corner_endpoints[i]
                        ep2 = corner_endpoints[i + 1]

                        # Skip if endpoints are the same
                        if (ep1.connector_id == ep2.connector_id and ep1.pin == ep2.pin):
                            continue

                        # Create connection
                        conn = Connection(
                            from_id=ep1.connector_id,
                            from_pin=ep1.pin if ep1.pin else '',
                            to_id=ep2.connector_id,
                            to_pin=ep2.pin if ep2.pin else '',
                            wire_dm=wire_dm,
                            wire_color=wire_color
                        )
                        connections.append(conn)

                # Skip normal endpoint processing for rectangular polylines
                continue

            # Find nearest connection points to both endpoints (for non-rectangular polylines)
            # Pass horizontal_connections to filter out pins already in use
            endpoint1 = find_nearest_connection_point(start_x, start_y, self.text_elements, max_distance=100,
                                                     horizontal_connections=self.horizontal_connections)
            endpoint2 = find_nearest_connection_point(end_x, end_y, self.text_elements, max_distance=100,
                                                     horizontal_connections=self.horizontal_connections)

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

                # CRITICAL: Collect ALL splices on segments, not just the first one
                # Example: 005→006→001 should find both 006
                # Example: RS857,3→008→007→004 should find both 008 and 007
                all_intermediate_splices = []

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
                            candidate_splice = find_nearest_connection_point(sx, sy, self.text_elements, max_distance=20)
                            # CRITICAL: Don't treat endpoints as intermediate splices
                            if candidate_splice and is_splice_point(candidate_splice.connector_id):
                                # Skip if this splice is one of the endpoints
                                if (candidate_splice.connector_id == endpoint1.connector_id and
                                    candidate_splice.pin == endpoint1.pin):
                                    continue
                                if (candidate_splice.connector_id == endpoint2.connector_id and
                                    candidate_splice.pin == endpoint2.pin):
                                    continue
                                # Add to list (not break!)
                                if candidate_splice not in all_intermediate_splices:
                                    all_intermediate_splices.append(candidate_splice)

                # If no splice found on segments, check vertices (for T-junctions)
                # CRITICAL: Use STRICT distance threshold (20 units) to avoid false matches
                # Long routing polylines can pass near other splices that aren't part of the path
                if not all_intermediate_splices:
                    for i in range(1, len(parsed_points) - 1):  # Skip first and last
                        px, py = parsed_points[i]
                        intermediate = find_nearest_connection_point(px, py, self.text_elements, max_distance=20)
                        if intermediate and is_splice_point(intermediate.connector_id):
                            if intermediate not in all_intermediate_splices:
                                all_intermediate_splices.append(intermediate)

                # If we found intermediate splices, create connections for ALL adjacent pairs
                # Example: 005→006→001 creates: 005→006, 006→001
                # Example: RS857,3→008→007→004 creates: RS857,3→008, 008→007, 007→004
                if all_intermediate_splices:

                    # CRITICAL: Determine path orientation (vertical vs horizontal)
                    # For vertical paths, sort by Y (top to bottom)
                    # For horizontal paths, sort by X (left to right)
                    x_diff = abs(endpoint1.x - endpoint2.x)
                    y_diff = abs(endpoint1.y - endpoint2.y)

                    is_vertical = y_diff > x_diff

                    # Build complete chain including endpoints
                    all_points = [endpoint1] + all_intermediate_splices + [endpoint2]

                    # Sort chain by position (not by distance from arbitrary endpoint)
                    if is_vertical:
                        # Vertical: sort by Y (top to bottom = increasing Y)
                        all_points.sort(key=lambda p: p.y)
                    else:
                        # Horizontal: sort by X (left to right = increasing X)
                        all_points.sort(key=lambda p: p.x)

                    # For multi-segment paths, source is first point in sorted chain
                    wire_dm, wire_color = self._find_wire_spec_near_path(path_points, (start_x, start_y))

                    # Create connections for all adjacent pairs
                    chain = all_points

                    # CRITICAL: When multiple pins from same connector are in chain with splices,
                    # each pin should connect to the splice, not to each other
                    # Example: FL7611,5 → FL7611,9 → FL7611,1 → SP025
                    # Should create: FL7611,5→SP025, FL7611,9→SP025, FL7611,1→SP025
                    # NOT: FL7611,5→FL7611,9, FL7611,9→FL7611,1, FL7611,1→SP025

                    # Check if chain contains splice points
                    has_splice_in_chain = any(is_splice_point(p.connector_id) for p in chain)

                    if has_splice_in_chain:
                        # Group consecutive pins from same connector, connect each to nearest splice
                        # Example: FL7611,5 → SP025, FL7611,9 → SP025, FL7611,1 → SP025

                        for i in range(len(chain)):
                            current = chain[i]

                            # Skip if current is a splice (splices can form chains)
                            if is_splice_point(current.connector_id):
                                continue

                            # Find nearest splice point in chain (could be before or after)
                            nearest_splice = None
                            min_distance = float('inf')

                            for j in range(len(chain)):
                                if i == j or not is_splice_point(chain[j].connector_id):
                                    continue

                                dist = math.sqrt((current.x - chain[j].x)**2 + (current.y - chain[j].y)**2)
                                if dist < min_distance:
                                    min_distance = dist
                                    nearest_splice = chain[j]

                            # Connect this pin to the nearest splice
                            if nearest_splice:
                                # Skip if has horizontal wire
                                from_key = (current.connector_id, current.pin)
                                if from_key in self.pins_with_horizontal_wires:
                                    continue

                                connections.append(Connection(
                                    from_id=current.connector_id,
                                    from_pin=current.pin,
                                    to_id=nearest_splice.connector_id,
                                    to_pin=nearest_splice.pin,
                                    wire_dm=wire_dm,
                                    wire_color=wire_color
                                ))

                        # Also create connections between consecutive splices
                        splice_indices = [i for i, p in enumerate(chain) if is_splice_point(p.connector_id)]
                        for i in range(len(splice_indices) - 1):
                            from_idx = splice_indices[i]
                            to_idx = splice_indices[i + 1]
                            from_splice = chain[from_idx]
                            to_splice = chain[to_idx]

                            # Skip if both are pass-through splices
                            if from_splice.connector_id in self.passthrough_splices and to_splice.connector_id in self.passthrough_splices:
                                continue

                            connections.append(Connection(
                                from_id=from_splice.connector_id,
                                from_pin=from_splice.pin,
                                to_id=to_splice.connector_id,
                                to_pin=to_splice.pin,
                                wire_dm=wire_dm,
                                wire_color=wire_color
                            ))
                    else:
                        # No splices in chain - use normal adjacent pair logic
                        for i in range(len(chain) - 1):
                            from_point = chain[i]
                            to_point = chain[i + 1]

                            # Skip if self-loop
                            if from_point.connector_id == to_point.connector_id and from_point.pin == to_point.pin:
                                continue

                            # Skip if same connector (different pins)
                            if from_point.connector_id == to_point.connector_id:
                                continue

                            # CRITICAL: Skip short-distance splice-to-splice connections
                            # These are handled by LongRoutingConnectionExtractor with color flow analysis
                            both_splices = (is_splice_point(from_point.connector_id) and
                                          is_splice_point(to_point.connector_id))
                            if both_splices:
                                dist = math.sqrt((from_point.x - to_point.x)**2 + (from_point.y - to_point.y)**2)
                                if dist < 400:
                                    continue

                            connections.append(Connection(
                                from_id=from_point.connector_id,
                                from_pin=from_point.pin,
                                to_id=to_point.connector_id,
                                to_pin=to_point.pin,
                                wire_dm=wire_dm,
                                wire_color=wire_color
                            ))

                    # Continue to next polyline (don't process old two-connection logic below)
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

            # Skip if this SPECIFIC connection already exists in horizontal wires
            # (Horizontal wires take precedence, but a pin can have multiple connections to different destinations)
            connection_already_exists = any(
                (conn.from_id == source_endpoint.connector_id and conn.from_pin == source_endpoint.pin and
                 conn.to_id == dest_endpoint.connector_id and conn.to_pin == dest_endpoint.pin) or
                (conn.from_id == dest_endpoint.connector_id and conn.from_pin == dest_endpoint.pin and
                 conn.to_id == source_endpoint.connector_id and conn.to_pin == source_endpoint.pin)
                for conn in self.horizontal_connections
            )
            if connection_already_exists:
                continue

            # Skip routing connections between two pass-through splice points
            # (Avoids false connections like SP184 → SP113 where both have horizontal wires)
            # But allow connections from pass-through splices to pins (e.g., SP025 → FL7611,9)
            if (source_endpoint.connector_id in self.passthrough_splices and
                dest_endpoint.connector_id in self.passthrough_splices):
                continue

            # CRITICAL: Skip short-distance splice-to-splice connections
            # Short splice-to-splice connections (< 400 units) are likely false positives from
            # polylines/paths that cross splice points without actually connecting them.
            # Long routing connections (>= 400 units) are handled by LongRoutingConnectionExtractor
            # which uses wire color flow analysis to verify they're real connections.
            if ep1_is_splice and ep2_is_splice:
                dist = math.sqrt((endpoint1.x - endpoint2.x)**2 + (endpoint1.y - endpoint2.y)**2)
                if dist < 400:
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

                # Skip if this SPECIFIC connection already exists in horizontal wires
                connection_already_exists = any(
                    (conn.from_id == source.connector_id and conn.from_pin == source.pin and
                     conn.to_id == dest.connector_id and conn.to_pin == dest.pin) or
                    (conn.from_id == dest.connector_id and conn.from_pin == dest.pin and
                     conn.to_id == source.connector_id and conn.to_pin == source.pin)
                    for conn in self.horizontal_connections
                )
                if connection_already_exists:
                    continue

                # Skip if same source+dest pin but different dest connector (wrong connector above shared pin)
                same_source_different_dest_connector = any(
                    (conn.from_id == source.connector_id and conn.from_pin == source.pin and
                     conn.to_pin == dest.pin and conn.to_id != dest.connector_id and
                     not is_splice_point(conn.to_id) and not is_splice_point(dest.connector_id)) or
                    (conn.to_id == source.connector_id and conn.to_pin == source.pin and
                     conn.from_pin == dest.pin and conn.from_id != dest.connector_id and
                     not is_splice_point(conn.from_id) and not is_splice_point(dest.connector_id))
                    for conn in self.horizontal_connections
                )
                if same_source_different_dest_connector:
                    continue

                # Skip if same dest but different source connector (unless dest is splice - splices allow multiple sources)
                if not is_splice_point(dest.connector_id):
                    same_dest_different_source_connector = any(
                        (conn.to_id == dest.connector_id and conn.to_pin == dest.pin and
                         conn.from_pin == source.pin and conn.from_id != source.connector_id and
                         not is_splice_point(conn.from_id) and not is_splice_point(source.connector_id)) or
                        (conn.from_id == dest.connector_id and conn.from_pin == dest.pin and
                         conn.to_pin == source.pin and conn.to_id != source.connector_id and
                         not is_splice_point(conn.to_id) and not is_splice_point(source.connector_id))
                        for conn in self.horizontal_connections
                    )
                    if same_dest_different_source_connector:
                        continue

                # Skip short-distance splice-to-splice connections (handled by LongRoutingConnectionExtractor)
                both_splices = (is_splice_point(source.connector_id) and
                              is_splice_point(dest.connector_id))
                if both_splices:
                    dist = math.sqrt((source.x - dest.x)**2 + (source.y - dest.y)**2)
                    if dist < 400:
                        continue

                # CRITICAL: Validate wire color consistency for splice connections
                # If connecting pin → splice with color X, but splice already has connections with color Y ≠ X,
                # this is likely a false connection from an st1 path crossing unrelated connection points
                # Example: MH614,22 → SP198 with PU/OG, but SP198 only has BU/BK connections → reject!
                source_is_splice = is_splice_point(source.connector_id)
                dest_is_splice = is_splice_point(dest.connector_id)
                if (source_is_splice or dest_is_splice) and wire_dm and wire_color:
                    # Find the splice in this connection
                    splice_id = source.connector_id if source_is_splice else dest.connector_id

                    # Get existing colors for this splice
                    splice_colors = set()
                    for conn in self.horizontal_connections:
                        if conn.wire_color and (conn.from_id == splice_id or conn.to_id == splice_id):
                            splice_colors.add(conn.wire_color)

                    # If splice has existing colors and this color doesn't match any of them, reject
                    if splice_colors and wire_color not in splice_colors:
                        continue

                # NOTE: We do NOT apply connector boundary filtering to routing paths!
                # Routing paths (polylines, st1, st3/st4) represent intentional cross-boundary connections
                # (e.g., L-shaped wires that route from one module to another)
                # Connector boundary filtering only applies to horizontal wire connections in HorizontalWireExtractor

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
