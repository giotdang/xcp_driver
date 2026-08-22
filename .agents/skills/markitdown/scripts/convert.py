"""Helper script to convert documents (PDF, DOCX, XLSX, PPTX, HTML, etc.) to Markdown using MarkItDown."""

import argparse
import sys
from pathlib import Path
from markitdown import MarkItDown


def convert_file(input_path: str, output_path: str | None = None) -> str:
    md = MarkItDown()
    result = md.convert(input_path)
    content = result.text_content

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(content, encoding="utf-8")
        print(f"Successfully converted '{input_path}' -> '{output_path}'")
    else:
        print(content)
    return content


def main():
    parser = argparse.ArgumentParser(description="Convert documents to Markdown using MarkItDown")
    parser.add_argument("input", help="Path to input document (PDF, Word, Excel, PowerPoint, etc.)")
    parser.add_argument("-o", "--output", help="Path to output markdown file (optional, default: stdout)")
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    convert_file(args.input, args.output)


if __name__ == "__main__":
    main()
