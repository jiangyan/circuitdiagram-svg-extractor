"""
Ground connection extractor.

Extracts ground connections from st17 path elements (arrow heads pointing to ground connectors).
"""
import re
import math
from typing import List, Tuple
from models import Connection, TextElement, WireSpec
from connector_finder import (
    is_connector_id,
    is_splice_point,
    find_all_connectors_above_pin
)
from .base_extractor import BaseExtractor, deduplicate_connections


class GroundConnectionExtractor(BaseExtractor):
    """Extracts ground connections from st17 path elements."""

    def __init__(self, paths: List[str], text_elements: List[TextElement], wire_specs: List[WireSpec] = None, horizontal_connections: List[Connection] = None):
        # Initialize base class
        super().__init__(text_elements, wire_specs or [])

        self.paths = paths
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
