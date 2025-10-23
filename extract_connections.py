"""
Circuit Diagram Connection Extractor

Modular architecture for extracting wire connections from Adobe Illustrator SVG files.
"""
from svg_parser import (
    parse_text_elements,
    parse_splice_dots,
    parse_st17_polylines,
    parse_st17_paths,
    extract_wire_specs,
    map_splice_positions_to_dots
)
from extractors import (
    HorizontalWireExtractor,
    VerticalRoutingExtractor,
    GroundConnectionExtractor,
    deduplicate_connections
)
from output_formatter import export_to_file, print_summary_statistics


def main():
    """Main entry point for connection extraction."""
    svg_file = 'sample-wire.svg'
    output_file = 'connections_output.md'

    print("=" * 80)
    print("Circuit Diagram Connection Extractor")
    print("=" * 80)

    # Step 1: Parse SVG elements
    print("Parsing SVG file...")
    text_elements = parse_text_elements(svg_file)
    splice_dots = parse_splice_dots(svg_file)
    polylines = parse_st17_polylines(svg_file)
    paths = parse_st17_paths(svg_file)

    print(f"Parsed {len(text_elements)} text elements")
    print(f"Parsed {len(splice_dots)} splice point dots")
    print(f"Found {len(polylines)} st17 polyline elements")
    print(f"Found {len(paths)} st17 path elements")

    # Step 2: Map splice positions to dots
    text_elements = map_splice_positions_to_dots(text_elements, splice_dots)

    # Step 3: Extract wire specifications
    wire_specs = extract_wire_specs(text_elements)
    print(f"Found {len(wire_specs)} wire specifications")

    # Step 4: Extract horizontal wire connections
    print("\n" + "=" * 80)
    print("Extracting Horizontal Wire Connections")
    print("=" * 80)
    horizontal_extractor = HorizontalWireExtractor(text_elements, wire_specs)
    horizontal_connections = horizontal_extractor.extract_connections()
    print(f"Extracted {len(horizontal_connections)} horizontal wire connections")

    # Step 5: Extract vertical routing connections
    print("\n" + "=" * 80)
    print("Extracting Vertical Routing (st17 polylines)")
    print("=" * 80)
    vertical_extractor = VerticalRoutingExtractor(polylines, text_elements)
    vertical_connections = vertical_extractor.extract_connections()
    print(f"Extracted {len(vertical_connections)} vertical routing connections")

    # Step 6: Extract ground connections
    print("\n" + "=" * 80)
    print("Extracting Ground Connections (st17 paths)")
    print("=" * 80)
    ground_extractor = GroundConnectionExtractor(paths, text_elements)
    ground_connections = ground_extractor.extract_connections()
    print(f"Extracted {len(ground_connections)} ground connections")

    # Step 7: Combine all connections
    all_connections = horizontal_connections + vertical_connections + ground_connections

    print("\n" + "=" * 80)
    print(f"Total connections: {len(all_connections)}")
    print("=" * 80)

    # Step 8: Export to file
    export_to_file(all_connections, output_file)

    # Print summary by type
    horizontal = [c for c in all_connections if c.wire_dm]
    vertical_and_ground = [c for c in all_connections if not c.wire_dm]

    print(f"\nBreakdown:")
    print(f"  - Horizontal wires (with specs): {len(horizontal)}")
    print(f"  - Vertical routing + Ground: {len(vertical_and_ground)}")


if __name__ == '__main__':
    main()
