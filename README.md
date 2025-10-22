# Circuit Diagram SVG Connection Extractor

Extract wire connections from circuit diagram SVG files (Adobe Illustrator exports).

## Quick Start

```bash
python extract_connections_v3.py
```

**Input:** `sample-wire.svg`
**Output:** `connections_output.md` (markdown table of all connections)

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Complete algorithm details, key insights, and design decisions
- **[wire-relation-prompt.md](wire-relation-prompt.md)** - AI prompt for processing similar SVG files

## Example Output

| From | From Pin | To | To Pin | Wire DM | Color |
|------|----------|-----|--------|---------|-------|
| MH3202C | 25 | MH2FL | 8 | 0.35 | WH/RD |
| MH3202C | 26 | MH2FL | 9 | 0.35 | BU/BK |
| MH3202E | 8 | MH2FL | 6 | 0.35 | GN/WH |
| ... | ... | ... | ... | ... | ... |

Total: 40 connections extracted from sample diagram.

## Files

- `extract_connections_v3.py` - Main extraction script
- `sample-wire.svg` - Example circuit diagram (Adobe Illustrator)
- `diagram.png` - Visual reference
- `connections_output.md` - Generated connection table
- `CLAUDE.md` - Complete technical documentation
- `wire-relation-prompt.md` - AI prompt for similar tasks

## Key Features

 Wire-centric algorithm (not boundary-based)
 Handles junction connectors (MH2FL/FL2MH, FTL2FL/FL2FTL)
 Multiple connector instances of same type
 Sorted output by connector ID
 Automatic deduplication

## Requirements

- Python 3.7+
- Standard library only (no external dependencies)
