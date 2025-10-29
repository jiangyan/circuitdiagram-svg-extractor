"""
Circuit Diagram Connection Extractor

Modular architecture for extracting wire connections from Adobe Illustrator SVG files.
"""
import sys
import json
import os
from typing import Set, Tuple
from models import IDGenerator
from svg_parser import (
    parse_text_elements,
    parse_splice_dots,
    parse_st17_polylines,
    parse_all_polylines,
    parse_st17_paths,
    parse_st1_paths,
    parse_routing_paths,
    extract_path_endpoints,
    extract_path_all_points,
    extract_wire_specs,
    map_splice_positions_to_dots,
    generate_ids_for_unlabeled_splices
)
from extractors import (
    HorizontalWireExtractor,
    VerticalRoutingExtractor,
    GroundConnectionExtractor,
    deduplicate_connections
)
from output_formatter import export_to_file, print_summary_statistics


def load_exclusions(svg_file: str = None) -> Tuple[Set[Tuple[str, str]], Set[Tuple[str, str, str, str]]]:
    """
    Load optional exclusion configuration for reference-only pins and specific connections.

    Supports filename-specific exclusion configs:
    1. First tries <svg_basename>_exclusions.json (e.g., intersection_exclusions.json)
    2. Falls back to exclusions_config.json
    3. Returns empty sets if neither exists

    Args:
        svg_file: Path to SVG file (optional, for filename-specific config)

    Returns:
        Tuple of:
        - Set of (connector_id, pin) tuples to exclude (excludes ALL connections for this pin)
        - Set of (from_id, from_pin, to_id, to_pin) tuples to exclude (excludes specific connection pairs)
    """
    config_files = []

    # Try filename-specific config first
    if svg_file:
        svg_basename = os.path.splitext(os.path.basename(svg_file))[0]
        specific_config = f'{svg_basename}_exclusions.json'

        # Check in same directory as SVG
        svg_dir = os.path.dirname(svg_file)
        if svg_dir:
            specific_config_path = os.path.join(svg_dir, specific_config)
            config_files.append(specific_config_path)
        else:
            config_files.append(specific_config)

    # Fall back to global config
    config_files.append('exclusions_config.json')

    # Try each config file in order
    for config_file in config_files:
        if not os.path.exists(config_file):
            continue

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Load pin exclusions (excludes ALL connections for this pin)
            pin_exclusions = set()
            for item in config.get('exclusions', []):
                connector_id = item.get('connector_id', '')
                pin = item.get('pin', '')
                if connector_id:  # Pin can be empty for splice points
                    pin_exclusions.add((connector_id, pin))

            # Load connection pair exclusions (excludes specific connection pairs)
            connection_exclusions = set()
            for item in config.get('connection_exclusions', []):
                from_id = item.get('from_connector', '')
                from_pin = item.get('from_pin', '')
                to_id = item.get('to_connector', '')
                to_pin = item.get('to_pin', '')
                if from_id and to_id:
                    connection_exclusions.add((from_id, from_pin, to_id, to_pin))

            if pin_exclusions or connection_exclusions:
                print(f"Loaded {len(pin_exclusions)} pin exclusions and {len(connection_exclusions)} connection pair exclusions from {config_file}")

            return pin_exclusions, connection_exclusions
        except Exception as e:
            print(f"Warning: Could not load exclusions config {config_file}: {e}")
            continue

    return set(), set()


def apply_exclusions(connections, pin_exclusions: Set[Tuple[str, str]], connection_exclusions: Set[Tuple[str, str, str, str]]):
    """
    Filter out connections involving excluded pins or specific connection pairs.

    Args:
        connections: List of Connection objects
        pin_exclusions: Set of (connector_id, pin) tuples to exclude (excludes ALL connections for this pin)
        connection_exclusions: Set of (from_id, from_pin, to_id, to_pin) tuples to exclude (excludes specific pairs)

    Returns:
        Filtered list of connections
    """
    if not pin_exclusions and not connection_exclusions:
        return connections

    filtered = []
    pin_excluded_count = 0
    connection_excluded_count = 0

    for conn in connections:
        # Check if either endpoint is in pin exclusion list
        from_key = (conn.from_id, conn.from_pin)
        to_key = (conn.to_id, conn.to_pin)

        if from_key in pin_exclusions or to_key in pin_exclusions:
            pin_excluded_count += 1
            continue

        # Check if this specific connection pair is excluded
        conn_key = (conn.from_id, conn.from_pin, conn.to_id, conn.to_pin)
        if conn_key in connection_exclusions:
            connection_excluded_count += 1
            continue

        filtered.append(conn)

    if pin_excluded_count > 0:
        print(f"Excluded {pin_excluded_count} connections involving excluded pins")
    if connection_excluded_count > 0:
        print(f"Excluded {connection_excluded_count} specific connection pairs")

    return filtered


def main():
    """Main entry point for connection extraction."""
    # Allow command-line override: python extract_connections.py [input.svg] [output.md]
    svg_file = sys.argv[1] if len(sys.argv) > 1 else 'sample-wire.svg'
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'connections_output.md'

    print("=" * 80)
    print("Circuit Diagram Connection Extractor")
    print("=" * 80)

    # Load optional exclusions for reference-only pins and specific connection pairs
    # Supports filename-specific configs: <svg_basename>_exclusions.json
    pin_exclusions, connection_exclusions = load_exclusions(svg_file)

    # Initialize ID generator for unlabeled splice points
    id_generator = IDGenerator()

    # Step 1: Parse SVG elements
    print("Parsing SVG file...")
    text_elements = parse_text_elements(svg_file)
    splice_dots = parse_splice_dots(svg_file)
    st17_polylines = parse_st17_polylines(svg_file)
    all_polylines = parse_all_polylines(svg_file)
    st17_paths = parse_st17_paths(svg_file)
    st1_paths = parse_st1_paths(svg_file)
    routing_paths = parse_routing_paths(svg_file, only_l_shaped=True)  # Only TRUE L-shaped wires (with vertical segments)

    print(f"Parsed {len(text_elements)} text elements")
    print(f"Parsed {len(splice_dots)} splice point dots")
    print(f"Found {len(st17_polylines)} st17 polyline elements")
    print(f"Found {len(all_polylines)} total polyline elements (including routing)")
    print(f"Found {len(st17_paths)} st17 path elements (ground arrows)")
    print(f"Found {len(st1_paths)} st1 path elements (white routing wires)")
    print(f"Found {len(routing_paths)} st3/st4 path elements (L-shaped routing wires)")

    # Step 2: Map splice positions to dots
    text_elements = map_splice_positions_to_dots(text_elements, splice_dots)

    # Step 2b: Generate IDs for unlabeled splice points
    text_elements = generate_ids_for_unlabeled_splices(text_elements, splice_dots, id_generator)

    # Step 3: Extract wire specifications
    wire_specs = extract_wire_specs(text_elements)
    print(f"Found {len(wire_specs)} wire specifications")

    # Step 4: Extract horizontal wire connections
    print("\n" + "=" * 80)
    print("Extracting Horizontal Wire Connections")
    print("=" * 80)
    horizontal_extractor = HorizontalWireExtractor(text_elements, wire_specs, all_polylines)
    horizontal_connections = horizontal_extractor.extract_connections()
    print(f"Extracted {len(horizontal_connections)} horizontal wire connections")

    # Step 5: Extract routing connections from polylines and routing paths (st1, st3, st4)
    print("\n" + "=" * 80)
    print("Extracting Routing Connections (polylines + routing paths)")
    print("=" * 80)
    # Combine st1 and st3/st4 paths
    all_routing_paths = st1_paths + routing_paths
    routing_extractor = VerticalRoutingExtractor(all_polylines, all_routing_paths, text_elements, wire_specs, horizontal_connections)
    routing_connections = routing_extractor.extract_connections()
    print(f"Extracted {len(routing_connections)} routing connections (polylines + routing paths)")

    # Step 6: Extract ground connections
    print("\n" + "=" * 80)
    print("Extracting Ground Connections (st17 paths)")
    print("=" * 80)
    ground_extractor = GroundConnectionExtractor(st17_paths, text_elements, wire_specs, horizontal_connections)
    ground_connections = ground_extractor.extract_connections()
    print(f"Extracted {len(ground_connections)} ground connections")

    # Step 7: Combine all connections and deduplicate globally
    # (Each extractor deduplicates internally, but we need global dedup across extractors)
    combined = horizontal_connections + routing_connections + ground_connections
    all_connections = deduplicate_connections(combined)

    # Step 7b: Apply exclusions for reference-only pins and specific connection pairs
    all_connections = apply_exclusions(all_connections, pin_exclusions, connection_exclusions)

    print("\n" + "=" * 80)
    print(f"Total connections: {len(all_connections)}")
    if len(combined) > len(all_connections):
        print(f"  (Removed {len(combined) - len(all_connections)} duplicates across extractors)")
    print("=" * 80)

    # Step 8: Export to file
    export_to_file(all_connections, output_file)

    # Print summary by type
    horizontal = [c for c in all_connections if c.wire_dm]
    routing_and_ground = [c for c in all_connections if not c.wire_dm]

    print(f"\nBreakdown:")
    print(f"  - Horizontal wires (with specs): {len(horizontal)}")
    print(f"  - Routing + Ground: {len(routing_and_ground)}")


if __name__ == '__main__':
    main()
