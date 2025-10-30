"""
Horizontal colored wire connection extractor.

Extracts connections from horizontal colored wires (non-grid diagrams).
For diagrams where horizontal colored wires directly connect connectors
without strict vertical routing columns. Uses wire endpoints to determine
which connectors are connected.

Algorithm:
1. For each horizontal colored wire
2. Find connectors/pins near the LEFT endpoint (source region)
3. Find connectors/pins near the RIGHT endpoint (destination region)
4. Create connections based on wire color
"""
from typing import List, Optional, Tuple
from models import Connection, TextElement, WireSpec, ConnectionPoint
from connector_finder import (
    is_connector_id,
    is_splice_point,
    find_all_connectors_above_pin
)


class HorizontalColoredWireExtractor:
    """
    Extracts connections from horizontal colored wires (non-grid diagrams).

    For diagrams where horizontal colored wires directly connect connectors
    without strict vertical routing columns. Uses wire endpoints to determine
    which connectors are connected.
    """

    def __init__(self, text_elements: List[TextElement],
                 horizontal_wires: List['HorizontalWireSegment'],
                 wire_specs: List[WireSpec] = None):
        self.text_elements = text_elements
        self.horizontal_wires = horizontal_wires
        self.wire_specs = wire_specs or []

        # Tolerance for finding connectors near wire endpoints
        self.X_TOLERANCE = 30.0  # Connectors within 30 units of wire end
        self.Y_TOLERANCE = 15.0  # Pins/splices within 15 units of wire height

    def extract_connections(self) -> List[Connection]:
        """
        Extract all connections from horizontal colored wires.

        Uses same logic as HorizontalWireExtractor: finds ALL connection points
        along the wire and creates connections between adjacent pairs.

        Returns:
            List of Connection objects
        """
        connections = []

        for wire in self.horizontal_wires:
            # Find ALL connection points along this horizontal wire
            # (pins and splices within Y tolerance and X range)
            connection_points = []

            for elem in self.text_elements:
                if not (elem.content.isdigit() or is_splice_point(elem.content)):
                    continue

                # Check if element is on same horizontal level as wire
                y_dist = abs(elem.y - wire.y)
                if y_dist > self.Y_TOLERANCE:
                    continue

                # Check if element is within wire's X range (with tolerance)
                if not (wire.x1 - self.X_TOLERANCE <= elem.x <= wire.x2 + self.X_TOLERANCE):
                    continue

                # Add connection point
                if is_splice_point(elem.content):
                    connection_points.append(ConnectionPoint(elem.content, '', elem.x, elem.y))
                else:
                    # For pins, determine which side of wire they're on
                    if elem.x <= (wire.x1 + wire.x2) / 2:
                        side = "left"
                        wire_end_x = wire.x1
                    else:
                        side = "right"
                        wire_end_x = wire.x2

                    connector_result = self._find_connector_near_pin_and_wire_end(
                        elem.x, elem.y, wire_end_x, side
                    )
                    if connector_result:
                        connection_points.append(ConnectionPoint(
                            connector_result[0],
                            elem.content,
                            elem.x,
                            elem.y
                        ))

            # Sort by X coordinate (left to right)
            connection_points.sort(key=lambda p: p.x)

            # Create connections between ALL ADJACENT PAIRS
            for i in range(len(connection_points) - 1):
                left_cp = connection_points[i]
                right_cp = connection_points[i + 1]

                # Skip if same connector (self-loop)
                if left_cp.connector_id == right_cp.connector_id and left_cp.pin == right_cp.pin:
                    continue

                # Find wire spec between or near these two points
                wire_dm = ''
                if self.wire_specs:
                    # Find specs between the points or closest to the pair
                    pair_avg_y = (left_cp.y + right_cp.y) / 2
                    between_specs = [
                        s for s in self.wire_specs
                        if (left_cp.x < s.x < right_cp.x and abs(s.y - pair_avg_y) < 20)
                    ]

                    if between_specs:
                        # Use spec between points, closest in Y
                        wire_spec = min(between_specs, key=lambda s: abs(s.y - pair_avg_y))
                        wire_dm = wire_spec.diameter
                    else:
                        # Check for spec near the wire (within Y tolerance)
                        nearby_specs = [
                            s for s in self.wire_specs
                            if abs(s.y - wire.y) < self.Y_TOLERANCE and wire.x1 < s.x < wire.x2
                        ]
                        if nearby_specs:
                            wire_spec = min(nearby_specs, key=lambda s: abs(s.y - wire.y))
                            wire_dm = wire_spec.diameter

                connections.append(Connection(
                    from_id=left_cp.connector_id,
                    from_pin=left_cp.pin,
                    to_id=right_cp.connector_id,
                    to_pin=right_cp.pin,
                    wire_dm=wire_dm,
                    wire_color=wire.color_name
                ))

        return connections

    def _find_connection_points_near(self, target_x: float, target_y: float, side: str) -> List[ConnectionPoint]:
        """
        Find connection points (connectors/pins) near a wire endpoint.

        Args:
            target_x: X coordinate of wire endpoint
            target_y: Y coordinate of wire (horizontal)
            side: "left" or "right" - which side of the wire we're checking

        Returns:
            List of ConnectionPoint objects
        """
        connection_points = []

        # Find pins on the same horizontal level
        for elem in self.text_elements:
            if not (elem.content.isdigit() or is_splice_point(elem.content)):
                continue

            y_dist = abs(elem.y - target_y)
            if y_dist > self.Y_TOLERANCE:
                continue

            # Check X distance based on side
            x_dist = abs(elem.x - target_x)
            if x_dist > self.X_TOLERANCE:
                continue

            # Prefer elements on the correct side
            # For "left" side, prefer elements to the left of or at the endpoint
            # For "right" side, prefer elements to the right of or at the endpoint
            if side == "left" and elem.x > target_x + self.X_TOLERANCE:
                continue
            if side == "right" and elem.x < target_x - self.X_TOLERANCE:
                continue

            # Find connector for this pin
            if is_splice_point(elem.content):
                connection_points.append(ConnectionPoint(elem.content, '', elem.x, elem.y))
            else:
                # For pins, find connector above and prefer connector on the SAME SIDE as wire endpoint
                connector_result = self._find_connector_near_pin_and_wire_end(
                    elem.x, elem.y, target_x, side
                )
                if connector_result:
                    connection_points.append(ConnectionPoint(
                        connector_result[0],  # connector_id
                        elem.content,          # pin
                        elem.x,
                        elem.y
                    ))

        # Fallback: if no pins found, look for connectors directly
        if not connection_points:
            for elem in self.text_elements:
                if not is_connector_id(elem.content):
                    continue
                if '(' in elem.content:  # Skip ground connectors
                    continue

                y_dist = abs(elem.y - target_y)
                x_dist = abs(elem.x - target_x)

                # Connectors can be further from the wire (up to 50 units in Y)
                if y_dist > 50 or x_dist > self.X_TOLERANCE:
                    continue

                # Check side preference
                if side == "left" and elem.x > target_x + self.X_TOLERANCE:
                    continue
                if side == "right" and elem.x < target_x - self.X_TOLERANCE:
                    continue

                connection_points.append(ConnectionPoint(elem.content, '', elem.x, elem.y))

        return connection_points

    def _find_connector_near_pin_and_wire_end(self, pin_x: float, pin_y: float,
                                               wire_end_x: float, side: str) -> Optional[Tuple[str, float, float]]:
        """
        Find connector above a pin, preferring connectors closer to the wire endpoint.

        For shared pins between adjacent connectors (e.g., MAIN14 and SR01 sharing pins),
        this prefers the connector that's on the same side as the wire endpoint.

        Args:
            pin_x, pin_y: Pin coordinates
            wire_end_x: X coordinate of wire endpoint
            side: "left" or "right"

        Returns:
            Tuple of (connector_id, x, y) or None
        """
        connectors_above = find_all_connectors_above_pin(pin_x, pin_y, self.text_elements)

        if not connectors_above:
            return None

        # If only one connector, use it
        if len(connectors_above) == 1:
            conn = connectors_above[0]
            return (conn[1], conn[2], conn[3])

        # Multiple connectors - prefer based on which side of pins the wire endpoint is on
        # This handles shared pins where wire endpoint doesn't reach the pins
        # Example: MAIN14 (X=628) ← wire ends at X=646 ← pins at X=650 ← SR01 (X=653)
        # Wire endpoint (646) is LEFT of pins (650), so pick MAIN14 (also left of pins)

        # Determine which side of pins the wire endpoint is on
        if wire_end_x < pin_x:
            # Wire endpoint is LEFT of pins - prefer leftmost connector
            best_connector = min(connectors_above, key=lambda c: c[2])
        else:
            # Wire endpoint is RIGHT of pins - prefer rightmost connector
            best_connector = max(connectors_above, key=lambda c: c[2])

        return (best_connector[1], best_connector[2], best_connector[3])
