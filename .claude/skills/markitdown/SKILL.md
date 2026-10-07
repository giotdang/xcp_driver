---
name: markitdown
description: Converts Office documents (Word .docx, Excel .xlsx, PowerPoint .pptx), PDF files, HTML, and other rich formats to Markdown for analysis.
---

# MarkItDown Document Converter Skill

Use this skill whenever you need to read, analyze, or extract content from non-plain-text documents such as PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), HTML, or media metadata into Markdown format.

## Supported Formats
- **PDF**: `.pdf`
- **Microsoft Word**: `.docx`
- **Microsoft Excel**: `.xlsx`, `.xls`
- **Microsoft PowerPoint**: `.pptx`
- **HTML / Web pages**: `.html`, `.htm`
- **Audio / Media**: Metadata and transcripts

## Execution Commands

### Convert to Markdown file:
```powershell
g:\@Autosar\xcp\xcp_driver\xcptool\.venv\Scripts\python.exe g:\@Autosar\xcp\xcp_driver\.agents\skills\markitdown\scripts\convert.py "<path_to_file>" -o "<path_to_output.md>"
```

### Direct CLI usage:
```powershell
g:\@Autosar\xcp\xcp_driver\xcptool\.venv\Scripts\markitdown.exe "<path_to_file>" -o "<path_to_output.md>"
```
