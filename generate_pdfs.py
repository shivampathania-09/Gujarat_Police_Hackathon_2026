import os
import re
import subprocess
import markdown

WORKSPACE_DIR = os.path.abspath(os.path.dirname(__file__))
DOCS_DIR = os.path.join(WORKSPACE_DIR, "docs")

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

BROWSER_PATH = None
for path in CHROME_PATHS:
    if os.path.exists(path):
        BROWSER_PATH = path
        break

if not BROWSER_PATH:
    raise RuntimeError("Neither Chrome nor Edge browser was found on system.")

print(f"Using browser: {BROWSER_PATH}")

HLD_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

@page {
    size: A4 portrait;
    margin: 16mm 14mm 16mm 14mm;
    @bottom-right {
        content: counter(page);
    }
}

body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.5;
    color: #1e293b;
    background: #ffffff;
    margin: 0;
    padding: 0;
}

h1, h2, h3, h4, h5, h6 {
    color: #0f172a;
    font-weight: 700;
    margin-top: 1.2em;
    margin-bottom: 0.4em;
    page-break-after: avoid;
}

h1 {
    font-size: 18pt;
    border-bottom: 2px solid #0284c7;
    padding-bottom: 6px;
    margin-top: 0;
    color: #0369a1;
}

h2 {
    font-size: 14pt;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 4px;
    color: #0f172a;
}

h3 {
    font-size: 11pt;
    color: #1e293b;
}

p {
    margin: 0.5em 0;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 1em 0;
    font-size: 8.5pt;
    page-break-inside: avoid;
}

th, td {
    border: 1px solid #cbd5e1;
    padding: 5px 8px;
    text-align: left;
    vertical-align: top;
}

th {
    background-color: #f1f5f9;
    color: #0f172a;
    font-weight: 600;
}

tr:nth-child(even) {
    background-color: #f8fafc;
}

code {
    font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
    font-size: 8.5pt;
    background-color: #f1f5f9;
    color: #0284c7;
    padding: 2px 4px;
    border-radius: 4px;
    border: 1px solid #e2e8f0;
}

pre {
    background-color: #0b1329;
    color: #e2e8f0;
    padding: 10px 12px;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 8pt;
    line-height: 1.35;
    page-break-inside: avoid;
    border: 1px solid #1e293b;
}

pre code {
    background-color: transparent;
    color: inherit;
    padding: 0;
    border: none;
    font-size: inherit;
}

blockquote {
    border-left: 4px solid #0284c7;
    background-color: #f0f9ff;
    margin: 0.8em 0;
    padding: 6px 12px;
    border-radius: 0 4px 4px 0;
    color: #0369a1;
    font-size: 9pt;
}

blockquote p {
    margin: 0.2em 0;
}

hr {
    border: none;
    border-top: 1px solid #e2e8f0;
    margin: 1.5em 0;
}

ul, ol {
    margin: 0.5em 0;
    padding-left: 1.3em;
}

li {
    margin: 0.25em 0;
}

.mermaid {
    display: flex;
    justify-content: center;
    margin: 1em 0;
    page-break-inside: avoid;
}
"""

SLIDE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

@page {
    size: A4 landscape;
    margin: 10mm 12mm 10mm 12mm;
}

body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 9pt;
    line-height: 1.4;
    color: #0f172a;
    background: #ffffff;
    margin: 0;
    padding: 0;
}

.slide {
    page-break-after: always;
    min-height: 175mm;
    max-height: 185mm;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
}

.slide:last-child {
    page-break-after: avoid;
}

h1 {
    font-size: 15pt;
    color: #0369a1;
    border-bottom: 2px solid #0284c7;
    padding-bottom: 4px;
    margin-top: 0;
    margin-bottom: 6px;
}

h2 {
    font-size: 12pt;
    color: #0f172a;
    margin-top: 4px;
    margin-bottom: 4px;
}

h3 {
    font-size: 10pt;
    color: #1e293b;
    margin-top: 4px;
    margin-bottom: 3px;
}

p {
    margin: 0.3em 0;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.4em 0;
    font-size: 7.5pt;
}

th, td {
    border: 1px solid #cbd5e1;
    padding: 4px 6px;
    text-align: left;
    vertical-align: top;
}

th {
    background-color: #f1f5f9;
    color: #0f172a;
    font-weight: 600;
}

tr:nth-child(even) {
    background-color: #f8fafc;
}

code {
    font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
    font-size: 7.5pt;
    background-color: #f1f5f9;
    color: #0284c7;
    padding: 1px 3px;
    border-radius: 3px;
}

pre {
    background-color: #0b1329;
    color: #f8fafc;
    padding: 6px 8px;
    border-radius: 4px;
    overflow-x: auto;
    font-size: 6.8pt;
    line-height: 1.25;
    margin: 0.3em 0;
}

pre code {
    background-color: transparent;
    color: inherit;
    padding: 0;
    border: none;
    font-size: inherit;
}

blockquote {
    border-left: 3px solid #0284c7;
    background-color: #f0f9ff;
    margin: 0.4em 0;
    padding: 4px 8px;
    border-radius: 0 4px 4px 0;
    color: #0369a1;
    font-size: 8pt;
}

blockquote p {
    margin: 0.1em 0;
}

hr {
    display: none;
}

ul, ol {
    margin: 0.3em 0;
    padding-left: 1.2em;
}

li {
    margin: 0.15em 0;
}
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        {css}
    </style>
</head>
<body>
    {content}
</body>
</html>
"""

def clean_math(text: str) -> str:
    # Convert LaTeX symbols to clean unicode
    text = text.replace(r'\%', '%')
    text = text.replace(r'\times', '×')
    text = text.replace(r'\rightarrow', '→')
    text = text.replace(r'\approx', '≈')
    text = text.replace(r'\mathbf', '')
    text = text.replace(r'\parallel', ' || ')
    text = text.replace(r'\left(', '(')
    text = text.replace(r'\right)', ')')
    text = text.replace(r'\dots', '...')
    
    text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\$\$([^$]+)\$\$', r'<div style="text-align:center;margin:6px 0;"><strong>\1</strong></div>', text)
    text = re.sub(r'\$([^$]+)\$', r'<strong>\1</strong>', text)
    return text

def convert_hld(md_path: str) -> str:
    with open(md_path, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    clean_text = clean_math(raw_text)
    md = markdown.Markdown(extensions=['extra', 'tables', 'fenced_code', 'codehilite', 'toc'])
    html_content = md.convert(clean_text)

    full_html = HTML_TEMPLATE.format(title="Gujarat Police NETRANG C4I - HLD Document", css=HLD_CSS, content=html_content)
    return full_html

def convert_deck(md_path: str) -> str:
    with open(md_path, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    clean_text = clean_math(raw_text)

    # Split slides by <!-- SLIDE X -->
    slides_raw = re.split(r'<!-- SLIDE \d+ -->', clean_text)
    
    md = markdown.Markdown(extensions=['extra', 'tables', 'fenced_code', 'codehilite'])
    slide_html_parts = []
    
    for part in slides_raw:
        part = part.strip()
        if not part:
            continue
        html_part = md.convert(part)
        slide_html_parts.append(f'<div class="slide">{html_part}</div>')

    content = "\n".join(slide_html_parts)
    full_html = HTML_TEMPLATE.format(title="Gujarat Police NETRANG C4I - Presentation Deck", css=SLIDE_CSS, content=content)
    return full_html

def generate_pdf(input_html_path: str, output_pdf_path: str):
    abs_html = os.path.abspath(input_html_path).replace('\\', '/')
    file_url = f"file:///{abs_html}"
    
    cmd = [
        BROWSER_PATH,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={os.path.abspath(output_pdf_path)}",
        file_url
    ]
    
    print(f"Generating PDF: {output_pdf_path}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error output: {res.stderr}")
    else:
        print(f"Successfully generated: {output_pdf_path}")

def main():
    hld_md = os.path.join(DOCS_DIR, "HLD_DOCUMENT.md")
    hld_pdf = os.path.join(DOCS_DIR, "HLD_DOCUMENT.pdf")
    hld_html = os.path.join(DOCS_DIR, "_temp_hld.html")

    deck_md = os.path.join(DOCS_DIR, "PRESENTATION_DECK.md")
    deck_pdf = os.path.join(DOCS_DIR, "PRESENTATION_DECK.pdf")
    deck_html = os.path.join(DOCS_DIR, "_temp_deck.html")

    # Generate HLD PDF
    html_hld = convert_hld(hld_md)
    with open(hld_hld_path := hld_html, 'w', encoding='utf-8') as f:
        f.write(html_hld)
    generate_pdf(hld_html, hld_pdf)
    if os.path.exists(hld_html):
        os.remove(hld_html)

    # Generate Presentation Deck PDF
    html_deck = convert_deck(deck_md)
    with open(deck_html, 'w', encoding='utf-8') as f:
        f.write(html_deck)
    generate_pdf(deck_html, deck_pdf)
    if os.path.exists(deck_html):
        os.remove(deck_html)

if __name__ == '__main__':
    main()
