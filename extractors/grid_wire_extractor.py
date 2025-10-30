"""
Grid wire connection extractor.

Extracts connections from grid-based routing diagrams where horizontal colored wires
and vertical dashed wires form a routing grid connecting pins.

Grid-based diagrams use:
- Horizontal colored wires (st8-st31 classes) at specific Y levels
- Vertical dashed wires (st16 class) at specific X columns
- Pins connect to vertical wires, which connect to horizontal wires, forming a routing grid
"""
from typing import List, Tuple
from models import Connection, TextElement
from connector_finder import (
    is_splice_point,
    find_connector_above_pin
)


class GridWireExtractor:
    """
    Extracts connections from grid-based routing diagrams.

    Algorithm:
    1. Find all pins from text elements
    2. For each pin, find connecting vertical wire (same X ± tolerance)
    3. Follow vertical wire to find horizontal wire intersections
    4. Follow horizontal wires to other vertical wire intersections
    5. Follow vertical wires to destination pins
    """

    def __init__(self, text_elements: List[TextElement],
                 horizontal_wires: List['HorizontalWireSegment'],
                 vertical_wires: List['VerticalWireSegment']):
        self.text_elements = text_elements
        self.horizontal_wires = horizontal_wires
        self.vertical_wires = vertical_wires

        # Tolerances for matching
        self.X_TOLERANCE = 5.0  # Pins/wires within 5 units in X are "same column"
        self.Y_TOLERANCE = 5.0  # Pins/wires within 5 units in Y are "same row"

    def extract_connections(self) -> List[Connection]:
        """
        Extract all connections from the grid routing system.

        Returns:
            List of Connection objects
        """
        connections = []

        # Get all pins with their connector associations
        pins = self._get_all_pins()

        # For each pair of pins, check if they're connected via the grid
        for i, pin1 in enumerate(pins):
            for pin2 in pins[i+1:]:
                # Check if pin1 and pin2 are connected via grid routing
                conn = self._trace_connection(pin1, pin2)
                if conn:
                    connections.append(conn)

        return connections

    def _get_all_pins(self) -> List[Tuple[str, str, float, float]]:
        """
        Get all pins from text elements.

        Returns:
            List of tuples: (connector_id, pin, x, y)
        """
        pins = []

        for elem in self.text_elements:
            # Pin numbers are single digits or small numbers
            if elem.content.isdigit() or is_splice_point(elem.content):
                # Find connector above this pin
                result = find_connector_above_pin(elem.x, elem.y, self.text_elements)
                if result:
                    connector_id, conn_x, conn_y = result
                    pin_number = '' if is_splice_point(elem.content) else elem.content
                    pins.append((connector_id, pin_number, elem.x, elem.y))

        return pins

    def _trace_connection(self, pin1: Tuple, pin2: Tuple) -> Connection:
        """
        Trace if two pins are connected via grid routing.

        Args:
            pin1: (connector_id, pin, x, y)
            pin2: (connector_id, pin, x, y)

        Returns:
            Connection object if connected, None otherwise
        """
        conn1_id, pin1_num, x1, y1 = pin1
        conn2_id, pin2_num, x2, y2 = pin2

        # CRITICAL: Don't connect pins on the same connector
        if conn1_id == conn2_id:
            return None

        # Find vertical wires connected to each pin
        v_wire1 = self._find_vertical_wire_at_pin(x1, y1)
        v_wire2 = self._find_vertical_wire_at_pin(x2, y2)

        if not v_wire1 or not v_wire2:
            return None

        # Check if they connect via a horizontal wire
        # Find horizontal wires that intersect with both vertical wires
        for h_wire in self.horizontal_wires:
            # Check if horizontal wire intersects v_wire1
            if not self._wires_intersect_vertical_horizontal(v_wire1, h_wire):
                continue

            # Check if horizontal wire intersects v_wire2
            if not self._wires_intersect_vertical_horizontal(v_wire2, h_wire):
                continue

            # Both vertical wires connect to this horizontal wire!
            # Determine direction: use X coordinates (left pin = source)
            if x1 < x2:
                return Connection(
                    from_id=conn1_id,
                    from_pin=pin1_num,
                    to_id=conn2_id,
                    to_pin=pin2_num,
                    wire_dm='',
                    wire_color=h_wire.color_name
                )
            else:
                return Connection(
                    from_id=conn2_id,
                    from_pin=pin2_num,
                    to_id=conn1_id,
                    to_pin=pin1_num,
                    wire_dm='',
                    wire_color=h_wire.color_name
                )

        return None

    def _find_vertical_wire_at_pin(self, pin_x: float, pin_y: float) -> 'VerticalWireSegment':
        """
        Find vertical wire connected to a pin.

        Args:
            pin_x, pin_y: Pin coordinates

        Returns:
            VerticalWireSegment if found, None otherwise
        """
        for v_wire in self.vertical_wires:
            # Check if pin is at same X (within tolerance)
            if abs(v_wire.x - pin_x) > self.X_TOLERANCE:
                continue

            # Check if pin is within vertical wire's Y range (with tolerance)
            if v_wire.y1 - self.Y_TOLERANCE <= pin_y <= v_wire.y2 + self.Y_TOLERANCE:
                return v_wire

        return None

    def _wires_intersect_vertical_horizontal(self, v_wire: 'VerticalWireSegment',
                                             h_wire: 'HorizontalWireSegment') -> bool:
        """
        Check if vertical and horizontal wires intersect.

        Args:
            v_wire: Vertical wire segment
            h_wire: Horizontal wire segment

        Returns:
            True if wires intersect, False otherwise
        """
        # Check if horizontal wire's X range contains vertical wire's X
        if not (h_wire.x1 - self.X_TOLERANCE <= v_wire.x <= h_wire.x2 + self.X_TOLERANCE):
            return False

        # Check if vertical wire's Y range contains horizontal wire's Y
        if not (v_wire.y1 - self.Y_TOLERANCE <= h_wire.y <= v_wire.y2 + self.Y_TOLERANCE):
            return False

        return True
