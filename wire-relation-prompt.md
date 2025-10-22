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

## Summary: The Golden Rules

1. **Wire-centric, not connector-centric**
2. **±10 Y-axis tolerance for horizontal alignment**
3. **Junction direction matters: `*2FL` = destinations, `FL2*` = sources**
4. **Find connector directly above pin, not closest overall**
5. **Deduplicate pin pairs to handle overlapping wires**
6. **Sort output by connector ID, then pin number**

Follow these rules exactly, and you will extract accurate wire connections from circuit diagram SVGs.
