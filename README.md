# Circuit Diagram SVG Connection Extractor

Extract wire connections from circuit diagram SVG files exported from Adobe Illustrator.

## Quick Start

```bash
python extract_connections.py
```

**Input:** `sample-wire.svg` (Adobe Illustrator SVG export)
**Output:** `connections_output.md` (markdown table of all wire connections)

## Installation

No external dependencies required - uses Python standard library only.

**Requirements:**
- Python 3.7+

## Usage

### Basic Usage

```bash
python extract_connections.py
```

This will:
1. Parse `sample-wire.svg`
2. Extract 54 wire connections (48 horizontal + 5 vertical + 1 ground)
3. Generate `connections_output.md` with sorted connection table

### Output Format

The tool generates a markdown file with two sections:

**1. All Connections (Sorted)**
```markdown
| From | From Pin | To | To Pin | Wire DM | Color |
|------|----------|-----|--------|---------|-------|
| FL2MH | 1 | FL7210 | 4 | 0.35 | GY/PU |
| FL2MH | 2 | FL7210 | 6 | 0.35 | BK/GN |
| MH3202C | 25 | MH2FL | 8 | 0.35 | WH/RD |
```

**2. Grouped by Source Connector**
```markdown
### MH3202C (6 connections)
| From Pin | To | To Pin | Wire DM | Color |
|----------|-----|--------|---------|-------|
| 25 | MH2FL | 8 | 0.35 | WH/RD |
| 26 | MH2FL | 9 | 0.35 | BU/BK |
```

## Architecture

The codebase uses a **modular architecture** for maintainability:

```
extract_connections.py    # Main entry point
├── models.py            # Data structures (Connection, TextElement, WireSpec)
├── svg_parser.py        # SVG parsing utilities
├── connector_finder.py  # Connector identification with junction handling
├── extractors.py        # Connection extraction classes
│   ├── HorizontalWireExtractor
│   ├── VerticalRoutingExtractor
│   └── GroundConnectionExtractor
└── output_formatter.py  # Output formatting and export
```

### Key Components

**models.py** - Core data structures
- `Connection` - Wire connection with from/to connector, pin, diameter, color
- `TextElement` - SVG text element with coordinates
- `WireSpec` - Wire specification (diameter, color)
- `IDGenerator` - For future custom ID generation

**svg_parser.py** - SVG element extraction
- Parse text elements with coordinates
- Find splice point dots
- Extract st17 polylines (vertical routing)
- Extract st17 paths (ground connections)

**connector_finder.py** - Sophisticated connector lookup
- Euclidean distance sorting
- Junction pair detection (MH2FL/FL2MH, FTL2FL/FL2FTL)
- "Between" logic for junction selection
- Type-specific distance calculations

**extractors.py** - Three specialized extractors
- `HorizontalWireExtractor` - Wire-centric algorithm for horizontal wires
- `VerticalRoutingExtractor` - Processes st17 polylines
- `GroundConnectionExtractor` - Processes st17 paths (120-unit threshold)

## Key Features

✓ **Wire-centric algorithm** - Lets wires dictate connections (not boundary-based)
✓ **Junction handling** - Proper direction semantics (*2FL = destinations, FL2* = sources)
✓ **Multiple connection types** - Horizontal wires, vertical routing, ground connections
✓ **Context-aware junction selection** - Uses source_x for "between" logic
✓ **Automatic deduplication** - Each extractor deduplicates independently
✓ **Sorted output** - By connector ID and pin number
✓ **Modular architecture** - Easy to extend and maintain

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Complete algorithm details, design decisions, and architecture
- **[wire-relation-prompt.md](wire-relation-prompt.md)** - AI prompt for processing similar SVG files

## Files

**Core modules:**
- `extract_connections.py` - Main entry point
- `models.py` - Data structures
- `svg_parser.py` - SVG parsing
- `connector_finder.py` - Connector identification
- `extractors.py` - Extraction classes
- `output_formatter.py` - Output formatting

**Sample data:**
- `sample-wire.svg` - Example circuit diagram
- `diagram.png` - Visual reference
- `connections_output.md` - Generated output

**Documentation:**
- `README.md` - This file
- `CLAUDE.md` - Technical documentation
- `wire-relation-prompt.md` - AI prompt reference

## How It Works

### Wire-Centric Approach

Instead of trying to assign pins to connectors using spatial boundaries:

1. **Find all wire specifications** (e.g., "0.35,GY/PU")
2. **For each wire, find all pins on the same horizontal line** (±10 Y units)
3. **Create connections between ALL ADJACENT PAIRS** of pins
4. **For each pin, find the connector directly above it**
5. **Handle junction pairs** using sophisticated selection logic

### Critical Design Parameters

- **Y-axis tolerance:** ±10 units (horizontal line alignment)
- **X-axis threshold:** 50 units (regular connectors), 100 units (junctions)
- **Ground connection threshold:** 120 units (prevents distant splice points)
- **Minimum Y-distance:** 5 units (connector must be above pin)

### Junction Connector Rules

Circuit diagrams use bidirectional junction connectors:

- **`*2FL` variants (MH2FL, FTL2FL)** = DESTINATIONS (wires come IN)
- **`FL2*` variants (FL2MH, FL2FTL)** = SOURCES (wires go OUT)

The `find_connector_above_pin()` function uses:
- **prefer_as_source** flag to select appropriate variant
- **source_x** parameter for context-aware "between" logic
- **Type-specific distance** calculations (MH vs FTL junctions)

## Example

```bash
$ python extract_connections.py
================================================================================
Circuit Diagram Connection Extractor
================================================================================
Parsing SVG file...
Parsed 268 text elements
Parsed 200 splice point dots
Found 4 st17 polyline elements
Found 3 st17 path elements
Found 52 wire specifications

================================================================================
Extracting Horizontal Wire Connections
================================================================================
Extracted 48 horizontal wire connections

================================================================================
Extracting Vertical Routing (st17 polylines)
================================================================================
Extracted 5 vertical routing connections

================================================================================
Extracting Ground Connections (st17 paths)
================================================================================
Extracted 1 ground connections

================================================================================
Total connections: 54
================================================================================
✓ Exported to connections_output.md

Breakdown:
  - Horizontal wires (with specs): 48
  - Vertical routing + Ground: 6
```

## Future Enhancements

The modular architecture is ready for:

- **Custom ID generation** for unnamed splice points (SP_CUSTOM_001, etc.)
- **Custom ID generation** for unnamed connectors (CON_CUSTOM_001, etc.)
- **Export formats** - CSV, JSON, Excel
- **Validation** against physical connector pin counts
- **Multi-file processing** - Batch extraction from multiple SVG files
- **Configuration** - Adjustable thresholds via config file

## License

See repository license.
