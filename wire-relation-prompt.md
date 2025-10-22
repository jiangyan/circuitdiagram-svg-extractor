# AI Prompt: Circuit Diagram Wire Connection Extraction

## Problem Statement

You are tasked with extracting wire connections from a circuit diagram SVG file exported from Adobe Illustrator. The SVG contains:
- Connector IDs (e.g., MH3202C, FL7210)
- Pin numbers (e.g., 25, 51)
- Wire specifications (e.g., 0.35,GY/PU - diameter and color)
- Horizontal lines representing wires connecting pins

Your goal is to produce a complete table of connections in the format:

```
From Connector | From Pin | To Connector | To Pin | Wire Diameter | Wire Color
```

## Critical: Use the Wire-Centric Algorithm

### ✓ DO: Wire-Centric Approach

**Start from the wires, not the connectors.**

```
For each wire specification in the SVG:
    1. Find all pins on the same horizontal line (±10 Y units)
    2. Identify pins on left side of wire spec (source pins)
    3. Identify pins on right side of wire spec (destination pins)
    4. Take the closest pin on each side
    5. For each pin, find the connector directly above it
    6. Create connection: (left_connector, left_pin) → (right_connector, right_pin)
```

### ❌ DON'T: Pin-Centric or Boundary-Based Approaches

**Do NOT try to:**
- Assign pins to connectors based on spatial proximity first
- Use boundaries or regions to group pins
- Assume pins are located immediately below their connector labels
- Use fixed distance thresholds to determine ownership

**Why these fail:**
- Pins can be located far below their connector labels
- Pins may be past other connector labels in the vertical column
- Multiple connector instances of the same type exist
- Connectors of different types are interleaved

## SVG Structure You Must Understand

### Text Element Coordinates

Adobe Illustrator exports text with transform matrices:

```xml
<text transform="matrix(1 0 0 1 237.3564 331.6939)">MH3202H</text>
```

**Extract coordinates from the last two numbers:**
- X = 237.3564
- Y = 331.6939

### Connector ID Pattern

Match this regex: `^[A-Z]{2,3}\d{1,5}[A-Z]{0,3}$`

**Valid examples:**
- `MH3202C` - Regular connector
- `FL7210` - Regular connector
- `MH2FL` - Junction connector (special handling required)
- `FL2MH` - Junction connector (special handling required)

**Exclude:**
- `SP*` patterns (these are splices, not connectors)

### Wire Specification Pattern

Match this regex: `^([\d.]+),([A-Z]{2}(?:/[A-Z]{2})?)$`

**Examples:**
- `0.35,BN` - 0.35mm diameter, brown wire
- `0.5,GY/PU` - 0.5mm diameter, gray/purple wire
- `0.75,GN/RD` - 0.75mm diameter, green/red wire

### Pin Pattern

**Simple rule:** Any numeric text that doesn't match wire specs

**Examples:** `1`, `25`, `51`, `73`

## Critical Parameters (DO NOT CHANGE)

### Y-Axis Tolerance: ±10 Units

When finding pins on the same horizontal line as a wire spec:

```python
if abs(pin_y - wire_spec_y) < 10:
    # Pin is on the same row as this wire
```

**Why ±10, not more:**
- ±20 is TOO LARGE: Groups pins from different wire rows
- Example: Pin at Y=611.17 and pin at Y=586.38 are 24.8 units apart
- If tolerance is ±20, wire at Y=604.9 matches BOTH pins → wrong connection
- ±10 prevents this while handling minor SVG rendering variations

**Why ±10, not less:**
- ±5 is too strict: Misses valid pins due to Adobe Illustrator rounding
- SVG text rendering may have sub-pixel variations

### X-Axis Threshold for Connector Lookup

When finding connector above a pin:

```python
if connector_type == "junction":  # MH2FL, FL2MH, etc.
    max_x_distance = 100
else:
    max_x_distance = 50
```

**Why these values:**
- Regular connectors have pins in a tight vertical column
- Junction connectors span wider areas and share pins

### Minimum Y-Distance: 5 Units

Connector must be at least 5 units above the pin:

```python
if pin_y - connector_y > 5:
    # Connector is above the pin (valid)
```

## Junction Connector Handling (CRITICAL)

### The Problem

Circuit diagrams use bidirectional junction connectors that share the same pins:

- `MH2FL` ↔ `FL2MH` (same physical location, same pins)
- `FTL2FL` ↔ `FL2FTL` (same physical location, same pins)

### The Rule

**Junction connectors have direction semantics:**

- **`*2FL` variants (MH2FL, FTL2FL)** = **DESTINATIONS ONLY**
  - Wires come IN to these junctions
  - Never use as "from" connector

- **`FL2*` variants (FL2MH, FL2FTL)** = **SOURCES ONLY**
  - Wires go OUT from these junctions
  - Never use as "to" connector

### Implementation

```python
def find_connector_above_pin(pin_x, pin_y, text_elements, prefer_as_source=False):
    # Find all connectors above the pin
    connectors_above = [...]

    # Get the closest connector
    closest = connectors_above[0]

    # Check if there are junction variants
    junction_candidates = [c for c in connectors_above
                          if '2FL' in c.id or 'FL2' in c.id]

    if junction_candidates:
        if prefer_as_source:
            # For left pin (source), prefer FL2* variants
            fl2_variants = [c for c in junction_candidates
                           if c.id.startswith('FL2')]
            if fl2_variants:
                return fl2_variants[0]
        else:
            # For right pin (destination), prefer *2FL variants
            to_fl_variants = [c for c in junction_candidates
                             if c.id.endswith('2FL')]
            if to_fl_variants:
                return to_fl_variants[0]

    return closest
```

### When Processing Each Wire

```python
# Left pin is the SOURCE - prefer FL2* for junctions
left_connector = find_connector_above_pin(
    left_pin_x, left_pin_y,
    text_elements,
    prefer_as_source=True  # ← Important!
)

# Right pin is the DESTINATION - prefer *2FL for junctions
right_connector = find_connector_above_pin(
    right_pin_x, right_pin_y,
    text_elements,
    prefer_as_source=False  # ← Important!
)
```

### Example of Correct Junction Handling

**Correct wire chain:**
```
MH3203D pin 7 → MH2FL pin 71    (ends at MH2FL destination)
FL2MH pin 71 → FTL2FL pin 20    (starts from FL2MH source)
FL2FTL pin 20 → FTL5651 pin 1   (starts from FL2FTL source)
```

**Incorrect (without junction rules):**
```
❌ MH3203D pin 7 → MH2FL pin 71
❌ MH2FL pin 71 → FTL2FL pin 20   (MH2FL should never be a source!)
```

## Deduplication (Important)

Some wire specifications appear multiple times on the same row (overlapping wires). Track processed pin pairs:

```python
seen_pin_pairs = set()

for each wire_spec:
    # ... find left_pin, right_pin, connectors ...

    # Create order-independent key
    pin_pair_key = tuple(sorted([
        (left_connector.id, left_pin.number, left_pin.x, left_pin.y),
        (right_connector.id, right_pin.number, right_pin.x, right_pin.y)
    ]))

    if pin_pair_key not in seen_pin_pairs:
        connections.append(connection)
        seen_pin_pairs.add(pin_pair_key)
```

## Step-by-Step Algorithm

```python
def extract_connections(svg_file):
    # Step 1: Parse all text elements
    text_elements = parse_svg_text_elements(svg_file)

    # Step 2: Identify wire specifications
    wire_specs = [e for e in text_elements
                  if matches_wire_pattern(e.content)]

    # Step 3: Process each wire
    connections = []
    seen_pin_pairs = set()

    for wire_spec in wire_specs:
        # Step 4: Find pins on the same horizontal line
        pins_on_line = [p for p in text_elements
                       if p.content.isdigit()
                       and abs(p.y - wire_spec.y) < 10]  # ±10 Y tolerance

        if len(pins_on_line) < 2:
            continue  # Need at least 2 pins

        # Step 5: Find closest pin on each side of wire
        left_pin = max([p for p in pins_on_line if p.x < wire_spec.x],
                      key=lambda p: p.x, default=None)
        right_pin = min([p for p in pins_on_line if p.x > wire_spec.x],
                       key=lambda p: p.x, default=None)

        if not left_pin or not right_pin:
            continue

        # Step 6: Find connectors above each pin
        left_connector = find_connector_above_pin(
            left_pin.x, left_pin.y, text_elements,
            prefer_as_source=True   # Prefer FL2* for junctions
        )
        right_connector = find_connector_above_pin(
            right_pin.x, right_pin.y, text_elements,
            prefer_as_source=False  # Prefer *2FL for junctions
        )

        if not left_connector or not right_connector:
            continue

        # Step 7: Deduplicate
        pin_pair_key = tuple(sorted([
            (left_connector.id, left_pin.number, left_pin.x, left_pin.y),
            (right_connector.id, right_pin.number, right_pin.x, right_pin.y)
        ]))

        if pin_pair_key in seen_pin_pairs:
            continue

        seen_pin_pairs.add(pin_pair_key)

        # Step 8: Create connection
        connections.append({
            'from_id': left_connector.id,
            'from_pin': left_pin.number,
            'to_id': right_connector.id,
            'to_pin': right_pin.number,
            'wire_dm': wire_spec.diameter,
            'wire_color': wire_spec.color
        })

    return connections
```

## Output Format

Sort connections by:
1. From connector ID (alphabetically)
2. From pin number (numerically)

```markdown
| From | From Pin | To | To Pin | Wire DM | Color |
|------|----------|-----|--------|---------|-------|
| FL2MH | 1 | FL7210 | 4 | 0.35 | GY/PU |
| FL2MH | 2 | FL7210 | 6 | 0.35 | BK/GN |
| MH3202C | 25 | MH2FL | 8 | 0.35 | WH/RD |
| MH3202C | 26 | MH2FL | 9 | 0.35 | BU/BK |
| MH3202E | 8 | MH2FL | 6 | 0.35 | GN/WH |
```

## Common Mistakes to Avoid

### ❌ Mistake 1: Using Connector Boundaries

```python
# WRONG: Trying to assign pins based on regions
for connector in connectors:
    boundary = (connector.y + next_connector.y) / 2
    connector.pins = [p for p in pins if p.y < boundary]
```

**Why it fails:** Pins can be located past other connector labels.

### ❌ Mistake 2: "Closest Connector Wins"

```python
# WRONG: Assigning pin to nearest connector
closest_connector = min(connectors,
                       key=lambda c: distance(c, pin))
```

**Why it fails:** Ignores junction semantics and connector types.

### ❌ Mistake 3: Large Y-Tolerance

```python
# WRONG: ±20 or ±30 tolerance
pins_on_line = [p for p in pins
               if abs(p.y - wire.y) < 20]  # TOO LARGE!
```

**Why it fails:** Groups pins from different wire rows together.

### ❌ Mistake 4: Ignoring Junction Direction

```python
# WRONG: Using MH2FL as source
connection = {
    'from': 'MH2FL',      # ← MH2FL should only be destination!
    'from_pin': '71',
    'to': 'FTL2FL',
    ...
}
```

**Why it fails:** Violates junction semantics, creates invalid wire chains.

## Validation Checks

After extraction, verify:

1. **No `*2FL` variants as sources:**
   ```python
   assert all(not conn['from_id'].endswith('2FL')
              for conn in connections)
   ```

2. **No `FL2*` variants as destinations:**
   ```python
   assert all(not conn['to_id'].startswith('FL2')
              for conn in connections)
   ```

3. **All pins have numeric content:**
   ```python
   assert all(conn['from_pin'].isdigit() and
              conn['to_pin'].isdigit()
              for conn in connections)
   ```

4. **Wire specs match pattern:**
   ```python
   assert all(re.match(r'^[\d.]+,[A-Z]{2}(?:/[A-Z]{2})?$',
                       f"{conn['wire_dm']},{conn['wire_color']}")
              for conn in connections)
   ```

## Vertical Routing Connections (st17 Polylines)

### Problem: Not All Connections Have Wire Specs

Some connections use vertical routing arrows instead of horizontal wires with specifications. These are encoded as `<polyline class="st17">` elements in the SVG.

### SVG Structure

```xml
<polyline class="st17" points="841,119 924.6,119 924.6,382.8"/>
```

This represents an L-shaped routing arrow connecting two points.

### Algorithm for Vertical Routing

```python
def extract_vertical_routing_connections(svg_file, text_elements):
    # Find all st17 polyline elements
    polylines = root.findall('.//{http://www.w3.org/2000/svg}polyline[@class="st17"]')

    for polyline in polylines:
        # Parse points: "x1,y1 x2,y2 x3,y3 ..."
        points_str = polyline.get('points', '').strip().split()
        if len(points_str) < 2:
            continue

        # Extract first and last points
        first_point = points_str[0].split(',')
        last_point = points_str[-1].split(',')
        start_x, start_y = float(first_point[0]), float(first_point[1])
        end_x, end_y = float(last_point[0]), float(last_point[1])

        # Find nearest connection point to each endpoint (within 100 units)
        endpoint1 = find_nearest_connection_point(start_x, start_y, text_elements)
        endpoint2 = find_nearest_connection_point(end_x, end_y, text_elements)

        if not endpoint1 or not endpoint2:
            continue

        # Determine direction: splice points (SP*) are ALWAYS destinations
        ep1_is_splice = is_splice_point(endpoint1.connector_id)
        ep2_is_splice = is_splice_point(endpoint2.connector_id)

        if ep1_is_splice and not ep2_is_splice:
            source, dest = endpoint2, endpoint1  # Pin → Splice
        elif ep2_is_splice and not ep1_is_splice:
            source, dest = endpoint1, endpoint2  # Pin → Splice
        else:
            # Neither or both are splices - use Y coordinate
            # Lower Y value = higher up = destination
            if start_y > end_y:
                source, dest = endpoint1, endpoint2
            else:
                source, dest = endpoint2, endpoint1

        # Create connection (no wire specs for vertical routing)
        connections.append({
            'from_id': source.connector_id,
            'from_pin': source.pin,
            'to_id': dest.connector_id,
            'to_pin': dest.pin,
            'wire_dm': '',
            'wire_color': ''
        })
```

### Helper Function: Find Nearest Connection Point

```python
def find_nearest_connection_point(target_x, target_y, text_elements, max_distance=100):
    """
    Find the nearest pin or splice point to a target coordinate.
    Used for vertical routing where polyline endpoints may not exactly align.
    """
    import math

    nearest = None
    min_distance = float('inf')

    for elem in text_elements:
        # Check for pin numbers (digits) or splice points (SP*)
        if elem['content'].isdigit() or is_splice_point(elem['content']):
            dist = math.sqrt((elem['x'] - target_x)**2 + (elem['y'] - target_y)**2)

            if dist < max_distance and dist < min_distance:
                min_distance = dist

                if is_splice_point(elem['content']):
                    # It's a splice point
                    nearest = ConnectionPoint(elem['content'], '', elem['x'], elem['y'])
                else:
                    # It's a pin - find the connector above it
                    connector = find_connector_above_pin(elem['x'], elem['y'], text_elements)
                    if connector:
                        nearest = ConnectionPoint(connector, elem['content'], elem['x'], elem['y'])

    return nearest
```

### Multi-Segment Polylines (CRITICAL)

Some polylines have more than 2 points and connect **multiple pins to one splice**:

```xml
<!-- 5-point polyline: FL7611 pin 1 and pin 9 both connect to SP025 -->
<polyline class="st17" points="718.4,678.9 800.6,678.9 800.6,384.4 781,653 718,653"/>
```

**Detection and handling:**

```python
# If both endpoints are pins (not splices) AND there are intermediate points
if len(points_str) > 2 and not ep1_is_splice and not ep2_is_splice:
    # Check intermediate points for splice points
    for i in range(1, len(points_str) - 1):  # Skip first and last
        point = points_str[i].split(',')
        px, py = float(point[0]), float(point[1])
        intermediate = find_nearest_connection_point(px, py, text_elements)

        if intermediate and is_splice_point(intermediate.connector_id):
            # Found splice in the middle - create TWO connections:
            # Connection 1: endpoint1 → splice
            # Connection 2: endpoint2 → splice
            connections.append(create_connection(endpoint1, intermediate))
            connections.append(create_connection(endpoint2, intermediate))
            break  # Skip normal single-connection logic
```

**Example:** FL7611 pin 1 → SP025 and FL7611 pin 9 → SP025

## Ground Connections (st17 Paths)

### Problem: Ground Symbols Use Path Elements

Ground connections (e.g., to symbols like `G22B(m)`) use `<path class="st17">` elements as arrowheads, not polylines.

### Ground Connector Pattern

Ground connectors are identified by parentheses containing a lowercase letter:

```regex
^[A-Z]+\d+[A-Z]*\([a-z]\)$
```

**Examples:**
- `G22B(m)` - Ground point (m)
- `G05(z)` - Ground point (z)

### SVG Structure

```xml
<path class="st17" d="M977.9,384.4c-29.2,0,-191.9,0,-217.4,0h-28.9c-3.1,0,-6.8,0,-10.8,0"/>
<text transform="matrix(1 0 0 1 1088.4135 382.4229)">G22B(m)</text>
```

### Algorithm for Ground Connections

```python
def extract_ground_connections(svg_file, text_elements):
    # Find all st17 path elements
    paths = root.findall('.//{http://www.w3.org/2000/svg}path[@class="st17"]')

    for path in paths:
        d_attr = path.get('d', '')
        if not d_attr:
            continue

        # Parse M command to get arrow location
        m_match = re.match(r'M([\d.]+),([\d.]+)', d_attr)
        if not m_match:
            continue

        path_x, path_y = float(m_match.group(1)), float(m_match.group(2))

        # Find all connection points on the same horizontal line
        # Within ±10 Y units AND ±200 X units of arrow
        connection_points = []

        for elem in text_elements:
            is_connection_point = (elem['content'].isdigit() or
                                 is_splice_point(elem['content']) or
                                 is_connector_id(elem['content']))
            if is_connection_point:
                y_dist = abs(elem['y'] - path_y)
                x_dist = abs(elem['x'] - path_x)

                # Must be on same horizontal line AND reasonably close
                if y_dist < 10 and x_dist < 200:
                    if elem['content'].isdigit():
                        # Pin: find connector above (prefer *2FL for ground)
                        connector = find_connector_above_pin_for_ground(
                            elem['x'], elem['y'], text_elements
                        )
                        if connector:
                            connection_points.append((elem['x'], connector, elem['content']))
                    elif is_connector_id(elem['content']):
                        # Ground connector or splice
                        connection_points.append((elem['x'], elem['content'], ''))

        # Filter: only create connection if one endpoint is a GROUND connector
        has_ground = any('(' in p[1] for p in connection_points)
        if not has_ground:
            continue  # Skip - this is regular routing handled elsewhere

        # Find the pair with maximum X distance
        if len(connection_points) >= 2:
            connection_points.sort(key=lambda p: p[0])  # Sort by X
            max_dist = 0
            best_pair = None

            for i in range(len(connection_points)):
                for j in range(i + 1, len(connection_points)):
                    p1, p2 = connection_points[i], connection_points[j]
                    dist = abs(p2[0] - p1[0])

                    # Check if one is ground
                    is_ground = ('(' in p1[1]) or ('(' in p2[1])

                    if dist > max_dist and is_ground:
                        max_dist = dist
                        best_pair = (p1, p2)

            if best_pair:
                left, right = best_pair
                connections.append({
                    'from_id': left[1],
                    'from_pin': left[2],
                    'to_id': right[1],
                    'to_pin': right[2],
                    'wire_dm': '',
                    'wire_color': ''
                })
```

### CRITICAL: Junction Connector Selection for Ground

When a pin is shared by junction connectors (e.g., both FL2MH and MH2FL are above pin 73), **ground connections must prefer the `*2FL` variant**:

```python
def find_connector_above_pin_for_ground(pin_x, pin_y, text_elements):
    """
    Find connector above pin, preferring *2FL variants for ground connections.
    """
    connectors_above = []

    for elem in text_elements:
        if is_connector_id(elem['content']):
            x_dist = abs(elem['x'] - pin_x)
            y_dist = pin_y - elem['y']

            is_junction = ('2FL' in elem['content'] or 'FL2' in elem['content'])
            max_x_dist = 100 if is_junction else 50

            if x_dist < max_x_dist and y_dist > 5:
                connectors_above.append((y_dist, elem['content'], elem['x'], elem['y']))

    if not connectors_above:
        return None

    connectors_above.sort(key=lambda c: c[0])  # Sort by Y distance

    # CRITICAL: Prefer *2FL pattern (MH2FL, FTL2FL) for ground connections
    to_fl_variants = [c for c in connectors_above if c[1].endswith('2FL')]
    if to_fl_variants:
        return to_fl_variants[0][1]  # Return MH2FL instead of FL2MH

    # Fall back to closest connector
    return connectors_above[0][1]
```

**Example:**
- Pin 73 is below both FL2MH (X=969.8) and MH2FL (X=995.4)
- Ground wire connects to the right side of the junction
- **Correct:** MH2FL pin 73 → G22B(m)
- **Incorrect:** FL2MH pin 73 → G22B(m)

**Why:** Ground wires come from the destination/input side of junction connectors (*2FL pattern).

### Deduplication for Vertical/Ground Connections

Multiple st17 path arrows may point to the same connection. Deduplicate at the end:

```python
# After extracting all vertical routing connections
seen = set()
unique_connections = []
for conn in vertical_connections:
    key = (conn['from_id'], conn['from_pin'], conn['to_id'], conn['to_pin'])
    if key not in seen:
        seen.add(key)
        unique_connections.append(conn)
```

## Connection Type Summary

Your final output should include THREE types of connections:

| Type | Element | Direction Rule | Wire Specs |
|------|---------|----------------|------------|
| Horizontal wires | Text: wire specs | Wire-centric algorithm | Yes (0.35,GY/PU) |
| Vertical routing | `<polyline class="st17">` | Splice = destination | No |
| Ground connections | `<path class="st17">` | Ground = destination, prefer *2FL | No |

**Example Output:**

```markdown
| From | From Pin | To | To Pin | Wire DM | Color |
|------|----------|-----|--------|---------|-------|
| FL2MH | 1 | FL7210 | 4 | 0.35 | GY/PU |        ← Horizontal wire
| FL7210B | 3 | SP025 |  |  |  |                   ← Vertical routing
| MH2FL | 73 | G22B(m) |  |  |  |                  ← Ground connection
```

## Validation Checks (Updated)

After extraction, verify:

1. **No `*2FL` variants as sources (horizontal wires only):**
   ```python
   horizontal_conns = [c for c in connections if c['wire_dm']]
   assert all(not conn['from_id'].endswith('2FL')
              for conn in horizontal_conns)
   ```

2. **No `FL2*` variants as destinations (horizontal wires only):**
   ```python
   assert all(not conn['to_id'].startswith('FL2')
              for conn in horizontal_conns)
   ```

3. **Ground connectors only appear as destinations:**
   ```python
   ground_conns = [c for c in connections if '(' in c['to_id']]
   assert all('(' not in conn['from_id'] for conn in ground_conns)
   ```

4. **Splice points appear as destinations in vertical routing:**
   ```python
   vertical_conns = [c for c in connections if not c['wire_dm']]
   assert all(not is_splice_point(conn['from_id'])
              for conn in vertical_conns)
   ```

## Summary: The Golden Rules

1. **Wire-centric, not connector-centric** (for horizontal wires)
2. **±10 Y-axis tolerance for horizontal alignment**
3. **Junction direction matters: `*2FL` = destinations, `FL2*` = sources**
4. **Find connector directly above pin, not closest overall**
5. **Deduplicate pin pairs to handle overlapping wires**
6. **Vertical routing: splice points are always destinations**
7. **Ground connections: prefer `*2FL` junction variants**
8. **Multi-segment polylines: check intermediate points for splices**
9. **st17 paths are ground arrowheads, only create if ground connector present**
10. **Sort output by connector ID, then pin number**

Follow these rules exactly, and you will extract accurate wire connections from circuit diagram SVGs.
