---
name: markitdown
description: Converts Office documents (Word .docx, Excel .xlsx, PowerPoint .pptx), PDF files, audio/transcripts, HTML, and other rich formats to Markdown for easy reading and analysis.
---

# MarkItDown Document Converter

Use this skill whenever you need to read, analyze, or extract content from non-plain-text documents such as PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), HTML, or image/audio metadata into clean Markdown format.

## Supported Formats
- **PDF**: `.pdf`
- **Microsoft Word**: `.docx`
- **Microsoft Excel**: `.xlsx`, `.xls`
- **Microsoft PowerPoint**: `.pptx`
- **HTML / Web pages**: `.html`, `.htm`
- **Text & Code**: `.csv`, `.json`, `.xml`, etc.
- **Audio / Media**: Metadata and transcripts (with speech plugins)

## How to Execute

### Option 1: Run via helper script (Recommended)
```powershell
g:\@Autosar\xcp\xcp_driver\xcptool\.venv\Scripts\python.exe g:\@Autosar\xcp\xcp_driver\.agents\skills\markitdown\scripts\convert.py "<path_to_file>" -o "<path_to_output.md>"
```
Or directly output to terminal / stream:
```powershell
g:\@Autosar\xcp\xcp_driver\xcptool\.venv\Scripts\python.exe g:\@Autosar\xcp\xcp_driver\.agents\skills\markitdown\scripts\convert.py "<path_to_file>"
```

### Option 2: Run via MarkItDown CLI
```powershell
g:\@Autosar\xcp\xcp_driver\xcptool\.venv\Scripts\markitdown.exe "<path_to_file>" -o "<path_to_output.md>"
```

### Option 3: Python in-memory usage
```python
from markitdown import MarkItDown

md = MarkItDown()
result = md.convert("<path_to_file>")
markdown_text = result.text_content
```

## Workflow when encountering document files
1. Detect document format (`.docx`, `.xlsx`, `.pdf`, `.pptx`).
2. Convert file to markdown using the command above into a temporary or artifact file.
3. Read the generated markdown using `view_file` to analyze tables, figures, texts, and structures accurately.
