"""
SVG parsing utilities for circuit diagrams.
"""
import re
import math
import xml.etree.ElementTree as ET
from typing import List, Tuple
from models import TextElement, WireSpec, IDGenerator


def parse_text_elements(svg_file: str) -> List[TextElement]:
    """
    Parse all text elements from SVG file.

    Args:
        svg_file: Path to SVG file

    Returns:
        List of TextElement objects
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    text_elements = []

    for text in root.iter('{http://www.w3.org/2000/svg}text'):
        transform = text.get('transform', '')
        content = text.text

        if not transform or not content:
            continue

        # Extract coordinates from transform matrix
        # Format: "matrix(1 0 0 1 237.3564 331.6939)"
        match = re.search(r'matrix\([^\)]+\s+([\d.]+)\s+([\d.]+)\)', transform)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            text_elements.append(TextElement(content.strip(), x, y))

    return text_elements


def merge_multiline_connectors(text_elements: List[TextElement]) -> List[TextElement]:
    """
    Merge connector option labels and create multiline connector IDs for shielded pairs.

    Handles two cases:
    1. Horizontal pairing: MAIN202 + (XR-) → "MAIN202 (XR-)"
    2. Vertical pairing (shielded pairs):
       MAIN202 (XR-) at Y=304
       MAIN642 (XR+) at Y=312
       → "MAIN202 (XR-)\\nMAIN642 (XR+)"

    Args:
        text_elements: List of text elements

    Returns:
        List of text elements with merged/combined connectors
    """
    from connector_finder import is_connector_id

    # Step 1: Merge horizontal option labels with base connectors
    option_to_connector = {}  # Maps option_index -> connector_index

    for i, elem in enumerate(text_elements):
        # Check if this is an option label like "(XR-)", "(XR+)"
        if re.match(r'^\([A-Z]+[+-]\)$', elem.content):
            # Find connector to the left (within 30 X units, same Y level ±3 units)
            for j, other in enumerate(text_elements):
                if j == i:
                    continue

                # Check if other is a connector ID to the left
                if is_connector_id(other.content):
                    # Must be to the left and on same Y level
                    if (other.x < elem.x and
                        abs(other.y - elem.y) < 3 and
                        abs(elem.x - other.x) < 30):
                        # Record this pairing
                        option_to_connector[i] = j
                        break

    # Build list with horizontal merges
    processed_indices = set()
    horizontally_merged = []

    for i, elem in enumerate(text_elements):
        if i in processed_indices:
            continue

        # Check if this element is a connector that has an option label
        if i in option_to_connector.values():
            # Find the option label(s) for this connector
            option_indices = [opt_i for opt_i, conn_i in option_to_connector.items() if conn_i == i]
            if option_indices:
                option_idx = option_indices[0]
                option_elem = text_elements[option_idx]
                # Merge: create new element with combined content
                combined_content = f"{elem.content} {option_elem.content}"
                horizontally_merged.append(TextElement(combined_content, elem.x, elem.y))
                processed_indices.add(i)
                processed_indices.add(option_idx)
                continue

        # Check if this is an option label that was already merged
        if i in option_to_connector:
            processed_indices.add(i)
            continue

        # Regular element
        horizontally_merged.append(elem)
        processed_indices.add(i)

    # Step 2: Detect and merge vertical shielded pairs
    # Find connectors with (XR-) and (XR+) options that are vertically aligned
    processed_indices = set()
    final_merged = []

    for i, elem in enumerate(horizontally_merged):
        if i in processed_indices:
            continue

        # Check if this is a connector with (XR-) or (XR+)
        if ' (XR-)' in elem.content or ' (XR+)' in elem.content:
            # Look for its pair (vertically stacked, within ±15 Y units, similar X position ±30 units)
            paired = False
            for j, other in enumerate(horizontally_merged):
                if j <= i or j in processed_indices:
                    continue

                # Check if other is also an XR connector
                if ' (XR-)' in other.content or ' (XR+)' in other.content:
                    # Must be vertically aligned (similar X, different Y)
                    x_diff = abs(other.x - elem.x)
                    y_diff = abs(other.y - elem.y)

                    # Vertically stacked: within ±30 X units, 5-20 Y units apart
                    if x_diff < 30 and 5 < y_diff < 20:
                        # Must have opposite options (one XR-, one XR+)
                        has_xr_minus = '(XR-)' in elem.content or '(XR-)' in other.content
                        has_xr_plus = '(XR+)' in elem.content or '(XR+)' in other.content

                        if has_xr_minus and has_xr_plus:
                            # Create multiline connector (use newline as separator)
                            # Order: XR- first, then XR+
                            if '(XR-)' in elem.content:
                                multiline_content = f"{elem.content}\n{other.content}"
                                use_y = elem.y
                            else:
                                multiline_content = f"{other.content}\n{elem.content}"
                                use_y = other.y

                            # CRITICAL: Use AVERAGE X coordinate of both connectors
                            # This represents the center position between the two stacked connectors
                            # Important for find_connector_above_pin "between" logic
                            use_x = (elem.x + other.x) / 2

                            final_merged.append(TextElement(multiline_content, use_x, use_y))
                            processed_indices.add(i)
                            processed_indices.add(j)
                            paired = True
                            break

            if not paired:
                # No pair found, keep as single-line connector
                final_merged.append(elem)
                processed_indices.add(i)
        else:
            # Not an XR connector
            final_merged.append(elem)
            processed_indices.add(i)

    return final_merged


def parse_splice_dots(svg_file: str) -> List[Tuple[float, float]]:
    """
    Parse splice point dots from SVG.

    Splice dots are small circles drawn with cubic bezier curves.
    Pattern: M x,y c ... (short path with multiple 'c' commands forming a circle)

    Args:
        svg_file: Path to SVG file

    Returns:
        List of (x, y) coordinates
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    dots = []

    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        d = path.get('d', '')

        # Splice dots are circles with these characteristics:
        # 1. No class attribute (real splice dots have no styling)
        # 2. Short path (< 200 chars)
        # 3. Multiple cubic bezier curves (at least 3 'c' commands)
        # 4. Starts with M x,y

        # CRITICAL: Only match paths with no class attribute
        # This excludes arrowheads (st10), routing arrows (st17), and other styled elements
        if path.get('class'):
            continue

        if len(d) > 200:
            continue

        # Count 'c' commands (cubic bezier curves)
        c_count = d.count('c') + d.count('C')
        # Rough heuristic: path('d="...c...c...c..."') has 3+ c's for circles
        if c_count < 3:
            continue

        # Extract starting coordinates
        match = re.match(r'M([\d.]+),([\d.]+)', d)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            dots.append((x, y))

    return dots


def parse_wire_lines(svg_file: str) -> List[Tuple[float, float, float, float]]:
    """
    Parse horizontal wire lines from SVG.

    Args:
        svg_file: Path to SVG file

    Returns:
        List of (x1, y1, x2, y2) tuples
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    lines = []

    for line in root.iter('{http://www.w3.org/2000/svg}line'):
        x1 = line.get('x1')
        y1 = line.get('y1')
        x2 = line.get('x2')
        y2 = line.get('y2')

        if x1 and y1 and x2 and y2:
            lines.append((float(x1), float(y1), float(x2), float(y2)))

    return lines


def parse_st17_polylines(svg_file: str) -> List[str]:
    """
    Parse st17 polyline elements (vertical routing arrows).

    Args:
        svg_file: Path to SVG file

    Returns:
        List of points strings (e.g., "x1,y1 x2,y2 x3,y3")
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    polylines = []

    for polyline in root.iter('{http://www.w3.org/2000/svg}polyline'):
        if polyline.get('class', '') == 'st17':
            points = polyline.get('points', '').strip()
            if points:
                polylines.append(points)

    return polylines


def parse_all_polylines(svg_file: str) -> List[str]:
    """
    Parse ALL polyline elements (for routing connections).

    This includes st17 (vertical routing), st3/st4 (diagonal routing to confluence points),
    and any other polyline-based wire connections.

    IMPORTANT: Deduplicates near-identical polylines (e.g., st20/st21 outline pairs)
    that represent the same wire but with slightly different endpoints.

    Args:
        svg_file: Path to SVG file

    Returns:
        List of points strings (e.g., "x1,y1 x2,y2 x3,y3")
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    polylines = []

    for polyline in root.iter('{http://www.w3.org/2000/svg}polyline'):
        points = polyline.get('points', '').strip()
        if points:
            polylines.append(points)

    # Deduplicate near-identical polylines
    # Some SVGs have decorative outline pairs (e.g., st20/st21) with same path but endpoints differ by ~1 unit
    deduplicated = []
    for points_str in polylines:
        # Parse points
        parsed = []
        for p in points_str.split():
            if ',' in p:
                x, y = p.split(',')
                parsed.append((float(x), float(y)))

        if len(parsed) < 2:
            continue

        # Check if this polyline is a near-duplicate of an existing one
        is_duplicate = False
        for existing_str in deduplicated:
            existing_parsed = []
            for p in existing_str.split():
                if ',' in p:
                    x, y = p.split(',')
                    existing_parsed.append((float(x), float(y)))

            # Compare: same length, same start, same intermediate points, close end
            if len(parsed) == len(existing_parsed):
                # Check start point (within 2 units)
                start_dist = abs(parsed[0][0] - existing_parsed[0][0]) + abs(parsed[0][1] - existing_parsed[0][1])
                if start_dist > 2:
                    continue

                # Check intermediate points (within 2 units each)
                all_intermediates_match = True
                for i in range(1, len(parsed) - 1):
                    dist = abs(parsed[i][0] - existing_parsed[i][0]) + abs(parsed[i][1] - existing_parsed[i][1])
                    if dist > 2:
                        all_intermediates_match = False
                        break

                if not all_intermediates_match:
                    continue

                # Check end point (within 2 units)
                end_dist = abs(parsed[-1][0] - existing_parsed[-1][0]) + abs(parsed[-1][1] - existing_parsed[-1][1])
                if end_dist <= 2:
                    is_duplicate = True
                    break

        if not is_duplicate:
            deduplicated.append(points_str)

    return deduplicated


def parse_st17_paths(svg_file: str) -> List[str]:
    """
    Parse st17 path elements (ground connection arrows).

    Args:
        svg_file: Path to SVG file

    Returns:
        List of d attribute strings
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    paths = []

    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        if path.get('class', '') == 'st17':
            d = path.get('d', '').strip()
            if d:
                paths.append(d)

    return paths


def parse_st1_paths(svg_file: str) -> List[str]:
    """
    Parse st1 path elements (white routing wires).

    Args:
        svg_file: Path to SVG file

    Returns:
        List of d attribute strings
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    paths = []

    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        if path.get('class', '') == 'st1':
            d = path.get('d', '').strip()
            if d:
                paths.append(d)

    return paths


def parse_routing_paths(svg_file: str, path_classes: List[str] = None, only_l_shaped: bool = True) -> List[str]:
    """
    Parse routing path elements by class names.

    Args:
        svg_file: Path to SVG file
        path_classes: List of class names to parse (e.g., ['st3', 'st4'])
                     If None, defaults to ['st3', 'st4']
        only_l_shaped: If True, only return paths with vertical segments (v/V commands)
                      to filter out horizontal-only paths that duplicate wire specs

    Returns:
        List of d attribute strings
    """
    if path_classes is None:
        path_classes = ['st3', 'st4']

    tree = ET.parse(svg_file)
    root = tree.getroot()

    paths = []

    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        cls = path.get('class', '')
        if cls in path_classes:
            d = path.get('d', '').strip()
            if d:
                # Filter: only include L-shaped paths (those with vertical segments)
                # This prevents duplicates from horizontal-only st3 paths
                if only_l_shaped:
                    if 'v' in d or 'V' in d:
                        paths.append(d)
                else:
                    paths.append(d)

    return paths


def extract_path_all_points(d_attr: str) -> list:
    """
    Extract all significant points from an SVG path d attribute.

    Returns a list of (x, y) tuples representing all points along the path.

    Args:
        d_attr: SVG path d attribute string

    Returns:
        List of (x, y) tuples, or empty list if parsing fails
    """
    import re

    try:
        commands = re.findall(r'[MmLlHhVvCcSsQqTtAaZz][^MmLlHhVvCcSsQqTtAaZz]*', d_attr)

        if not commands:
            return []

        # Parse first command (should be M or m)
        first_cmd = commands[0].strip()
        if first_cmd[0] not in ['M', 'm']:
            return []

        # Extract start coordinates from M command
        coords = re.findall(r'-?\d+\.?\d*', first_cmd)
        if len(coords) < 2:
            return []

        start_x, start_y = float(coords[0]), float(coords[1])
        current_x, current_y = start_x, start_y

        points = [(current_x, current_y)]

        # Process subsequent commands
        for cmd_str in commands[1:]:
            cmd = cmd_str[0]
            params = re.findall(r'-?\d+\.?\d*', cmd_str[1:])

            if cmd == 'M':  # Absolute moveto
                if len(params) >= 2:
                    current_x, current_y = float(params[0]), float(params[1])
                    points.append((current_x, current_y))
            elif cmd == 'm':  # Relative moveto
                if len(params) >= 2:
                    current_x += float(params[0])
                    current_y += float(params[1])
                    points.append((current_x, current_y))
            elif cmd == 'L':  # Absolute lineto
                if len(params) >= 2:
                    current_x, current_y = float(params[-2]), float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'l':  # Relative lineto
                if len(params) >= 2:
                    current_x += float(params[-2])
                    current_y += float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'H':  # Absolute horizontal
                if len(params) >= 1:
                    current_x = float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'h':  # Relative horizontal
                if len(params) >= 1:
                    current_x += float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'V':  # Absolute vertical
                if len(params) >= 1:
                    current_y = float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'v':  # Relative vertical
                if len(params) >= 1:
                    current_y += float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'C':  # Absolute cubic bezier
                if len(params) >= 6:
                    current_x, current_y = float(params[-2]), float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'c':  # Relative cubic bezier
                if len(params) >= 6:
                    current_x += float(params[-2])
                    current_y += float(params[-1])
                    points.append((current_x, current_y))
            elif cmd in ['Z', 'z']:  # Close path
                current_x, current_y = start_x, start_y
                points.append((current_x, current_y))

        return points

    except Exception:
        return []


def extract_path_endpoints(d_attr: str) -> tuple:
    """
    Extract start and end coordinates from an SVG path d attribute.

    Supports basic path commands: M (moveto), L/l (lineto), H/h (horizontal),
    V/v (vertical), C/c (cubic bezier), and Z/z (closepath).

    Args:
        d_attr: SVG path d attribute string

    Returns:
        Tuple of (start_x, start_y, end_x, end_y) or None if parsing fails
    """
    import re

    try:
        # Remove extra whitespace and split by command letters
        commands = re.findall(r'[MmLlHhVvCcSsQqTtAaZz][^MmLlHhVvCcSsQqTtAaZz]*', d_attr)

        if not commands:
            return None

        # Parse first command (should be M or m)
        first_cmd = commands[0].strip()
        if first_cmd[0] not in ['M', 'm']:
            return None

        # Extract start coordinates from M command
        coords = re.findall(r'-?\d+\.?\d*', first_cmd)
        if len(coords) < 2:
            return None

        start_x, start_y = float(coords[0]), float(coords[1])
        current_x, current_y = start_x, start_y

        # Process subsequent commands to find end point
        for cmd_str in commands[1:]:
            cmd = cmd_str[0]
            params = re.findall(r'-?\d+\.?\d*', cmd_str[1:])

            if cmd == 'M':  # Absolute moveto
                if len(params) >= 2:
                    current_x, current_y = float(params[0]), float(params[1])
            elif cmd == 'm':  # Relative moveto
                if len(params) >= 2:
                    current_x += float(params[0])
                    current_y += float(params[1])
            elif cmd == 'L':  # Absolute lineto
                if len(params) >= 2:
                    current_x, current_y = float(params[-2]), float(params[-1])
            elif cmd == 'l':  # Relative lineto
                if len(params) >= 2:
                    current_x += float(params[-2])
                    current_y += float(params[-1])
            elif cmd == 'H':  # Absolute horizontal
                if len(params) >= 1:
                    current_x = float(params[-1])
            elif cmd == 'h':  # Relative horizontal
                if len(params) >= 1:
                    current_x += float(params[-1])
            elif cmd == 'V':  # Absolute vertical
                if len(params) >= 1:
                    current_y = float(params[-1])
            elif cmd == 'v':  # Relative vertical
                if len(params) >= 1:
                    current_y += float(params[-1])
            elif cmd == 'C':  # Absolute cubic bezier
                if len(params) >= 6:
                    current_x, current_y = float(params[-2]), float(params[-1])
            elif cmd == 'c':  # Relative cubic bezier
                if len(params) >= 6:
                    current_x += float(params[-2])
                    current_y += float(params[-1])
            elif cmd in ['Z', 'z']:  # Close path
                current_x, current_y = start_x, start_y

        return (start_x, start_y, current_x, current_y)

    except Exception:
        return None


def extract_wire_specs(text_elements: List[TextElement]) -> List[WireSpec]:
    """
    Extract wire specifications from text elements.

    Args:
        text_elements: List of TextElement objects

    Returns:
        List of WireSpec objects
    """
    from connector_finder import is_wire_spec, parse_wire_spec

    wire_specs = []

    for elem in text_elements:
        if is_wire_spec(elem.content):
            parsed = parse_wire_spec(elem.content)
            if parsed:
                diameter, color = parsed
                wire_specs.append(WireSpec(diameter, color, elem.x, elem.y))

    return wire_specs


def map_splice_positions_to_dots(
    text_elements: List[TextElement],
    dots: List[Tuple[float, float]],
    max_distance: float = 35
) -> List[TextElement]:
    """
    Map splice point labels (SP*) to their dot positions.

    Some splice points have labels offset from their actual position.
    This function corrects the position by finding the nearest dot.

    Args:
        text_elements: List of TextElement objects
        dots: List of dot (x, y) coordinates
        max_distance: Maximum distance to consider

    Returns:
        List of TextElement objects with corrected positions
    """
    from connector_finder import is_splice_point

    corrected_elements = []

    for elem in text_elements:
        if is_splice_point(elem.content):
            # Find nearest dot
            nearest_dot = None
            min_dist = float('inf')

            for dot_x, dot_y in dots:
                dist = math.sqrt((elem.x - dot_x)**2 + (elem.y - dot_y)**2)
                if dist < max_distance and dist < min_dist:
                    min_dist = dist
                    nearest_dot = (dot_x, dot_y)

            if nearest_dot:
                # Use dot position instead of label position
                corrected_elements.append(
                    TextElement(elem.content, nearest_dot[0], nearest_dot[1])
                )
            else:
                # Keep original position
                corrected_elements.append(elem)
        else:
            # Not a splice point - keep as is
            corrected_elements.append(elem)

    return corrected_elements


def generate_ids_for_unlabeled_splices(
    text_elements: List[TextElement],
    dots: List[Tuple[float, float]],
    id_generator: IDGenerator,
    max_distance: float = 35
) -> List[TextElement]:
    """
    Generate custom IDs for splice dots that don't have labels.

    This handles edge cases where circuit diagrams contain splice points (dots)
    without accompanying SP* labels. Custom IDs are generated in format SP_CUSTOM_001.

    Args:
        text_elements: Existing text elements (should already be mapped to dots)
        dots: All splice dot positions from parse_splice_dots()
        id_generator: IDGenerator instance for creating custom IDs
        max_distance: Maximum distance to consider a label as associated with a dot (default: 35)

    Returns:
        Augmented list of text elements including generated IDs for unlabeled dots
    """
    from connector_finder import is_splice_point

    # Collect all labeled splice positions (after map_splice_positions_to_dots)
    labeled_positions = []
    for elem in text_elements:
        if is_splice_point(elem.content):
            labeled_positions.append((elem.x, elem.y))

    # Find unlabeled dots
    unlabeled_dots = []
    for dot_x, dot_y in dots:
        # Check if this dot has a label positioned on or very near it
        has_label = False
        for label_x, label_y in labeled_positions:
            dist = math.sqrt((dot_x - label_x)**2 + (dot_y - label_y)**2)
            if dist < max_distance:
                has_label = True
                break

        if not has_label:
            unlabeled_dots.append((dot_x, dot_y))

    # Generate IDs for unlabeled dots
    result = list(text_elements)  # Copy existing elements

    for dot_x, dot_y in unlabeled_dots:
        custom_id = id_generator.get_or_create_splice_id(dot_x, dot_y)
        result.append(TextElement(custom_id, dot_x, dot_y))

    return result


def parse_horizontal_colored_wires(svg_file: str) -> List['HorizontalWireSegment']:
    """
    Parse horizontal colored wire segments from SVG.

    These are represented as <line> or <path> elements with colored stroke classes
    (st8-st31) and represent horizontal routing wires in grid-based diagrams.

    Args:
        svg_file: Path to SVG file

    Returns:
        List of HorizontalWireSegment objects
    """
    from models import HorizontalWireSegment

    tree = ET.parse(svg_file)
    root = tree.getroot()

    # CSS class to standard wire color code mapping
    COLOR_MAP = {
        'st5': 'BU',      # #0000F8 - Blue
        'st6': 'BUDK',    # #083A94 - Blue/Dark blue
        'st7': 'BK',      # #000000 - Black
        'st8': 'GN',      # #00B42B - Green
        'st9': 'PU',      # #A54CFF - Purple
        'st10': 'GY',     # #B3B3B3 - Gray
        'st11': 'BK',     # #000000 - Black
        'st12': 'BN',     # #804000 - Brown
        'st19': 'YE',     # #FFFF25 - Yellow
        'st21': 'RD',     # #FF0000 - Red
        'st22': 'BK',     # #000000 - Black
        'st23': 'GN',     # #00B42B - Green
        'st24': 'WH',     # #FFFFFF - White
        'st26': 'PU',     # #A54CFF - Purple
        'st27': 'BU',     # #0000F8 - Blue
        'st28': 'BN',     # #804000 - Brown
        'st29': 'RD',     # #FF0000 - Red
        'st30': 'YE',     # #FFFF25 - Yellow
        'st31': 'YE',     # #FFFF25 - Yellow
    }

    segments = []

    # Parse <line> elements
    for line in root.iter('{http://www.w3.org/2000/svg}line'):
        cls = line.get('class', '')
        if cls in COLOR_MAP:
            x1 = float(line.get('x1', 0))
            y1 = float(line.get('y1', 0))
            x2 = float(line.get('x2', 0))
            y2 = float(line.get('y2', 0))

            # Only keep horizontal lines (y1 ≈ y2)
            if abs(y1 - y2) < 1.0:
                segments.append(HorizontalWireSegment(
                    x1=min(x1, x2),
                    x2=max(x1, x2),
                    y=(y1 + y2) / 2,
                    color_class=cls,
                    color_name=COLOR_MAP[cls]
                ))

    # Parse <path> elements (some horizontal wires are paths)
    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        cls = path.get('class', '')
        if cls in COLOR_MAP:
            d = path.get('d', '').strip()
            if not d:
                continue

            # Extract horizontal paths
            # Format: M x,y c dx,dy,... or M x,y H x2 or M x,y h dx
            match_m = re.match(r'M([\d.]+),([\d.]+)', d)
            if not match_m:
                continue

            x1 = float(match_m.group(1))
            y1 = float(match_m.group(2))

            # Check for horizontal command (H or h)
            match_h = re.search(r'[Hh]([\d.]+)', d)
            if match_h:
                if 'H' in d:  # Absolute
                    x2 = float(match_h.group(1))
                else:  # Relative
                    x2 = x1 + float(match_h.group(1))

                segments.append(HorizontalWireSegment(
                    x1=min(x1, x2),
                    x2=max(x1, x2),
                    y=y1,
                    color_class=cls,
                    color_name=COLOR_MAP[cls]
                ))

            # Check for cubic bezier horizontal path (c dx,0,...)
            # Pattern: M x,y c dx,0,dx2,0,dx3,0
            elif 'c' in d.lower():
                # Extract the 'c' command parameters
                match_c = re.search(r'c([\d.,\s]+)', d)
                if match_c:
                    params = match_c.group(1).replace(',', ' ').split()
                    if len(params) >= 6:
                        # Parse cubic bezier: c dx1,dy1,dx2,dy2,dx,dy
                        dx = float(params[4])
                        dy = float(params[5])

                        # Check if it's horizontal (dy ≈ 0)
                        if abs(dy) < 1.0:
                            x2 = x1 + dx
                            segments.append(HorizontalWireSegment(
                                x1=min(x1, x2),
                                x2=max(x1, x2),
                                y=y1,
                                color_class=cls,
                                color_name=COLOR_MAP[cls]
                            ))

    return segments


def parse_vertical_dashed_wires(svg_file: str) -> List['VerticalWireSegment']:
    """
    Parse vertical dashed wire segments from SVG.

    These are represented as <path class="st16"> elements with vertical 'c' commands
    and represent vertical routing wires in grid-based diagrams.

    Args:
        svg_file: Path to SVG file

    Returns:
        List of VerticalWireSegment objects
    """
    from models import VerticalWireSegment

    tree = ET.parse(svg_file)
    root = tree.getroot()

    segments = []

    # Parse st16 path elements
    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        cls = path.get('class', '')
        if cls != 'st16':
            continue

        d = path.get('d', '').strip()
        if not d:
            continue

        # Extract vertical paths
        # Format: M x,y c 0,dy1,0,dy2,0,dy
        match_m = re.match(r'M([\d.]+),([\d.]+)', d)
        if not match_m:
            continue

        x = float(match_m.group(1))
        y1 = float(match_m.group(2))

        # Check for cubic bezier vertical path (c 0,dy,...)
        # Pattern: M x,y c 0,dy1,0,dy2,0,dy
        match_c = re.search(r'c([\d.,\s]+)', d)
        if match_c:
            params = match_c.group(1).replace(',', ' ').split()
            if len(params) >= 6:
                # Parse cubic bezier: c dx1,dy1,dx2,dy2,dx,dy
                dx = float(params[4])
                dy = float(params[5])

                # Check if it's vertical (dx ≈ 0)
                if abs(dx) < 1.0:
                    y2 = y1 + dy
                    segments.append(VerticalWireSegment(
                        x=x,
                        y1=min(y1, y2),
                        y2=max(y1, y2),
                        color_class='st16',
                        color_name='dashed'
                    ))

    return segments
