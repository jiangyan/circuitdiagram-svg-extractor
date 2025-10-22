"""
Wire-Centric Circuit Diagram SVG Connection Extractor

Strategy: Start from wires, not connectors.
1. Find all wire specifications
2. For each wire, find pins on both ends
3. Assign each pin to the CLOSEST connector above it (simple nearest-above rule)
"""

import xml.etree.ElementTree as ET
import re
from dataclasses import dataclass
from typing import List, Tuple, Optional

# Global variable to store wire lines for junction selection
_wire_lines = []


@dataclass
class Connection:
    from_id: str
    from_pin: str
    to_id: str
    to_pin: str
    wire_dm: str
    wire_color: str


def parse_svg_elements(svg_file: str) -> tuple[List[dict], List[dict], List[dict]]:
    """Parse all text elements, splice point dots, and wire lines from SVG file

    Returns:
        (text_elements, splice_dots, wire_lines)
        text_elements: list of {x, y, content} for all text
        splice_dots: list of {x, y} for all splice point dots (path circles)
        wire_lines: list of {y, x_start, x_end} for horizontal wire lines
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    text_elements = []
    splice_dots = []
    wire_lines = []

    # Parse text elements
    for text in root.iter('{http://www.w3.org/2000/svg}text'):
        transform = text.get('transform', '')
        content = text.text or ''

        match = re.search(r'matrix\([^)]*\s+([\d.]+)\s+([\d.]+)\)', transform)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            text_elements.append({'x': x, 'y': y, 'content': content.strip()})

    # Parse path elements for both splice dots and wire lines
    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        d = path.get('d', '')
        cls = path.get('class', '')

        # Parse circle paths (splice dots): M x,y c ...
        match = re.match(r'M([\d.]+),([\d.]+)c', d)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            splice_dots.append({'x': x, 'y': y})

        # Parse horizontal wire line paths (class="st4"): M x,y c ...
        if 'st4' in cls:
            match = re.match(r'M([\d.]+),([\d.]+)', d)
            if match:
                x_start = float(match.group(1))
                y = float(match.group(2))
                # Parse the relative coordinates to get x_end
                # Path like: M581.3,91.2c-37.5,0,7.4,0,-95.6,0 or M413.2,345.9c-56.4,0-13.8,0-168.9,0
                # The format is: c dx1,dy1,dx2,dy2,dx,dy (commas are optional when sign provides boundary)
                # Extract all numbers after 'c'
                numbers_str = d.split('c')[1] if 'c' in d else ''
                # Insert spaces before hyphens that start new numbers (not at beginning or after comma)
                numbers_str = re.sub(r'(\d)(-)', r'\1 \2', numbers_str)
                # Now extract all numbers
                numbers = re.findall(r'[-\d.]+', numbers_str)
                if len(numbers) >= 6:
                    x_displacement = float(numbers[4])  # The dx value (5th number, index 4)
                    x_end = x_start + x_displacement
                    wire_lines.append({'y': y, 'x_start': min(x_start, x_end), 'x_end': max(x_start, x_end)})

    return text_elements, splice_dots, wire_lines


def is_connector_id(text: str) -> bool:
    """Check if text is a connector ID"""
    if text.startswith('SP'):  # Exclude splices
        return False
    return bool(re.match(r'^[A-Z]{2,3}\d{1,5}[A-Z]{0,3}$', text))


def is_splice_point(text: str) -> bool:
    """Check if text is a splice point ID"""
    return bool(re.match(r'^SP\d+$', text))


def map_splice_labels_to_dots(text_elements: List[dict], splice_dots: List[dict]) -> List[dict]:
    """Map splice point text labels to their actual dot positions

    For each SP* text label, find the closest dot and replace the text position
    with the dot position. This gives us the actual connection point, not the label position.

    Returns:
        Updated text_elements with SP* positions replaced by dot positions
    """
    import math

    updated_elements = []

    for elem in text_elements:
        if is_splice_point(elem['content']):
            # Find closest dot to this SP* label
            closest_dot = None
            min_distance = float('inf')

            for dot in splice_dots:
                # Calculate distance from label to dot
                distance = math.sqrt((dot['x'] - elem['x'])**2 + (dot['y'] - elem['y'])**2)
                if distance < min_distance:
                    min_distance = distance
                    closest_dot = dot

            if closest_dot and min_distance < 50:  # Within reasonable distance
                # Replace label position with dot position
                updated_elements.append({
                    'x': closest_dot['x'],
                    'y': closest_dot['y'],
                    'content': elem['content']
                })
            else:
                # No nearby dot found, keep original
                updated_elements.append(elem)
        else:
            # Not a splice point, keep as-is
            updated_elements.append(elem)

    return updated_elements


def find_endpoint_above(point_x: float, point_y: float, text_elements: List[dict],
                        prefer_as_source: bool = False, source_x: float = None) -> Optional[Tuple[str, str, float, float]]:
    """Find the entity (connector or splice point) directly above a connection point

    Returns: (entity_id, pin, x, y) where pin is '' for splice points
    """
    # Check if this point itself is a splice point
    for elem in text_elements:
        if is_splice_point(elem['content']) and abs(elem['x'] - point_x) < 5 and abs(elem['y'] - point_y) < 5:
            # The point itself is a splice - return it with empty pin
            return (elem['content'], '', elem['x'], elem['y'])

    # Otherwise, find connector above the pin
    result = find_connector_above_pin(point_x, point_y, text_elements, prefer_as_source, source_x)
    if result:
        # find_connector_above_pin returns (conn_id, x, y), we need to add the pin
        # The pin is determined by looking for the numeric text at this point
        pin = ''
        for elem in text_elements:
            if elem['content'].isdigit() and abs(elem['x'] - point_x) < 5 and abs(elem['y'] - point_y) < 5:
                pin = elem['content']
                break

        return (result[0], pin, result[1], result[2])

    return None


def find_connector_above_pin(pin_x: float, pin_y: float, text_elements: List[dict],
                             prefer_as_source: bool = False, source_x: float = None) -> Optional[Tuple[str, float, float]]:
    """Find the closest connector directly above a pin

    Args:
        pin_x, pin_y: Pin coordinates
        text_elements: All text elements from SVG
        prefer_as_source: If True, for mirrored junction pairs, prefer the variant where shorter prefix is LAST
                         If False, for mirrored junction pairs, prefer the variant where shorter prefix is FIRST
    """
    connectors_above = []

    for elem in text_elements:
        if not is_connector_id(elem['content']):
            continue

        # Check if connector is above the pin
        x_dist = abs(elem['x'] - pin_x)
        y_dist = pin_y - elem['y']

        # Connector must be above (positive y_dist) and horizontally aligned
        # Use generous thresholds to handle junction connectors
        conn_id = elem['content']

        # Detect junction pattern: PREFIX12PREFIX2 (e.g., MH2FL, FL2MH, FTL2FL, FL2FTL)
        # Junction has '2' in middle, splits into two 2-3 letter alphabetic parts
        is_junction = False
        if '2' in conn_id and len(conn_id) >= 5:
            parts = conn_id.split('2', 1)
            if len(parts) == 2 and all(p.isalpha() and 2 <= len(p) <= 3 for p in parts):
                is_junction = True

        max_x_dist = 100 if is_junction else 50

        if x_dist < max_x_dist and y_dist > 5:
            connectors_above.append((y_dist, elem['content'], elem['x'], elem['y']))

    if not connectors_above:
        return None

    # Sort by Y distance first, then X distance for ties
    # Calculate Euclidean distance for final selection
    import math
    connectors_with_distance = []
    for y_dist, cid, cx, cy in connectors_above:
        x_dist_from_pin = abs(cx - pin_x)
        euclidean_dist = math.sqrt(y_dist**2 + x_dist_from_pin**2)
        connectors_with_distance.append((euclidean_dist, y_dist, x_dist_from_pin, cid, cx, cy))

    # Sort by Euclidean distance
    connectors_with_distance.sort(key=lambda c: c[0])

    # Check for junction pairs (mirrored connectors like FL2MH/MH2FL, FTL2FL/FL2FTL)
    has_junction_pair = False
    junction_connectors = []
    for c in connectors_with_distance[:3]:
        if '2' in c[3] and len(c[3]) >= 5:
            parts = c[3].split('2', 1)
            if len(parts) == 2 and all(p.isalpha() and 2 <= len(p) <= 3 for p in parts):
                mirror_name = f"{parts[1]}2{parts[0]}"
                if any(c2[3] == mirror_name for c2 in connectors_with_distance[:3]):
                    has_junction_pair = True
                    junction_connectors.append(c)

    # Special handling for junction pairs
    if has_junction_pair and len(junction_connectors) >= 2:
        junc1, junc2 = junction_connectors[0], junction_connectors[1]

        # If we know the source X position, pick the junction that's between source and destination
        if source_x is not None and not prefer_as_source:
            # For destination: pick the junction that's between source_x and pin_x
            junc1_x, junc2_x = junc1[4], junc2[4]

            # Identify junction type for type-specific logic
            is_mh_junction = 'MH2FL' in junc1[3] or 'FL2MH' in junc1[3]

            # Check if wire goes left-to-right or right-to-left
            if source_x < pin_x:
                # Wire goes left to right: pick junction between source and pin
                junc1_between = source_x < junc1_x < pin_x
                junc2_between = source_x < junc2_x < pin_x
            else:
                # Wire goes right to left: pick junction between pin and source
                junc1_between = pin_x < junc1_x < source_x
                junc2_between = pin_x < junc2_x < source_x

            if junc1_between and junc2_between:
                # Both between: logic depends on junction type
                # MH junctions: pick closer to PIN (tightly packed near destination)
                # FTL junctions: pick closer to SOURCE (spread out along wire path)
                if is_mh_junction:
                    dist1_from_pin = abs(junc1_x - pin_x)
                    dist2_from_pin = abs(junc2_x - pin_x)
                    if dist1_from_pin < dist2_from_pin:
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                    else:
                        conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
                else:  # FTL junction
                    dist1_from_source = abs(junc1_x - source_x)
                    dist2_from_source = abs(junc2_x - source_x)
                    if dist1_from_source < dist2_from_source:
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                    else:
                        conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
            elif junc1_between and not junc2_between:
                # Only junc1 is between: prefer it
                conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
            elif junc2_between and not junc1_between:
                # Only junc2 is between: prefer it
                conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
            else:
                # Neither between: use closest to pin (junc1 is already sorted as closest)
                conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
        else:
            # No source info or this is source: use closest
            conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
    else:
        # No junction pair, use closest
        conn_id, conn_x, conn_y = connectors_with_distance[0][3], connectors_with_distance[0][4], connectors_with_distance[0][5]

    return (conn_id, conn_x, conn_y)


def extract_all_connections(svg_file: str) -> List[Connection]:
    """Extract all wire connections from SVG"""
    text_elements, splice_dots, wire_lines = parse_svg_elements(svg_file)

    print(f"Parsed {len(text_elements)} text elements")
    print(f"Parsed {len(splice_dots)} splice point dots")
    print(f"Parsed {len(wire_lines)} wire lines")

    # Map splice point labels to their actual dot positions
    text_elements = map_splice_labels_to_dots(text_elements, splice_dots)
    print(f"Mapped splice point positions to dots")

    # Store wire_lines globally so find_connector_above_pin can access them
    global _wire_lines
    _wire_lines = wire_lines

    # Find all wire specifications
    wire_specs = []
    for elem in text_elements:
        # Match both single color (BN) and dual color (GY/PU) patterns
        match = re.match(r'^([\d.]+),([A-Z]{2}(?:/[A-Z]{2})?)$', elem['content'])
        if match:
            diameter, color = match.groups()
            wire_specs.append({
                'x': elem['x'],
                'y': elem['y'],
                'diameter': diameter,
                'color': color
            })

    print(f"Found {len(wire_specs)} wire specifications")

    connections = []
    # Track pin pairs to avoid duplicates
    seen_pin_pairs = set()

    # Group wire specs by horizontal line (same Y coordinate within ±10 units)
    wire_lines = {}
    for wire_spec in wire_specs:
        # Round Y to nearest 10 to group wires on same horizontal line
        line_key = round(wire_spec['y'] / 10) * 10
        if line_key not in wire_lines:
            wire_lines[line_key] = []
        wire_lines[line_key].append(wire_spec)

    # Process each horizontal line
    for line_y, specs_on_line in wire_lines.items():
        # Use the first wire spec for diameter/color (they should all be the same on one line)
        wire_spec = specs_on_line[0]

        # Find all connection points on this horizontal line (±10 Y units)
        # Connection points can be: pins (numeric) OR splice points (SP*)
        connection_points = []
        for elem in text_elements:
            if abs(elem['y'] - wire_spec['y']) < 10:
                if elem['content'].isdigit() or is_splice_point(elem['content']):
                    connection_points.append(elem)

        if len(connection_points) < 2:
            # Need at least 2 connection points
            continue

        # Sort connection points by X coordinate (left to right)
        connection_points.sort(key=lambda p: p['x'])

        # Create connections between ALL ADJACENT pairs of connection points on this line
        # This handles: pin→splice, splice→splice, splice→pin, pin→pin
        for i in range(len(connection_points) - 1):
            left_point = connection_points[i]
            right_point = connection_points[i + 1]

            # Find entities for both connection points
            # Left is source
            left_endpoint = find_endpoint_above(left_point['x'], left_point['y'], text_elements, prefer_as_source=True)
            # Right is destination - pass source X to help with junction selection
            right_endpoint = find_endpoint_above(right_point['x'], right_point['y'], text_elements, prefer_as_source=False, source_x=left_point['x'])

            if left_endpoint and right_endpoint:
                left_id, left_pin, _, _ = left_endpoint
                right_id, right_pin, _, _ = right_endpoint

                # Skip self-connections (same connector, different pins on same line)
                if left_id == right_id and left_pin != right_pin and not is_splice_point(left_id):
                    continue

                # Create a unique key for this connection
                connection_key = tuple(sorted([
                    (left_id, left_pin, left_point['x'], left_point['y']),
                    (right_id, right_pin, right_point['x'], right_point['y'])
                ]))

                # Skip if we've already created this connection
                if connection_key in seen_pin_pairs:
                    continue

                seen_pin_pairs.add(connection_key)

                connection = Connection(
                    from_id=left_id,
                    from_pin=left_pin,
                    to_id=right_id,
                    to_pin=right_pin,
                    wire_dm=wire_spec['diameter'],
                    wire_color=wire_spec['color']
                )
                connections.append(connection)

    return connections


if __name__ == '__main__':
    svg_file = 'sample-wire.svg'

    print("=" * 80)
    print("Circuit Diagram Connection Extractor V3 (Wire-Centric)")
    print("=" * 80)

    connections = extract_all_connections(svg_file)

    print(f"\nExtracted {len(connections)} total connections")

    # Filter for MH3202C
    mh3202c_connections = [c for c in connections if c.from_id == 'MH3202C']
    print(f"\nMH3202C connections: {len(mh3202c_connections)}")
    for conn in mh3202c_connections:
        print(f"  {conn.from_id} pin {conn.from_pin} -> {conn.to_id} pin {conn.to_pin} ({conn.wire_dm},{conn.wire_color})")

    # Filter for MH3202E
    mh3202e_connections = [c for c in connections if c.from_id == 'MH3202E']
    print(f"\nMH3202E connections: {len(mh3202e_connections)}")
    for conn in mh3202e_connections:
        print(f"  {conn.from_id} pin {conn.from_pin} -> {conn.to_id} pin {conn.to_pin} ({conn.wire_dm},{conn.wire_color})")

    # Generate markdown table
    print("\n" + "=" * 80)
    print("All Connections (Sorted by From Connector)")
    print("=" * 80)
    print("\n| From | From Pin | To | To Pin | Wire DM | Color |")
    print("|------|----------|-----|--------|---------|-------|")

    # Sort connections by From connector ID, then by From pin number
    sorted_connections = sorted(connections, key=lambda c: (c.from_id, int(c.from_pin) if c.from_pin.isdigit() else 999))

    for conn in sorted_connections:
        print(f"| {conn.from_id} | {conn.from_pin} | {conn.to_id} | "
              f"{conn.to_pin} | {conn.wire_dm} | {conn.wire_color} |")

    # Export to markdown file
    output_file = 'connections_output.md'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Circuit Diagram Wire Connections\n\n")
        f.write(f"**Total Connections:** {len(connections)}\n\n")

        f.write("## All Connections (Sorted by From Connector)\n\n")
        f.write("| From | From Pin | To | To Pin | Wire DM | Color |\n")
        f.write("|------|----------|-----|--------|---------|-------|\n")

        # Use already sorted connections from console output
        for conn in sorted_connections:
            f.write(f"| {conn.from_id} | {conn.from_pin} | {conn.to_id} | "
                   f"{conn.to_pin} | {conn.wire_dm} | {conn.wire_color} |\n")

        # Group by source connector
        f.write("\n## Connections Grouped by Source Connector\n\n")

        # Get unique source connectors
        source_connectors = sorted(set(c.from_id for c in connections))

        for src_conn in source_connectors:
            src_connections = [c for c in connections if c.from_id == src_conn]
            f.write(f"### {src_conn} ({len(src_connections)} connections)\n\n")
            f.write("| From Pin | To | To Pin | Wire DM | Color |\n")
            f.write("|----------|-----|--------|---------|-------|\n")

            # Sort by pin number
            src_connections.sort(key=lambda c: int(c.from_pin) if c.from_pin.isdigit() else 999)

            for conn in src_connections:
                f.write(f"| {conn.from_pin} | {conn.to_id} | {conn.to_pin} | "
                       f"{conn.wire_dm} | {conn.wire_color} |\n")
            f.write("\n")

    print(f"\n✓ Exported to {output_file}")
