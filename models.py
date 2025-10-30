"""
Data models for circuit diagram connection extraction.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class TextElement:
    """Represents a text element from the SVG."""
    content: str
    x: float
    y: float


@dataclass
class ConnectionPoint:
    """Represents a connection point (connector with optional pin)."""
    connector_id: str
    pin: str  # Empty string if no pin
    x: float
    y: float


@dataclass
class Connection:
    """Represents a wire connection between two points."""
    from_id: str
    from_pin: str
    to_id: str
    to_pin: str
    wire_dm: str  # Wire diameter (empty for vertical/ground connections)
    wire_color: str  # Wire color (empty for vertical/ground connections)

    def __lt__(self, other):
        """Enable sorting by from_id, then from_pin."""
        if self.from_id != other.from_id:
            return self.from_id < other.from_id
        # Handle numeric pins
        try:
            self_pin = int(self.from_pin) if self.from_pin else 0
            other_pin = int(other.from_pin) if other.from_pin else 0
            return self_pin < other_pin
        except ValueError:
            return self.from_pin < other.from_pin


class IDGenerator:
    """Generates custom IDs for unnamed splice points and connectors."""

    def __init__(self):
        self._splice_counter = 1
        self._connector_counter = 1
        self._generated_ids = {}  # Map (x, y) -> generated_id

    def get_or_create_splice_id(self, x: float, y: float) -> str:
        """
        Get or create a custom splice point ID.

        Args:
            x, y: Coordinates of the splice point

        Returns:
            Custom ID like 'SP_CUSTOM_001'
        """
        key = (round(x, 2), round(y, 2))
        if key not in self._generated_ids:
            custom_id = f"SP_CUSTOM_{self._splice_counter:03d}"
            self._generated_ids[key] = custom_id
            self._splice_counter += 1
        return self._generated_ids[key]

    def get_or_create_connector_id(self, x: float, y: float) -> str:
        """
        Get or create a custom connector ID.

        Args:
            x, y: Coordinates of the connector

        Returns:
            Custom ID like 'CON_CUSTOM_001'
        """
        key = (round(x, 2), round(y, 2))
        if key not in self._generated_ids:
            custom_id = f"CON_CUSTOM_{self._connector_counter:03d}"
            self._generated_ids[key] = custom_id
            self._connector_counter += 1
        return self._generated_ids[key]

    def reset(self):
        """Reset the ID generators."""
        self._splice_counter = 1
        self._connector_counter = 1
        self._generated_ids = {}


@dataclass
class WireSpec:
    """Represents a wire specification found in the diagram."""
    diameter: str
    color: str
    x: float
    y: float


@dataclass
class HorizontalWireSegment:
    """Represents a horizontal wire segment in a grid routing system."""
    x1: float
    x2: float
    y: float
    color_class: str  # CSS class like 'st8', 'st21', etc.
    color_name: str  # Human-readable color like 'green', 'red', etc.


@dataclass
class VerticalWireSegment:
    """Represents a vertical wire segment in a grid routing system."""
    x: float
    y1: float
    y2: float
    color_class: str  # Usually 'st16' for dashed lines
    color_name: str  # Usually 'dashed' or 'black'
