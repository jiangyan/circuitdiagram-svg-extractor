# Architecture

## Module Structure

```
extract_connections.py          # Main entry point
├── models.py                  # Data structures (Connection, TextElement, WireSpec, etc.)
├── svg_parser.py              # SVG parsing utilities
├── connector_finder.py        # Connector identification and lookup logic
├── output_formatter.py        # Output formatting and export
└── extractors/                # Connection extraction package (modular)
    ├── __init__.py           # Package initialization, exports all extractors
    ├── base_extractor.py     # Base class with shared utilities
    ├── horizontal_wire_extractor.py
    ├── horizontal_colored_wire_extractor.py
    ├── vertical_routing_extractor.py
    ├── ground_connection_extractor.py
    ├── long_routing_connection_extractor.py
    └── grid_wire_extractor.py
```

### Benefits of Modular Architecture

- **Clarity**: Each extractor has its own file (~150-400 lines vs 2175-line monolith)
- **Maintainability**: Changes to one extractor don't affect others
- **Testability**: Individual extractors can be tested in isolation
- **Reusability**: BaseExtractor shares common utilities (wire spec detection, deduplication)
- **Scalability**: New extractor types can be added without modifying existing code

## Key Data Structures (models.py)

```python
@dataclass
class Connection:
    from_id: str
    from_pin: str
    to_id: str
    to_pin: str
    wire_dm: str
    wire_color: str

@dataclass
class TextElement:
    content: str
    x: float
    y: float

@dataclass
class WireSpec:
    diameter: str
    color: str
    x: float
    y: float

@dataclass
class ConnectionPoint:
    connector_id: str
    pin: str
    x: float
    y: float

@dataclass
class HorizontalWireSegment:
    x1: float
    x2: float
    y: float
    color_class: str
    color_name: str

class IDGenerator:
    """Generates custom IDs for unnamed splice points and connectors"""
    def get_or_create_splice_id(x: float, y: float) -> str
    def get_or_create_connector_id(x: float, y: float) -> str
```

## SVG Parser (svg_parser.py)

Core functions for parsing SVG elements:

- `parse_text_elements()` - Extract all text with coordinates
- `merge_multiline_connectors()` - Merge shielded pair connectors (XR-/XR+)
- `parse_splice_dots()` - Find splice point dot positions (circle paths)
- `parse_all_polylines()` - Extract all polylines (including routing)
- `parse_st17_polylines()` - Extract vertical routing polylines
- `parse_st17_paths()` - Extract ground connection paths
- `parse_st1_paths()` - Extract white routing wire paths
- `parse_routing_paths(only_l_shaped=True)` - Extract L-shaped routing paths (st3/st4) with vertical segments
- `parse_horizontal_colored_wires()` - Extract colored horizontal wire segments (CSS classes st5-st31)
- `parse_vertical_dashed_wires()` - Extract vertical dashed wire segments
- `extract_wire_specs()` - Find wire specifications (diameter, color)
- `extract_path_endpoints()` - Extract start and end points from path 'd' attribute
- `extract_path_all_points()` - Extract all points along a path (for multi-segment polylines)
- `map_splice_positions_to_dots()` - Map SP* labels to actual dot positions
- `generate_ids_for_unlabeled_splices()` - Generate custom IDs (SP_CUSTOM_*) for dots without labels

## Connector Finder (connector_finder.py)

Core logic for finding connectors above pins with sophisticated junction handling:

```python
def find_connector_above_pin(
    pin_x: float,
    pin_y: float,
    text_elements: List[TextElement],
    prefer_as_source: bool = False,
    source_x: float = None,
    destination_x: float = None
) -> Optional[Tuple[str, float, float]]:
    """
    Implements:
    - Euclidean distance sorting
    - Junction pair detection
    - "Between" logic: picks junction physically between source and destination
    - Type-specific selection:
      * MH junctions: pick closer to PIN (tightly packed)
      * FTL junctions: pick closer to SOURCE (spread out)
    - Y-distance threshold: 60 units for "between" connectors
    """
```

### Helper Functions

- `is_connector_id(text)` - Check if text is a valid connector ID (including multiline)
- `is_splice_point(text)` - Check if text is a splice point ID (SP001 or SP_CUSTOM_001)
- `is_pin_number(text)` - Check if text is a pin number (regular or dash-separated)
- `is_wire_spec(text)` - Check if text matches wire spec pattern
- `parse_wire_spec(text)` - Parse wire spec into (diameter, color)
- `is_ground_connector(text)` - Check if connector is a ground connector
- `find_all_connectors_above_pin()` - Get all connectors above a pin (for disambiguation)

## Output Formatter (output_formatter.py)

Functions for formatting and exporting connections:

- `format_multiline_for_markdown(text)` - Convert newlines to `<br>` tags
- `format_markdown_table(connections)` - Format connections as markdown table
- `format_grouped_by_source(connections)` - Group connections by source connector
- `generate_report(connections)` - Generate complete markdown report
- `export_to_file(connections, filename)` - Export to markdown file
- `print_summary_statistics(connections)` - Print extraction statistics

## Extractors Package (extractors/)

### Base Extractor (base_extractor.py)

`BaseExtractor` provides shared utilities for all extractors:

```python
class BaseExtractor:
    def __init__(self, text_elements: List[TextElement], wire_specs: List[WireSpec]):
        self.text_elements = text_elements
        self.wire_specs = wire_specs

    def _find_wire_spec_for_rectangular_polyline(self, path_points) -> Tuple[str, str]:
        """Find wire spec on LONGEST horizontal segment of rectangular polyline."""
        # Returns (diameter, color) from longest horizontal segment

    def _find_wire_spec_near_path(self, path_points, source_point=None) -> Tuple[str, str]:
        """Find wire spec closest to routing path, prioritizing segment near source."""
        # Returns (diameter, color) from horizontal segment closest to source
```

Also includes `deduplicate_connections()` function for global deduplication.

### Specialized Extractors

#### 1. HorizontalWireExtractor (`horizontal_wire_extractor.py`)

**Purpose:** Primary extractor for horizontal wires with wire specs (most connections)

**Algorithm:**
- Groups connection points by horizontal line (±10 Y units)
- Creates connections between ALL ADJACENT PAIRS on same line
- Handles junction selection with source_x context
- Filters out wire specs on polyline segments

**Key Features:**
- Pin-pair deduplication
- Wire spec selection closest to average pin Y
- Clustered connection point processing
- Junction bypass detection

#### 2. HorizontalColoredWireExtractor (`horizontal_colored_wire_extractor.py`)

**Purpose:** Handles horizontal colored wires in non-grid diagrams

**Algorithm:**
- Parses colored wire segments from `<line>` and `<path>` elements
- Finds all connection points along wire (pins, splices)
- Creates connections between adjacent pairs
- Uses wire color instead of wire specs

**Key Features:**
- CSS class to color mapping (st5-st31)
- Connector detection near wire endpoints
- Wire diameter lookup from nearby specs

#### 3. VerticalRoutingExtractor (`vertical_routing_extractor.py`) **[inherits BaseExtractor]**

**Purpose:** Processes vertical routing connections

**Handles:**
- st17 polylines (vertical routing arrows)
- st1 paths (white routing wires)
- st3/st4 paths (L-shaped routing wires with vertical segments)
- Rectangular polylines (4-point H-V-H pattern)

**Key Features:**
- Pass-through splice tracking
- Multi-segment polyline handling
- Nearest endpoint detection
- Self-connection filtering
- Uses inherited wire spec detection methods

#### 4. GroundConnectionExtractor (`ground_connection_extractor.py`) **[inherits BaseExtractor]**

**Purpose:** Processes ground connections (st17 paths)

**Algorithm:**
- Finds connection points within 120 units of path arrow
- Only creates connections involving ground connectors
- Prefers *2FL junction variants

**Key Features:**
- Ground connector pattern recognition
- Distance-based filtering (stricter than regular routing)
- Junction variant preference

#### 5. LongRoutingConnectionExtractor (`long_routing_connection_extractor.py`)

**Purpose:** Handles long-distance splice-to-splice connections

**Algorithm:**
- Uses wire color flow to trace multi-hop paths
- Finds indirect connections through intermediate splices

**Key Features:**
- Color-based connection tracing
- Multi-hop path discovery

#### 6. GridWireExtractor (`grid_wire_extractor.py`)

**Purpose:** Handles grid-based routing diagrams

**Note:** Different coordinate system from standard diagrams

### BaseExtractor Inheritance Pattern

```python
# VerticalRoutingExtractor inherits shared utilities
from .base_extractor import BaseExtractor

class VerticalRoutingExtractor(BaseExtractor):
    def __init__(self, polylines, routing_paths, text_elements, wire_specs, horizontal_connections):
        # Initialize base class with shared data
        super().__init__(text_elements, wire_specs)
        # Initialize extractor-specific data
        self.polylines = polylines
        self.routing_paths = routing_paths
        # ...

    def extract_connections(self):
        # Use inherited method for rectangular polylines
        wire_spec = self._find_wire_spec_for_rectangular_polyline(path_points)

        # Use inherited method for normal routing paths
        wire_spec = self._find_wire_spec_near_path(path_points, source_point)
```

**Extractors using BaseExtractor:**
- `VerticalRoutingExtractor` - Uses both inherited wire spec methods
- `GroundConnectionExtractor` - Uses `_find_wire_spec_near_path()`

**Extractors NOT using BaseExtractor:**
- `HorizontalWireExtractor` - Has its own wire spec logic (groups by horizontal line)
- `HorizontalColoredWireExtractor` - Uses color flow, no wire specs
- `LongRoutingConnectionExtractor` - Uses color flow, no wire specs
- `GridWireExtractor` - Different coordinate system, independent logic

## Execution Flow

```python
# Imports from modular architecture
from extractors import (
    HorizontalWireExtractor,
    HorizontalColoredWireExtractor,
    VerticalRoutingExtractor,
    GroundConnectionExtractor,
    LongRoutingConnectionExtractor,
    deduplicate_connections
)
from models import IDGenerator
from svg_parser import (
    parse_text_elements,
    merge_multiline_connectors,
    parse_splice_dots,
    parse_all_polylines,
    parse_st17_paths,
    parse_st1_paths,
    parse_routing_paths,
    parse_horizontal_colored_wires,
    parse_vertical_dashed_wires,
    map_splice_positions_to_dots,
    generate_ids_for_unlabeled_splices,
    extract_wire_specs
)
from output_formatter import export_to_file

# 0. Initialize ID generator for unlabeled splice points
id_generator = IDGenerator()

# 1. Parse all SVG elements
text_elements = parse_text_elements(svg_file)
text_elements = merge_multiline_connectors(text_elements)  # Merge shielded pairs
splice_dots = parse_splice_dots(svg_file)
all_polylines = parse_all_polylines(svg_file)
st17_paths = parse_st17_paths(svg_file)
st1_paths = parse_st1_paths(svg_file)
routing_paths = parse_routing_paths(svg_file, only_l_shaped=True)
horizontal_wires = parse_horizontal_colored_wires(svg_file)
vertical_wires = parse_vertical_dashed_wires(svg_file)

# 2. Map splice positions
text_elements = map_splice_positions_to_dots(text_elements, splice_dots)
text_elements = generate_ids_for_unlabeled_splices(text_elements, splice_dots, id_generator)

# 3. Extract wire specs
wire_specs = extract_wire_specs(text_elements)

# 4. Run extractors independently
horizontal_connections = HorizontalWireExtractor(text_elements, wire_specs, all_polylines).extract_connections()

colored_wire_connections = HorizontalColoredWireExtractor(text_elements, horizontal_wires, wire_specs).extract_connections()

all_routing_paths = st1_paths + routing_paths
routing_connections = VerticalRoutingExtractor(
    all_polylines, all_routing_paths, text_elements, wire_specs, horizontal_connections
).extract_connections()

ground_connections = GroundConnectionExtractor(st17_paths, text_elements, wire_specs, horizontal_connections).extract_connections()

long_routing_connections = LongRoutingConnectionExtractor(combined_for_flow, text_elements).extract_connections()

# 5. Combine and deduplicate globally
combined = horizontal_connections + colored_wire_connections + routing_connections + ground_connections + long_routing_connections
all_connections = deduplicate_connections(combined)

# 6. Apply exclusions (if config exists)
all_connections = apply_exclusions(all_connections, pin_exclusions, connection_exclusions)

# 7. Export
export_to_file(all_connections, output_file)
```

## Critical Configuration Values

### Ground Connection Distance Threshold

```python
# Ground connections use stricter distance filtering
if y_dist < 10 and x_dist < 120:  # 120 units, not 200
    # Connection point is valid
```

This prevents distant splice points from being incorrectly associated with ground arrows.

### "Between" Logic Y-Distance Threshold

```python
# Only prioritize "between" connectors if they're reasonably close in Y
# Use a threshold of 60 Y-units as "reasonable" vertical distance
if is_between and y_dist < 60:
    between_connectors.append(conn)
```

Initially set to 50 units, increased to 60 units after discovering valid "between" connectors at Y-distance=52.4 were being excluded.

### Rectangular Polyline Endpoint Detection

```python
# Find connectors/pins near all 4 corners
min_dist = 15  # Tight threshold to match only true endpoints
```

**Why 15 units:**
- Valid endpoints: UH07 (10.6), UH08 (10.1), G203B(m) (12.7), pins (5-8 units)
- Excludes incidental labels: MAIN14 at 15.8 units (too far), G202(m) at 50 units (way too far)
