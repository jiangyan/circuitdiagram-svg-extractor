"""
Output formatting utilities for connection tables.
"""
from typing import List, Dict
from collections import defaultdict
from models import Connection


def format_markdown_table(connections: List[Connection]) -> str:
    """
    Format connections as a markdown table.

    Args:
        connections: List of Connection objects

    Returns:
        Markdown table string
    """
    # Sort connections by from_id, then from_pin
    sorted_connections = sorted(connections)

    # Build markdown table
    lines = []
    lines.append("| From | From Pin | To | To Pin | Wire DM | Color |")
    lines.append("|------|----------|-----|--------|---------|-------|")

    for conn in sorted_connections:
        line = f"| {conn.from_id} | {conn.from_pin} | {conn.to_id} | {conn.to_pin} | {conn.wire_dm} | {conn.wire_color} |"
        lines.append(line)

    return "\n".join(lines)


def format_grouped_by_source(connections: List[Connection]) -> str:
    """
    Format connections grouped by source connector.

    Args:
        connections: List of Connection objects

    Returns:
        Markdown string with grouped connections
    """
    # Group connections by source connector
    groups: Dict[str, List[Connection]] = defaultdict(list)
    for conn in connections:
        groups[conn.from_id].append(conn)

    # Sort groups by connector ID
    sorted_groups = sorted(groups.items())

    lines = []
    for connector_id, conns in sorted_groups:
        lines.append(f"\n### {connector_id} ({len(conns)} connections)\n")
        lines.append("| From Pin | To | To Pin | Wire DM | Color |")
        lines.append("|----------|-----|--------|---------|-------|")

        # Sort connections within group by from_pin
        sorted_conns = sorted(conns)

        for conn in sorted_conns:
            lines.append(
                f"| {conn.from_pin} | {conn.to_id} | {conn.to_pin} | "
                f"{conn.wire_dm} | {conn.wire_color} |"
            )

    return "\n".join(lines)


def generate_report(connections: List[Connection]) -> str:
    """
    Generate a complete markdown report with all connection tables.

    Args:
        connections: List of Connection objects

    Returns:
        Complete markdown report string
    """
    lines = []

    # Header
    lines.append("# Circuit Diagram Wire Connections")
    lines.append("")
    lines.append(f"**Total Connections:** {len(connections)}")
    lines.append("")

    # All connections sorted
    lines.append("## All Connections (Sorted by From Connector)")
    lines.append("")
    lines.append(format_markdown_table(connections))
    lines.append("")

    # Grouped by source connector
    lines.append("## Connections Grouped by Source Connector")
    lines.append(format_grouped_by_source(connections))
    lines.append("")

    return "\n".join(lines)


def export_to_file(connections: List[Connection], filename: str) -> None:
    """
    Export connections to a markdown file.

    Args:
        connections: List of Connection objects
        filename: Output file path
    """
    report = generate_report(connections)

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"✓ Exported to {filename}")


def print_summary_statistics(connections: List[Connection]) -> None:
    """
    Print summary statistics about connections.

    Args:
        connections: List of Connection objects
    """
    horizontal = [c for c in connections if c.wire_dm]
    vertical = [c for c in connections if not c.wire_dm]

    print(f"\nExtracted {len(horizontal)} horizontal wire connections")
    print(f"\nExtracted {len(vertical)} vertical routing connections")
    print(f"\nTotal connections: {len(connections)} (horizontal + vertical)")
