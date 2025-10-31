# SVG Patterns and Technical Reference

This document contains technical details about SVG structure patterns, regex patterns, and implementation specifics.

## SVG Structure Patterns

### Text Element Format

Adobe Illustrator exports text with transform matrices:

```xml
<text transform="matrix(1 0 0 1 237.3564 331.6939)" class="st3 st7">MH3202H</text>
```

The last two numbers in the matrix are the X and Y coordinates:
- X = 237.3564
- Y = 331.6939

### Shielded Pair Connector Format

Shielded pair connectors appear as two separate text elements that are merged:

```xml
<!-- Base connector -->
<text transform="matrix(1 0 0 1 757.4992 498.22)" class="st4 st16">MAIN605</text>

<!-- Option label -->
<text transform="matrix(1 0 0 1 803.0493 497.9896)" class="st4 st16">(XR-)</text>
```

**Merging Logic:**
1. **Horizontal merge**: MAIN605 + (XR-) → "MAIN605 (XR-)"
2. **Vertical merge**: Stack XR- and XR+ connectors with newline separator
   - Result: "MAIN605 (XR-)\nMAIN641 (XR+)"
   - Uses average X position of both connectors for positioning

### Colored Wire Segments

Colored wires are represented as `<line>` or `<path>` elements with CSS class:

```xml
<!-- Blue wire -->
<line class="st5" x1="774.9" y1="514.3" x2="619.0" y2="514.3"/>

<!-- Dark blue wire -->
<line class="st6" x1="944.2" y1="514.4" x2="794.5" y2="514.4"/>
```

**Color Mapping (svg_parser.py):**
```python
COLOR_MAP = {
    'st5': 'BU',      # #0000F8 - Blue
    'st6': 'BUDK',    # #083A94 - Blue/Dark blue
    'st7': 'BK',      # #000000 - Black
    'st8': 'GN',      # #00B42B - Green
    # ... st9-st31
}
```

### Routing Path Commands

**SVG Path 'd' Attribute Commands:**
- `M x,y` - Move to absolute position
- `m dx,dy` - Move to relative position
- `L x,y` - Line to absolute position
- `l dx,dy` - Line to relative position
- `H x` - Horizontal line to absolute X
- `h dx` - Horizontal line to relative X
- `V y` - Vertical line to absolute Y
- `v dy` - Vertical line to relative Y
- `c dx1,dy1,dx2,dy2,dx,dy` - Relative cubic Bezier curve
- `C x1,y1,x2,y2,x,y` - Absolute cubic Bezier curve

**L-Shaped Path Detection:**
```python
# Check for vertical commands to identify L-shaped paths
if 'v' in path_d or 'V' in path_d:
    # This is a TRUE L-shaped path
    paths.append(path_d)
```

### Splice Point Dots

Splice points are represented as circles:

```xml
<circle class="st5" cx="829.9" cy="732.2" r="2.8"/>
```

**Recognition:**
- Circles with small radius (typically 2-3 units)
- May or may not have accompanying text labels

## Regex Patterns

### Connector ID Pattern

```regex
^[A-Z]{2,4}\d{1,5}[A-Z_]{0,5}$
```

**Breakdown:**
- `[A-Z]{2,4}` - 2-4 uppercase letters (prefix)
- `\d{1,5}` - 1-5 digits
- `[A-Z_]{0,5}$` - 0-5 uppercase letters or underscores (suffix)

**Examples:**
- `MH3202C` - 2 letters + 4 digits + 1 letter
- `FL7210` - 2 letters + 4 digits
- `MH2FL` - 2 letters + 1 digit + 2 letters (junction)
- `MAIN605` - 4 letters + 3 digits

**Exclusions:**
- `SP*` patterns (splices, not connectors)

**Multiline Connector Pattern (Shielded Pairs):**
```regex
# Single-line with option
^[A-Z]{2,4}\d{1,5}[A-Z_]{0,5}\s+\([A-Z]+[+-]\)$

# Multiline (newline-separated)
# Checked programmatically: split on '\n' and validate each line
```

### Pin Number Pattern

```regex
# Regular pin
^\d+$

# Dash-separated pin (shielded wires)
^\d+-\d+$
```

**Examples:**
- Regular: `1`, `2`, `3`, `19`, `73`
- Dash-separated: `1-1`, `1-2`, `3-1`, `4-2`

### Wire Spec Pattern

```regex
^([\d.]+),\s*([A-Z]{2,}(?:/[A-Z]{2,})?)$
```

**Breakdown:**
- `([\d.]+)` - Capture group 1: wire diameter (digits and decimal point)
- `,\s*` - Comma with optional whitespace
- `([A-Z]{2,}(?:/[A-Z]{2,})?)` - Capture group 2: color code
  - `[A-Z]{2,}` - 2 or more uppercase letters (primary color)
  - `(?:/[A-Z]{2,})?` - Optional: slash + 2 or more letters (secondary color)

**Examples:**
- `0.35,BN` - diameter 0.35mm, brown wire
- `0.5,GY/PU` - diameter 0.5mm, gray/purple wire
- `0.5,BUDK` - diameter 0.5mm, dark blue wire (4 letters)
- `6.0,RD` - diameter 6.0mm, red wire

**Updated Pattern (supports 4-letter colors):**
- Changed from `[A-Z]{2}` to `[A-Z]{2,}` to support BUDK, GNDK, etc.

### Ground Connector Pattern

```regex
^[A-Z]+\d+[A-Z]*\([a-z]\)$
```

**Breakdown:**
- `[A-Z]+` - 1 or more uppercase letters
- `\d+` - 1 or more digits
- `[A-Z]*` - 0 or more uppercase letters
- `\([a-z]\)` - Lowercase letter in parentheses

**Examples:**
- `G22B(m)` - Ground connector with (m) designation
- `G404(s)` - Ground connector with (s) designation
- `G05(z)` - Ground connector with (z) designation

### Splice Point Pattern

```regex
# Labeled splice
^SP\d+$

# Custom-generated splice
^SP_CUSTOM_\d+$
```

**Examples:**
- Labeled: `SP001`, `SP023`, `SP113`, `SP323`
- Custom: `SP_CUSTOM_001`, `SP_CUSTOM_002`, `SP_CUSTOM_009`

## Connector Assignment Logic

```python
def find_connector_above_pin(pin_x, pin_y, text_elements, prefer_as_source=False, source_x=None, destination_x=None):
    """
    Find the closest connector directly above a pin.

    Args:
        pin_x, pin_y: Pin coordinates
        prefer_as_source: If True, prefer FL2* for junctions
                         If False, prefer *2FL for junctions
        source_x: X coordinate of source (for "between" logic when this pin is destination)
        destination_x: X coordinate of destination (for picking junction closer to destination)

    Returns:
        Tuple of (connector_id, x, y) or None
    """
    connectors_above = []

    for elem in text_elements:
        if not is_connector_id(elem.content):
            continue

        x_dist = abs(elem.x - pin_x)
        y_dist = pin_y - elem.y

        # Connector must be above (positive y_dist) and horizontally aligned
        conn_id = elem.content

        # Detect junction pattern
        is_junction = False
        if '2' in conn_id and len(conn_id) >= 5:
            parts = conn_id.split('2', 1)
            if len(parts) == 2 and all(p.isalpha() and 2 <= len(p) <= 3 for p in parts):
                is_junction = True

        max_x_dist = 100 if is_junction else 50

        if x_dist < max_x_dist and y_dist > 5:
            connectors_above.append((y_dist, elem.content, elem.x, elem.y))

    if not connectors_above:
        return None

    # Sort by Euclidean distance
    connectors_with_distance = []
    for y_dist, cid, cx, cy in connectors_above:
        x_dist_from_pin = abs(cx - pin_x)
        euclidean_dist = math.sqrt(y_dist**2 + x_dist_from_pin**2)
        connectors_with_distance.append((euclidean_dist, y_dist, x_dist_from_pin, cid, cx, cy))

    connectors_with_distance.sort(key=lambda c: c[0])

    # Apply "between" logic if source_x provided
    if source_x is not None and not prefer_as_source:
        # ... between logic implementation ...
        pass

    # Get closest connector
    conn_id = connectors_with_distance[0][3]

    # Handle junction preference
    if prefer_as_source:
        # Prefer FL2* pattern (source from junction)
        fl2_variants = [c for c in connectors_with_distance if c[3].startswith('FL2')]
        if fl2_variants:
            conn_id = fl2_variants[0][3]
    else:
        # Prefer *2FL pattern (destination to junction)
        to_fl_variants = [c for c in connectors_with_distance if c[3].endswith('2FL')]
        if to_fl_variants:
            conn_id = to_fl_variants[0][3]

    return (conn_id, connectors_with_distance[0][4], connectors_with_distance[0][5])
```

## Output Format

### Sorted Connection Table

Connections are sorted by:
1. **From connector ID** (alphabetically)
2. **From pin number** (numerically)

This makes it easy to verify all connections for each source connector.

### Grouped by Source Connector

Additional section groups connections by source connector with statistics:

```markdown
### MH3202C (6 connections)

| From Pin | To | To Pin | Wire DM | Color |
|----------|-----|--------|---------|-------|
| 25 | MH2FL | 8 | 0.35 | WH/RD |
| 26 | MH2FL | 9 | 0.35 | BU/BK |
...
```

### Multiline Connector Display

Shielded pair connectors are displayed with HTML `<br>` tags:

```markdown
| From | From Pin | To | To Pin | Wire DM | Color |
|------|----------|-----|--------|---------|-------|
| MAIN641 | 3 | CS02 (XR-)<br>CS42 (XR+) | 2 | 0.5 | BU |
```

This renders as two lines in markdown viewers:
```
CS02 (XR-)
CS42 (XR+)
```

## Vertical Routing and Ground Connections

### Vertical Routing Arrows (st17 Polylines)

**Format:**
```xml
<polyline class="st17" points="718.4,678.9 800.6,678.9 800.6,384.4 781,653 718,653"/>
```

**Parsing:**
```python
points = polyline.get('points').split()
start = points[0]   # First point
end = points[-1]    # Last point

# Parse each point: "x,y"
start_x, start_y = float(start.split(',')[0]), float(start.split(',')[1])
end_x, end_y = float(end.split(',')[0]), float(end.split(',')[1])
```

**Direction Detection:**
- Splice points are ALWAYS destinations
- Otherwise: higher up (smaller Y) = destination

### Ground Connections (st17 Paths)

**Format:**
```xml
<path class="st17" d="M977.9,384.4c-29.2,0,-191.9,0,-217.4,0"/>
```

**Parsing M Command:**
```python
# Extract M command coordinates
match = re.match(r'M([\d.]+),([\d.]+)', path_d)
if match:
    path_x = float(match.group(1))
    path_y = float(match.group(2))
```

**Connection Point Detection:**
- Within ±10 Y units of path
- Within ±120 X units of path (stricter than regular routing)
- Must involve at least one ground connector

## Optional Exclusion Configuration

### File Format (exclusions_config.json)

```json
{
  "description": "Optional exclusion configuration",
  "exclusions": [
    {
      "connector_id": "RRS111",
      "pin": "22",
      "reason": "Reference connection to external diagram"
    }
  ],
  "connection_exclusions": [
    {
      "from_connector": "MAIN42",
      "from_pin": "7",
      "to_connector": "SP_CUSTOM_006",
      "to_pin": "",
      "reason": "False connection, pins on different horizontal wires"
    }
  ]
}
```

### Diagram-Specific Config

The tool supports per-diagram exclusion configs:
- `vertical-intersection.svg` → `vertical-intersection_exclusions.json`
- Falls back to `exclusions_config.json` if diagram-specific config doesn't exist

### Exclusion Types

1. **Pin Exclusions** (`exclusions` array):
   - Excludes ALL connections involving this pin
   - Format: `{connector_id, pin, reason}`

2. **Connection Exclusions** (`connection_exclusions` array):
   - Excludes specific connection pairs
   - Format: `{from_connector, from_pin, to_connector, to_pin, reason}`

## Connection Type Summary

| Type | Element | Wire Specs | Examples |
|------|---------|------------|----------|
| Horizontal wires | Text: wire specs | Yes | FL2MH pin 1 → FL7210 pin 4 (0.35,GY/PU) |
| Colored horizontal wires | `<line>` with CSS class | Optional | MAIN702,1-1 → MAIN605,1 (BUDK) |
| Vertical routing | `<polyline class="st17">` | No | FL7210B pin 3 → SP025 |
| L-shaped routing | `<path class="st3/st4">` with 'v'/'V' | Optional | RRT15,3 → SP323 |
| Rectangular routing | 4-point H-V-H polyline | Yes | MAIN14,1 → G203B(m) (4.0, BK) |
| Ground connections | `<path class="st17">` | Optional | MH2FL pin 73 → G22B(m) |
| Long routing | Color flow tracing | No | Multi-hop splice connections |
