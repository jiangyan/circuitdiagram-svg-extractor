"""
Extractors package for circuit diagram connection extraction.

This package contains specialized extractors for different types of connections:
- HorizontalWireExtractor: Standard horizontal wires with wire specifications
- HorizontalColoredWireExtractor: Colored horizontal wires in non-grid diagrams
- VerticalRoutingExtractor: Vertical routing arrows and st1/st3/st4 path wires
- GroundConnectionExtractor: Ground connections from st17 path elements
- LongRoutingConnectionExtractor: Long-distance splice connections via color flow analysis
- GridWireExtractor: Grid-based routing diagrams with vertical and horizontal wires
"""
from .base_extractor import BaseExtractor, deduplicate_connections
from .horizontal_wire_extractor import HorizontalWireExtractor
from .horizontal_colored_wire_extractor import HorizontalColoredWireExtractor
from .vertical_routing_extractor import VerticalRoutingExtractor
from .ground_connection_extractor import GroundConnectionExtractor
from .long_routing_connection_extractor import LongRoutingConnectionExtractor
from .grid_wire_extractor import GridWireExtractor

__all__ = [
    'BaseExtractor',
    'deduplicate_connections',
    'HorizontalWireExtractor',
    'HorizontalColoredWireExtractor',
    'VerticalRoutingExtractor',
    'GroundConnectionExtractor',
    'LongRoutingConnectionExtractor',
    'GridWireExtractor',
]
