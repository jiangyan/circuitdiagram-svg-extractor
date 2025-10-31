# Circuit Diagram SVG Connection Extractor

## Quick Overview

This tool extracts wire connections from circuit diagram SVG files (Adobe Illustrator). It parses connector IDs, pin numbers, wire specs (diameter/color), and produces a complete connection table.

**Core Approach:** Wire-centric algorithm - start from wire specifications, find pins on both ends, lookup connectors above pins.

## Usage

```bash
# Basic usage
python extract_connections.py [input.svg] [output.md]

# Default (if no args)
python extract_connections.py  # Uses sample-wire.svg → connections_output.md

# Example
python extract_connections.py test_cases/shielded-wire.svg test_cases/shielded-wire_output.md
```

## Top 5 Critical Rules

### 1. Y-Axis Tolerance: ±10 Units
Wire specs and pins must be on the same horizontal line. **±10 units** is the sweet spot for Adobe Illustrator SVG exports.
- Too large (±20): Groups pins from different rows → wrong connections
- Too small (±5): Misses valid pins due to SVG rendering variations

### 2. Wire-Centric Algorithm
Instead of assigning pins to connectors by spatial boundaries:
1. Find all wire specifications (e.g., "0.35,GY/PU")
2. For each wire, find pins on both ends of the horizontal line
3. For each pin, lookup the connector directly above it

This avoids complex spatial logic when pins are far below their connectors.

### 3. Junction Connector Direction Rules
Bidirectional junction connectors (e.g., `MH2FL` ↔ `FL2MH`) have specific direction semantics:
- `*2FL` variants = **destinations** (wires coming IN to junction)
- `FL2*` variants = **sources** (wires going OUT of junction)

Pass `prefer_as_source=True` for source pins, `False` for destination pins.

### 4. "Between" Logic for Shared Pins
When multiple connectors are above the same pin, prefer connectors **BETWEEN** the wire spec and pin (horizontally). This ensures correct connector selection at boundaries.

Configuration: Only prioritize "between" connectors within **60 Y-units** of the pin.

### 5. Pass-Through Splice Filtering
Splice points with horizontal wires on BOTH sides are "pass-throughs". **DO NOT** create routing connections between two pass-through splices - they already have dedicated horizontal wires.

## Key Files

**Core Modules:**
- `extract_connections.py` - Main entry point, orchestrates all extractors
- `models.py` - Data structures (Connection, TextElement, WireSpec, IDGenerator)
- `svg_parser.py` - SVG parsing (text, paths, polylines, colored wires)
- `connector_finder.py` - Connector identification, junction handling, "between" logic
- `output_formatter.py` - Markdown export with multiline connector support

**Extractors Package (`extractors/`):**
- `base_extractor.py` - Base class with shared wire spec detection utilities
- `horizontal_wire_extractor.py` - **Primary extractor** for wires with specs (most connections)
- `horizontal_colored_wire_extractor.py` - Colored wires without specs
- `vertical_routing_extractor.py` - Routing polylines, L-shaped paths, rectangular paths
- `ground_connection_extractor.py` - Ground connections (st17 paths)
- `long_routing_connection_extractor.py` - Multi-hop splice connections via color flow
- `grid_wire_extractor.py` - Grid-based diagrams

**Test Files:**
- `sample-wire.svg` - Example circuit diagram
- `test_cases/` - Additional test SVG files with edge cases

## Supported Features

✅ **Pin Formats:**
- Regular pins: `1`, `2`, `3`
- Dash-separated pins: `1-1`, `1-2`, `3-1` (shielded wire diagrams)

✅ **Connector Types:**
- Regular connectors: `MH3202C`, `FL7210`
- Junction connectors: `MH2FL`, `FL2MH`, `FTL2FL`, `FL2FTL`
- Ground connectors: `G22B(m)`, `G404(s)`
- Multiline shielded pairs: `MAIN202 (XR-)\nMAIN642 (XR+)` (displayed with `<br>` in markdown)

✅ **Wire Specs:**
- Standard format: `0.35,BK` (diameter, color)
- Dual-color: `0.5,GY/PU`
- 4-letter colors: `0.5,BUDK`, `0.5,GNDK` (shielded wires)

✅ **Connection Types:**
- Horizontal wires with specs
- Colored horizontal wires (CSS classes st5-st31)
- Vertical routing (polylines, L-shaped paths)
- Rectangular polylines (4-point H-V-H pattern)
- Ground connections
- Long-distance routing via color flow

✅ **Special Cases:**
- Unlabeled splice points (auto-generates `SP_CUSTOM_001`, etc.)
- Optional exclusion config (`exclusions_config.json`)

## Detailed Documentation

For in-depth information, see the `docs/` directory:

- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - Module structure, data structures, extractor classes, inheritance patterns
- **[ALGORITHM_DETAILS.md](docs/ALGORITHM_DETAILS.md)** - All 9 critical design decisions with examples and code
- **[SVG_PATTERNS.md](docs/SVG_PATTERNS.md)** - Text element format, regex patterns, connector assignment logic

## Quick Reference: SVG Patterns

### Connector ID Pattern
```regex
^[A-Z]{2,4}\d{1,5}[A-Z_]{0,5}$
```
Examples: `MH3202C`, `FL7210`, `MH2FL`, `MAIN605`

### Wire Spec Pattern
```regex
^([\d.]+),\s*([A-Z]{2,}(?:/[A-Z]{2,})?)$
```
Examples: `0.35,BN`, `0.5,GY/PU`, `0.5,BUDK`, `6.0,RD`

### Ground Connector Pattern
```regex
^[A-Z]+\d+[A-Z]*\([a-z]\)$
```
Examples: `G22B(m)`, `G404(s)`, `G05(z)`

## Environment

- Windows 11 Pro
- Python 3.x
- Windows Command Terminal
- All necessary tools installed (git bash, github cli)

## For AI Agents

See **[wire-relation-prompt.md](wire-relation-prompt.md)** for a complete prompt capturing all critical knowledge and rules from this project.

---

**Documentation Status:** Lean version (optimized for Claude Code performance)
**Last Updated:** 2025-01 (shielded wire support added)
