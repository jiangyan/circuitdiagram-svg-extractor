# Algorithm Details: Critical Design Decisions

This document contains all 9 critical design decisions that make the wire extraction algorithm work correctly.

## Core Algorithm: Wire-Centric Approach

### The Key Insight

Instead of trying to assign pins to connectors using spatial boundaries, we **start from the wires** and work outward:

1. **Find all wire specifications** (e.g., "0.35,GY/PU")
2. **For each wire, find the pins on both ends** of the horizontal line
3. **For each pin, look up which connector is directly above it**

This approach avoids the complexity of:
- Determining which pins "belong" to which connector when pins are far below labels
- Handling multiple connector instances of the same type
- Dealing with interleaved connectors of different types

### Algorithm Steps

```
For each wire specification in the SVG:
    1. Find all pins on the same horizontal line (±10 Y units)
    2. Identify the leftmost pin right of wire spec (source)
    3. Identify the rightmost pin left of wire spec (destination)
    4. For left pin: find closest connector above (prefer FL2* variants for junctions)
    5. For right pin: find closest connector above (prefer *2FL variants for junctions)
    6. Create connection: (left_connector, left_pin) → (right_connector, right_pin)
    7. Skip if this pin-pair already processed (deduplication)
```

## 1. Wire-Centric vs Pin-Centric

**❌ Pin-Centric (Failed Approach):**
- Try to assign pins to connectors based on spatial proximity
- Problem: Pins can be located far below their connector, past other connector labels
- Problem: Boundary-based approaches fail when connectors are interleaved

**✓ Wire-Centric (Successful Approach):**
- Let the wires dictate the connections
- Simple rule: find the connector directly above each pin
- No boundaries, no complex spatial logic

## 2. Y-Axis Tolerance: ±10 Units

**Why this matters:**
- Wire specifications and pins must be on the same horizontal row
- Too large (±20): Groups pins from different rows → wrong connections
- Too small (±5): Misses valid pins due to SVG rendering variations
- **±10 units** is the sweet spot for Adobe Illustrator SVG exports

**Example of the problem at ±20:**
```
Pin 25 at Y=611.17  }  24.8 units apart
Pin 8  at Y=586.38  }  ← Both matched to wire at Y=604.9
→ Algorithm picks pin 8 (closer horizontally) instead of pin 25
```

## 3. Junction Connector Handling

Circuit diagrams use bidirectional junction connectors that share pins:

**Junction Pairs:**
- `MH2FL` ↔ `FL2MH` (Main to Front-Left junction)
- `FTL2FL` ↔ `FL2FTL` (Front-To-Left junction)

**Rule:**
- `*2FL` variants = **destinations** (wires coming IN to junction)
- `FL2*` variants = **sources** (wires going OUT of junction)

**Implementation:**
```python
# For left pin (source): prefer FL2* variants
left_conn = find_connector_above_pin(left_pin_x, left_pin_y,
                                      prefer_as_source=True)

# For right pin (destination): prefer *2FL variants
right_conn = find_connector_above_pin(right_pin_x, right_pin_y,
                                       prefer_as_source=False)
```

**Why this matters:**
Without this rule, you get invalid chains like:
```
❌ MH3203D → MH2FL (stops)
❌ MH2FL → FTL2FL (MH2FL shouldn't be a source!)
```

With the rule:
```
✓ MH3203D → MH2FL (ends at junction)
✓ FL2MH → FTL2FL (continues from junction)
✓ FL2FTL → FTL5651 (continues from junction)
```

## 4. Pin Deduplication

Some wire specifications appear multiple times on the same row (e.g., overlapping dual-color wires). To avoid duplicate connections:

```python
# Create order-independent key for pin pair
pin_pair_key = tuple(sorted([
    (left_connector, left_pin, left_x, left_y),
    (right_connector, right_pin, right_x, right_y)
]))

if pin_pair_key not in seen_pin_pairs:
    connections.append(connection)
    seen_pin_pairs.add(pin_pair_key)
```

## 5. Unlabeled Splice Point Handling

**Edge Case:** Some diagrams contain splice point dots without accompanying labels (no SP001, SP023, etc.).

**Solution:** Automatically generate custom IDs for unlabeled splice dots.

**Implementation:**

```python
from models import IDGenerator

# 1. Initialize ID generator
id_generator = IDGenerator()

# 2. After mapping labeled splices to dots, identify unlabeled dots
text_elements = map_splice_positions_to_dots(text_elements, splice_dots)
text_elements = generate_ids_for_unlabeled_splices(text_elements, splice_dots, id_generator)

# 3. IDGenerator creates unique IDs: SP_CUSTOM_001, SP_CUSTOM_002, ...
```

**Detection Logic:**

```python
def generate_ids_for_unlabeled_splices(text_elements, dots, id_generator, max_distance=5):
    """Generate custom IDs for splice dots that don't have labels."""

    # Collect positions of all labeled splices
    labeled_positions = [(elem.x, elem.y) for elem in text_elements if is_splice_point(elem.content)]

    # Find dots without nearby labels (within 5 units)
    unlabeled_dots = []
    for dot_x, dot_y in dots:
        has_label = any(
            math.sqrt((dot_x - lx)**2 + (dot_y - ly)**2) < max_distance
            for lx, ly in labeled_positions
        )
        if not has_label:
            unlabeled_dots.append((dot_x, dot_y))

    # Generate custom IDs
    for dot_x, dot_y in unlabeled_dots:
        custom_id = id_generator.get_or_create_splice_id(dot_x, dot_y)
        text_elements.append(TextElement(custom_id, dot_x, dot_y))

    return text_elements
```

**Recognition:**

Custom splice IDs are recognized by `is_splice_point()`:

```python
def is_splice_point(text: str) -> bool:
    """Check if text is a splice point ID (SP001 or SP_CUSTOM_001)."""
    if re.match(r'^SP\d+$', text):  # Labeled: SP001
        return True
    if text.startswith('SP_CUSTOM_'):  # Custom: SP_CUSTOM_001
        return True
    return False
```

**Example:**

Edge case file: `test_cases/splicepoints-has-no-id.svg`
- Circuit diagram with 37 unique connectors
- Only 9 unlabeled splice dots (out of 12 total dots)
- Generated 9 custom IDs (SP_CUSTOM_001 to SP_CUSTOM_009)
- Result: 87 connections

**Why This Matters:**

- Some circuit diagrams omit splice point labels to reduce clutter
- Without auto-generation, connections to unlabeled splices would be lost
- Custom IDs ensure complete extraction while maintaining traceability

## 6. Shared Pin Connector Selection ("Between" Logic)

**Edge Case:** Multiple connectors positioned above the same physical pin.

**Problem:**
```
Wire: MH097 pin 7 ---[2.5,YE/BU]---> pin 1
Connectors above pin 1:
  - MH020 at X=317.8 (LEFT of pin, at end of yellow wire)
  - RRS100 at X=343.1 (RIGHT of pin, at start of red wire)
```

Without proper logic, algorithm picks **RRS100** (closest to pin, only 0.7 units away) instead of **MH020** (24.6 units away).

**Solution:** Prefer connectors **BETWEEN** wire spec and pin.

**Implementation:**

```python
def find_connector_above_pin(pin_x, pin_y, text_elements, prefer_as_source=False, source_x=None):
    """Find connector above pin, preferring those between source and pin."""

    # ... find all connectors above pin ...

    # CRITICAL: If source_x provided, prefer connectors BETWEEN source and pin
    if source_x is not None and not prefer_as_source:
        between_connectors = []
        other_connectors = []

        for conn in connectors_with_distance:
            cx = conn[4]  # connector X position

            # Check if connector is between source_x and pin_x
            if source_x < pin_x:
                is_between = source_x < cx < pin_x
            else:
                is_between = pin_x < cx < source_x

            if is_between:
                between_connectors.append(conn)
            else:
                other_connectors.append(conn)

        # Prioritize connectors between source and pin
        if between_connectors:
            connectors_with_distance = between_connectors + other_connectors

    # Return closest connector (now prioritizing "between" connectors)
    return connectors_with_distance[0]
```

**Example:**

Wire spec at X=243.9, pin at X=342.4:
- MH020 at X=317.8 → **BETWEEN** (243.9 < 317.8 < 342.4) ✓
- RRS100 at X=343.1 → **NOT BETWEEN** (343.1 > 342.4) ✗

Result: **MH020** is chosen (correct!)

**Why This Matters:**

- Shared pins are common at connector boundaries
- Picking the wrong connector breaks wire tracing
- "Between" logic ensures we follow the physical wire path

**Critical Configuration:**

The "between" logic has a Y-distance threshold to prevent distant connectors from being prioritized just because they happen to be between in X:

```python
# Only prioritize "between" connectors if they're reasonably close in Y
# Use a threshold of 60 Y-units as "reasonable" vertical distance
if is_between and y_dist < 60:
    between_connectors.append(conn)
```

Initially set to 50 units, this was increased to 60 units after discovering that valid "between" connectors at Y-distance=52.4 were being excluded.

## 6a. Wire Spec Selection for Groups with Multiple Y Positions

**Edge Case:** Multiple wire specs grouped together (round(Y/10)*10) can have significantly different Y positions, causing connection points to be missed.

**Problem:**
```
Group 110 contains 3 wire specs:
  - 1.5,YE/GN at Y=106.7
  - 2.5,RD/WH at Y=111.9
  - 2.5,YE at Y=112.1

If algorithm uses specs_on_line[0].y (106.7) to find pins within ±10:
  - Matches pins at Y=112-116 ✓
  - MISSES pins at Y=118 ✗ (118 > 106.7+10)

Result: Valid connections involving pins at Y=118 are not created!
```

**Root Cause:** The original implementation used `specs_on_line[0].y` as the reference Y position for finding connection points. When the first spec in a group had a significantly different Y than other specs, pins near the other specs would not be matched.

**Solution:** Check if connection points are within ±10 of **ANY** spec in the group, not just the first one.

**Implementation:**

```python
# BEFORE (WRONG):
for elem in self.text_elements:
    if abs(elem.y - specs_on_line[0].y) < 10:  # Only checks first spec!
        if elem.content.isdigit() or is_splice_point(elem.content):
            connection_points.append(elem)

# AFTER (CORRECT):
for elem in self.text_elements:
    if elem.content.isdigit() or is_splice_point(elem.content):
        for spec in specs_on_line:  # Check ALL specs in group
            if abs(elem.y - spec.y) < 10:
                connection_points.append(elem)
                break  # Don't add same element multiple times
```

**Wire Spec Selection Logic:**

Once all connection points are found, select the wire spec **closest in Y-distance to the average pin position**:

```python
# Calculate average Y position of all connection points
avg_pin_y = sum(p.y for p in connection_points) / len(connection_points)

# Select the wire spec closest in Y to the average
wire_spec = min(specs_on_line, key=lambda s: abs(s.y - avg_pin_y))
```

This implements the principle that **wire specs are positioned directly above the wires they describe**.

**Example:**

```
Group 110 specs:
  - 1.5,YE/GN at Y=106.7
  - 2.5,RD/WH at Y=111.9
  - 2.5,YE at Y=112.1

Connection points found: pins at Y=112.2, 112.3, 112.5, 117.9, 118.2, 118.4
Average pin Y: 115.2

Y-distances from average:
  - 1.5,YE/GN: |106.7 - 115.2| = 8.5 units
  - 2.5,RD/WH: |111.9 - 115.2| = 3.3 units
  - 2.5,YE: |112.1 - 115.2| = 3.1 units ✓ SELECTED

Result: Connections use 2.5,YE (the spec closest to the pins)
```

**Why This Matters:**

- Prevents missing valid connections when wire specs have varying Y positions
- Ensures the correct wire spec is used (closest to actual pins, not arbitrary first spec)
- Respects the physical layout principle that specs are positioned above their wires

**Real-World Impact:**

This fix resolved MH097,12 → MH020,17 showing wrong wire spec (1.5,RD/YE instead of 2.5,YE) and discovered a previously missed valid connection (RRS113,11 → RRS112,4 with 2.5,YE).

## 7. L-Shaped Routing Wires (st3/st4 Path Filtering)

**Edge Case:** Some circuit diagrams use L-shaped routing wires (vertical + horizontal segments) encoded as `<path class="st3">` or `<path class="st4">` elements.

**Problem:**
```
st3 paths can represent TWO types of connections:
1. TRUE L-shaped wires (vertical routing with 'v' or 'V' commands)
2. Horizontal-only wires (using 'c' curve commands without vertical segments)

Type 2 creates DUPLICATE connections already captured by wire specs!
```

**Solution:** Smart filtering - only parse st3/st4 paths with vertical segments.

**Implementation:**

```python
def parse_routing_paths(svg_file: str, only_l_shaped: bool = True) -> List[str]:
    """
    Parse routing path elements, optionally filtering for L-shaped paths.

    Args:
        svg_file: Path to SVG file
        only_l_shaped: If True, only return paths with vertical segments (v/V commands)
                      to filter out horizontal-only paths that duplicate wire specs
    """
    paths = []

    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        cls = path.get('class', '')
        if cls in ['st3', 'st4']:
            d = path.get('d', '').strip()
            if d:
                # Filter: only include L-shaped paths (those with vertical segments)
                if only_l_shaped:
                    if 'v' in d or 'V' in d:  # Check for vertical commands
                        paths.append(d)
                else:
                    paths.append(d)

    return paths
```

**Why This Matters:**

- Enabling all st3/st4 paths creates massive duplicates (breaks test cases)
- Smart filtering adds ONLY unique L-shaped connections
- sample-wire.svg remains unchanged (no st3 paths with vertical segments)
- test_cases adds RRT15,3 → SP323 connection without duplicates

**SVG Path Commands Reference:**
- `M x,y` - Move to absolute position
- `c dx1,dy1,dx2,dy2,dx,dy` - Relative cubic Bezier curve (horizontal wire)
- `v dy` - Relative vertical line (LOWERCASE = relative)
- `V y` - Absolute vertical line (UPPERCASE = absolute)
- `h dx` - Relative horizontal line
- `H x` - Absolute horizontal line

## 8. Rectangular Polyline Routing Wires

**Edge Case:** Some circuit diagrams use rectangular polylines (4-point H-V-H pattern) to connect components at different vertical levels.

**Pattern Recognition:**
```python
# A rectangular polyline has 4 points forming 3 sides: H-V-H
# Structure: point1 → point2 → point3 → point4
is_rectangular = (
    len(path_points) == 4 and
    abs(path_points[0][1] - path_points[1][1]) < 5 and  # First segment horizontal
    abs(path_points[1][0] - path_points[2][0]) < 5 and  # Second segment vertical
    abs(path_points[2][1] - path_points[3][1]) < 5      # Third segment horizontal
)
```

**Examples:**
- UH07 ↔ UH08 (orange wire forming rectangle)
- SR02 ↔ SR03 (multiple colored wires, each forming rectangle)
- MAIN14,1 → G203B(m) (4.0, BK ground connection via rectangular path)

### Critical Implementation Details

**1. Corner Endpoint Detection (15-unit threshold):**

Valid endpoints: UH07 (10.6), UH08 (10.1), G203B(m) (12.7), pins (5-8 units)
Excludes incidental labels: MAIN14 at 15.8 units (too far), G202(m) at 50 units (way too far)

**2. Wire Spec Selection (Longest Horizontal Segment):**

Rectangular polylines have multiple horizontal segments. The wire spec is positioned on the **longest** segment (main wire), not the short entry segment.

**3. Wire Spec Conflict Resolution (Shared Pin Disambiguation):**

When a pin has multiple connectors above it and already has a horizontal wire with a different wire spec, select the alternative connector.

**Result:** Pin 1 correctly assigned to MAIN14 (not SR01), creating connection MAIN14,1 → G203B(m) with wire spec 4.0, BK.

**Why This Matters:**

- Pins can have multiple connections: ONE horizontal wire + multiple vertical routing paths
- But each wire spec must match the physical wire (different specs = different connectors)
- This disambiguation ensures correct connector assignment when pins are shared

**Key Rule:**

✅ **ALLOWED:** Pin has one horizontal wire (2.5, BK to SR02) + one vertical routing wire (4.0, BK to G203B(m))
❌ **FORBIDDEN:** Pin connects to two different destinations with the SAME wire spec (duplicate horizontal wires)

## 9. Pass-Through Splice Point Filtering

**Edge Case:** Splice points that act as "pass-throughs" for horizontal wires.

**Problem:**
```
Splice Point Anatomy:
    SP113 (829.9, 732.2)
      ↑            ↑
  Left wire   Right wire
(from RR626)  (to RR622)

When a splice has horizontal wires on BOTH sides, it's a "pass-through".
Routing connections (polylines) should NOT connect two pass-through splices!
```

**Solution:** Track pass-through splices and filter routing connections between them.

**Implementation:**

```python
class VerticalRoutingExtractor:
    def __init__(self, polylines, routing_paths, text_elements, horizontal_connections):
        # ... existing code ...

        # Track splice points with horizontal connections on BOTH sides
        splice_incoming = {}  # splice_id -> count of incoming horizontal wires
        splice_outgoing = {}  # splice_id -> count of outgoing horizontal wires

        for conn in horizontal_connections:
            if is_splice_point(conn.from_id):
                splice_outgoing[conn.from_id] = splice_outgoing.get(conn.from_id, 0) + 1
            if is_splice_point(conn.to_id):
                splice_incoming[conn.to_id] = splice_incoming.get(conn.to_id, 0) + 1

        # Identify bidirectional pass-through splices
        self.passthrough_splices = set()
        for splice_id in set(splice_incoming.keys()) | set(splice_outgoing.keys()):
            if splice_incoming.get(splice_id, 0) >= 1 and splice_outgoing.get(splice_id, 0) >= 1:
                self.passthrough_splices.add(splice_id)

    def extract_connections(self):
        # ... process polylines ...

        # Filter: Skip routing connections between two pass-through splices
        if (source_endpoint.connector_id in self.passthrough_splices and
            dest_endpoint.connector_id in self.passthrough_splices):
            continue  # Don't create connection

        # But ALLOW connections from pass-through splices to pins
        # Example: SP025 → FL7611,9 is valid (SP025 is pass-through, FL7611 is a pin)
```

**Why This Matters:**

- Pass-through splices are common in automotive circuit diagrams
- Without filtering, false connections create invalid wire traces
- Filtering preserves legitimate connections (splice → pin, pin → splice)
- Only blocks splice → splice connections for pass-through nodes

**Examples:**

```
✓ ALLOWED:
  - SP025 → FL7611,9 (pass-through splice to pin)
  - RRT15,3 → SP323 (pin to pass-through splice)

❌ BLOCKED:
  - SP184 → SP113 (both are pass-through splices)
  - SP305 → SP323 (both are pass-through splices)
```

## Lessons Learned

### What Didn't Work

1. **Boundary-based pin assignment** - Pins can be located past other connector labels
2. **Fixed distance thresholds** - Different connector types have different layouts
3. **"Closest connector wins"** - Doesn't account for junction semantics
4. **Large Y-axis tolerance (±20)** - Groups pins from different wire rows
5. **Enabling all st3/st4 paths** - Creates massive duplicates of horizontal wires
6. **Ignoring pass-through splices** - Creates false connections between splice points with horizontal wires

### What Works

1. **Wire-centric algorithm** - Let wires dictate connections
2. **Tight Y-axis tolerance (±10)** - Ensures pins are on same horizontal line
3. **Junction direction rules** - `*2FL` as destinations, `FL2*` as sources
4. **Simple "connector above pin" lookup** - No spatial complexity
5. **Pin-pair deduplication** - Handles overlapping wire specifications
6. **Smart L-shaped path filtering** - Only parse st3/st4 paths with vertical segments ('v' or 'V' commands)
7. **Pass-through splice detection** - Track splices with horizontal wires on both sides, filter routing connections between them
8. **Modular extractor architecture** - Split 2175-line monolith into focused modules with inheritance for shared utilities
