"""
Connector identification and lookup logic.
"""
import re
import math
from typing import List, Optional, Tuple
from models import TextElement, ConnectionPoint

# Junction configuration: central junction identifier in automotive wiring
# Convention: PREFIX+2+JUNCTION_ID = destination, JUNCTION_ID+2+PREFIX = source
JUNCTION_ID = 'FL'  # Front Left junction point


def is_destination_junction(connector_id: str) -> bool:
    """Check if junction connector is a destination (*2JUNCTION_ID pattern)."""
    return connector_id.endswith(f'2{JUNCTION_ID}')


def is_source_junction(connector_id: str) -> bool:
    """Check if junction connector is a source (JUNCTION_ID2* pattern)."""
    return connector_id.startswith(f'{JUNCTION_ID}2')


def is_junction_connector(connector_id: str) -> bool:
    """Check if connector is a junction (contains JUNCTION_ID with '2')."""
    return f'2{JUNCTION_ID}' in connector_id or f'{JUNCTION_ID}2' in connector_id


def is_connector_id(text: str) -> bool:
    """
    Check if text is a connector ID (including ground points like G22B(m)).

    Args:
        text: Text to check

    Returns:
        True if text matches connector ID pattern
    """
    # Exclude both labeled (SP001) and custom (SP_CUSTOM_001) splices
    if text.startswith('SP'):
        return False
    # Exclude GND labels (GND, GND1, GND2, etc.) - these are descriptions, not connectors
    if re.match(r'^GND\d*$', text):
        return False
    # Standard connector pattern: MH3202C, FL7210, MH2FL, MAIN557, MAIN38, RRSS380_A
    # Support 2-4 letter prefixes to handle connectors like MAIN
    # Support underscores in connector names (e.g., RRSS380_A)
    if re.match(r'^[A-Z]{2,4}\d{1,5}[A-Z_]{0,5}$', text):
        return True
    # Ground point pattern: G22B(m), G05(z), G22_B(m), etc.
    # Allow underscores between letters
    if re.match(r'^[A-Z_]+\d+[A-Z_]*\([a-z]\)$', text):
        return True
    # Multiline connector with options: MAIN202 (XR-), MAIN642 (XR+)
    # Format: CONNECTOR_ID space (OPTION)
    if re.match(r'^[A-Z]{2,4}\d{1,5}[A-Z_]{0,5}\s+\([A-Z]+[+-]\)$', text):
        return True
    # Shielded pair (multiline): "MAIN202 (XR-)\nMAIN642 (XR+)"
    # Check if text contains newline and both lines match connector pattern
    if '\n' in text:
        lines = text.split('\n')
        if len(lines) == 2:
            # Both lines should match connector patterns
            line1_match = (re.match(r'^[A-Z]{2,4}\d{1,5}[A-Z_]{0,5}$', lines[0]) or
                          re.match(r'^[A-Z]{2,4}\d{1,5}[A-Z_]{0,5}\s+\([A-Z]+[+-]\)$', lines[0]))
            line2_match = (re.match(r'^[A-Z]{2,4}\d{1,5}[A-Z_]{0,5}$', lines[1]) or
                          re.match(r'^[A-Z]{2,4}\d{1,5}[A-Z_]{0,5}\s+\([A-Z]+[+-]\)$', lines[1]))
            if line1_match and line2_match:
                return True
    return False


def is_splice_point(text: str) -> bool:
    """
    Check if text is a splice point ID.

    Matches both labeled splice points (SP001, SP023) and
    custom-generated IDs for unlabeled splices (SP_CUSTOM_001).

    Args:
        text: Text to check

    Returns:
        True if text matches splice point pattern (SP* or SP_CUSTOM_*)
    """
    # Match SP001 format
    if re.match(r'^SP\d+$', text):
        return True
    # Match SP_CUSTOM_001 format
    if text.startswith('SP_CUSTOM_'):
        return True
    return False


def is_pin_number(text: str) -> bool:
    """
    Check if text is a pin number.

    Supports both regular format (1, 2, 3) and dash-separated format (3-1, 4-2).

    Args:
        text: Text to check

    Returns:
        True if text is a valid pin number
    """
    # Regular pin: pure digits
    if text.isdigit():
        return True
    # Dash-separated pin: N-M format (e.g., "3-1", "4-2")
    if re.match(r'^\d+-\d+$', text):
        return True
    return False


def is_wire_spec(text: str) -> bool:
    """
    Check if text is a wire specification.

    Args:
        text: Text to check

    Returns:
        True if text matches wire spec pattern (e.g., "0.35,GY/PU" or "0.35, GY/PU")
    """
    return bool(re.match(r'^([\d.]+),\s*([A-Z]{2,}(?:/[A-Z]{2,})?)$', text))


def parse_wire_spec(text: str) -> Optional[Tuple[str, str]]:
    """
    Parse wire specification into diameter and color.

    Args:
        text: Wire spec text (e.g., "0.35,GY/PU")

    Returns:
        Tuple of (diameter, color) or None if not a wire spec
    """
    match = re.match(r'^([\d.]+),\s*([A-Z]{2,}(?:/[A-Z]{2,})?)$', text)
    if match:
        return match.group(1), match.group(2)
    return None


def find_connector_above_pin(
    pin_x: float,
    pin_y: float,
    text_elements: List[TextElement],
    prefer_as_source: bool = False,
    source_x: float = None,
    destination_x: float = None
) -> Optional[Tuple[str, float, float]]:
    """
    Find the closest connector directly above a pin.

    Args:
        pin_x, pin_y: Pin coordinates
        text_elements: List of all text elements
        prefer_as_source: If True, for mirrored junction pairs, prefer the variant where shorter prefix is LAST
                         If False, for mirrored junction pairs, prefer the variant where shorter prefix is FIRST
        source_x: X coordinate of source (for junction selection when this pin is destination)
        destination_x: X coordinate of destination (for picking junction closer to destination when this pin is source)

    Returns:
        Tuple of (connector_id, x, y) or None if no connector found
    """
    connectors_above = []

    for elem in text_elements:
        if not is_connector_id(elem.content):
            continue

        # Check if connector is above the pin
        x_dist = abs(elem.x - pin_x)
        y_dist = pin_y - elem.y

        # Connector must be above (positive y_dist) and horizontally aligned
        conn_id = elem.content

        # Detect junction pattern: PREFIX12PREFIX2 (e.g., MH2FL, FL2MH, FTL2FL, FL2FTL)
        # Junction has '2' in middle, splits into two 2-3 letter alphabetic parts
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

    # Sort by Y distance first, then X distance for ties
    # Calculate Euclidean distance for final selection
    connectors_with_distance = []
    for y_dist, cid, cx, cy in connectors_above:
        x_dist_from_pin = abs(cx - pin_x)
        euclidean_dist = math.sqrt(y_dist**2 + x_dist_from_pin**2)
        connectors_with_distance.append((euclidean_dist, y_dist, x_dist_from_pin, cid, cx, cy))

    # Sort by Euclidean distance
    connectors_with_distance.sort(key=lambda c: c[0])

    # CRITICAL: If source_x is provided, prefer connectors BETWEEN source and pin
    # This handles shared pins where multiple connectors are above the same pin
    if source_x is not None and not prefer_as_source:
        # Separate connectors into "between" and "not between"
        between_connectors = []
        other_connectors = []

        for conn in connectors_with_distance:
            eucl_dist, y_dist, x_dist, cid, cx, cy = conn

            # Check if connector is between source_x and pin_x
            if source_x < pin_x:
                # Wire goes left to right
                is_between = source_x < cx < pin_x
            else:
                # Wire goes right to left
                is_between = pin_x < cx < source_x

            if is_between:
                between_connectors.append(conn)
            else:
                other_connectors.append(conn)

        # If we have connectors between, prioritize them
        if between_connectors:
            # CRITICAL: Among "between" connectors, use smart sorting strategy:
            # 1. First, filter to connectors within 50 Y units of pin (ignore distant connectors)
            #    Example: SP_CUSTOM_001 → RS808/RS911 (Y=14) vs RS809 (Y=337) → ignore RS809
            # 2. Among close connectors, if they have different Y distances (>50 units), prefer closest to PIN
            #    Example: RS901,4 → RS904 (Y=14) vs RS857 (Y=154) → pick RS904 (just above wire)
            # 3. If they have similar Y distances (<50 units), prefer closest to SOURCE
            #    Example: SP_CUSTOM_001 → RS808 (X dist=41) vs RS911 (X dist=64) → pick RS808 (to the left)

            # Filter to connectors within 50 Y units of pin
            close_between_connectors = [c for c in between_connectors if c[1] < 50]  # c[1] is Y distance

            # If we have close connectors, use them; otherwise use all between connectors
            connectors_to_sort = close_between_connectors if close_between_connectors else between_connectors

            # Check Y distance range among connectors to sort
            y_distances = [c[1] for c in connectors_to_sort]
            min_y_dist = min(y_distances)
            max_y_dist = max(y_distances)
            y_range = max_y_dist - min_y_dist

            if y_range > 50:
                # Large Y range: prefer connector closest to pin (smallest Euclidean distance)
                connectors_to_sort.sort(key=lambda c: c[0])  # c[0] is Euclidean distance
            else:
                # Small Y range: prefer connector closest to source (smallest X distance to source)
                connectors_to_sort.sort(key=lambda c: abs(c[4] - source_x))  # c[4] is connector X

            connectors_with_distance = connectors_to_sort + other_connectors

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

        # If destination_x is provided (this pin is source), pick junction CLOSER to destination
        if destination_x is not None and prefer_as_source:
            junc1_x, junc2_x = junc1[4], junc2[4]
            dist1_to_dest = abs(junc1_x - destination_x)
            dist2_to_dest = abs(junc2_x - destination_x)

            # Pick the junction closer to the destination
            if dist1_to_dest < dist2_to_dest:
                conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
            else:
                conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]

            return (conn_id, conn_x, conn_y)

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
                # Both between: prefer based on prefer_as_source rule
                if not prefer_as_source:
                    # Destination: prefer destination junction variant
                    if is_destination_junction(junc1[3]):
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                    elif is_destination_junction(junc2[3]):
                        conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
                    else:
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                else:
                    # Source: prefer source junction variant
                    if is_source_junction(junc1[3]):
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                    elif is_source_junction(junc2[3]):
                        conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
                    else:
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
            elif junc1_between and not junc2_between:
                # Only junc1 is between: prefer it
                conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
            elif junc2_between and not junc1_between:
                # Only junc2 is between: prefer it
                conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
            else:
                # Neither between: prefer based on prefer_as_source rule
                if not prefer_as_source:
                    # Destination: prefer destination junction variant
                    if is_destination_junction(junc1[3]):
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                    elif is_destination_junction(junc2[3]):
                        conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
                    else:
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                else:
                    # Source: prefer source junction variant
                    if is_source_junction(junc1[3]):
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                    elif is_source_junction(junc2[3]):
                        conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
                    else:
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
        else:
            # No source info: use prefer_as_source rule
            if not prefer_as_source:
                # Destination: prefer destination junction variant
                if is_destination_junction(junc1[3]):
                    conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                elif is_destination_junction(junc2[3]):
                    conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
                else:
                    conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
            else:
                # Source: prefer source junction variant
                if is_source_junction(junc1[3]):
                    conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                elif is_source_junction(junc2[3]):
                    conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
                else:
                    conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
    else:
        # No junction pair, use closest
        conn_id, conn_x, conn_y = connectors_with_distance[0][3], connectors_with_distance[0][4], connectors_with_distance[0][5]

    return (conn_id, conn_x, conn_y)


def find_connector_above_pin_prefer_ground(
    pin_x: float,
    pin_y: float,
    text_elements: List[TextElement]
) -> Optional[str]:
    """
    Find connector above pin, preferring *2FL variants for ground connections.

    Args:
        pin_x, pin_y: Pin coordinates
        text_elements: List of all text elements

    Returns:
        Connector ID or None
    """
    connectors_above = []

    for elem in text_elements:
        if not is_connector_id(elem.content):
            continue

        x_dist = abs(elem.x - pin_x)
        y_dist = pin_y - elem.y

        max_x_dist = 100 if is_junction_connector(elem.content) else 50
        max_y_dist = 50  # Don't match connectors that are too far above the pin

        if x_dist < max_x_dist and 5 < y_dist < max_y_dist:
            connectors_above.append((y_dist, elem.content, elem.x, elem.y))

    if not connectors_above:
        return None

    connectors_above.sort(key=lambda c: c[0])

    # Prefer destination junction variants for ground connections
    dest_variants = [c for c in connectors_above if is_destination_junction(c[1])]
    if dest_variants:
        return dest_variants[0][1]

    # Fall back to closest connector
    return connectors_above[0][1]


def find_nearest_connection_point(
    target_x: float,
    target_y: float,
    text_elements: List[TextElement],
    max_distance: float = 100,
    prefer_connector_near_target: bool = True,
    horizontal_connections: List = None
) -> Optional[ConnectionPoint]:
    """
    Find the nearest pin or splice point to a target coordinate.

    Used for vertical routing where polyline endpoints may not exactly align.

    Args:
        target_x, target_y: Target coordinates
        text_elements: List of all text elements
        max_distance: Maximum distance to search
        prefer_connector_near_target: If True and multiple connectors are above a pin,
                                      prefer the connector closest to target (for polylines)
        horizontal_connections: List of horizontal wire connections (to filter out pins already in use)

    Returns:
        ConnectionPoint or None
    """
    nearest = None
    min_distance = float('inf')

    for elem in text_elements:
        # Check for pin numbers (digits), splice points (SP*), or ground connectors
        is_ground = is_connector_id(elem.content) and '(' in elem.content
        if elem.content.isdigit() or is_splice_point(elem.content) or is_ground:
            dist = math.sqrt((elem.x - target_x)**2 + (elem.y - target_y)**2)

            if dist < max_distance and dist < min_distance:
                min_distance = dist

                if is_splice_point(elem.content):
                    # It's a splice point
                    nearest = ConnectionPoint(elem.content, '', elem.x, elem.y)
                elif is_ground:
                    # It's a ground connector
                    nearest = ConnectionPoint(elem.content, '', elem.x, elem.y)
                else:
                    # It's a pin number - find the connector above it
                    # CRITICAL: When multiple connectors are above this pin (e.g., MH316 and RLS200),
                    # prefer the connector that's CLOSER TO THE TARGET (polyline endpoint)
                    # This handles cases where the wire routes to a specific connector position
                    if prefer_connector_near_target:
                        # Find all connectors above this pin
                        connectors_above = find_all_connectors_above_pin(elem.x, elem.y, text_elements)
                        if connectors_above:
                            # CRITICAL: Prefer connectors WITHOUT existing horizontal wires
                            # This handles shared pins where one connector is already in use for horizontal wiring
                            # BUT: Only filter if multiple connectors are at SIMILAR Y distances
                            # If one is MUCH closer (> 20 Y units difference), rely on deduplication instead
                            if horizontal_connections and len(connectors_above) > 1:
                                # Check Y distance range among CLOSEST TWO connectors
                                # connectors_above is already sorted by Y distance (from find_all_connectors_above_pin)
                                # We only care if the two closest are at similar distances
                                closest_two_y_dists = [connectors_above[0][0], connectors_above[1][0]]
                                y_dist_range = closest_two_y_dists[1] - closest_two_y_dists[0]

                                # Only filter if the TWO CLOSEST connectors are at similar distances (< 20 Y units apart)
                                # At >= 20 Y apart, one is much closer - deduplication handles it
                                if y_dist_range < 20:
                                    # Get set of pins that have horizontal wires as sources
                                    pins_with_horizontal = set()
                                    for conn in horizontal_connections:
                                        pins_with_horizontal.add((conn.from_id, conn.from_pin))

                                    # Separate connectors into those with/without horizontal wires
                                    connectors_without_horizontal = [c for c in connectors_above
                                                                    if (c[1], elem.content) not in pins_with_horizontal]

                                    # Prefer connectors without horizontal wires, but allow those with if no alternatives
                                    if connectors_without_horizontal:
                                        connectors_above = connectors_without_horizontal

                            # Pick the connector closest to the PIN (by Y-distance)
                            # connectors_above is already sorted by Y-distance, so first one is closest
                            closest_connector = connectors_above[0]
                            nearest = ConnectionPoint(
                                closest_connector[1],  # connector_id
                                elem.content,          # pin
                                elem.x,
                                elem.y
                            )
                    else:
                        # Use standard logic (connector directly above pin)
                        connector_result = find_connector_above_pin(elem.x, elem.y, text_elements)
                        if connector_result:
                            nearest = ConnectionPoint(
                                connector_result[0],
                                elem.content,
                                elem.x,
                                elem.y
                            )

    # Fallback: If no pins/splices found, look for regular connector IDs
    # This handles diagrams where connectors don't have individual pin labels
    if nearest is None:
        for elem in text_elements:
            if is_connector_id(elem.content) and '(' not in elem.content:  # Regular connectors (not ground)
                dist = math.sqrt((elem.x - target_x)**2 + (elem.y - target_y)**2)

                if dist < max_distance and dist < min_distance:
                    min_distance = dist
                    # Connector without pin
                    nearest = ConnectionPoint(elem.content, '', elem.x, elem.y)

    return nearest


def find_all_connectors_above_pin(
    pin_x: float,
    pin_y: float,
    text_elements: List[TextElement]
) -> List[Tuple[float, str, float, float]]:
    """
    Find ALL connectors above a pin (not just the closest).

    Used for ground connections where we need to choose between junction variants.

    Args:
        pin_x, pin_y: Pin coordinates
        text_elements: List of all text elements

    Returns:
        List of (y_distance, connector_id, x, y) tuples, sorted by Y distance
    """
    connectors_above = []

    for elem in text_elements:
        if not is_connector_id(elem.content):
            continue

        x_dist = abs(elem.x - pin_x)
        y_dist = pin_y - elem.y

        max_x_dist = 100 if is_junction_connector(elem.content) else 50
        max_y_dist = 50  # Don't match connectors that are too far above the pin

        if x_dist < max_x_dist and 5 < y_dist < max_y_dist:
            connectors_above.append((y_dist, elem.content, elem.x, elem.y))

    connectors_above.sort(key=lambda c: c[0])
    return connectors_above
