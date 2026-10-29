import re
from typing import List, Dict, Any


def strip_css_at_rules(text: str) -> str:
    """
    Robustly removes @media and other at-rules even with nested braces,
    without regex catastrophic backtracking.
    """
    if not text:
        return ''
    idx = 0
    while True:
        m = re.search(r'@(?:media|supports)\b[^{]*\{', text[idx:], flags=re.IGNORECASE)
        if not m:
            break
        start = idx + m.start()
        brace_start = idx + m.end() - 1
        brace_count = 1
        curr = brace_start + 1
        while curr < len(text) and brace_count > 0:
            if text[curr] == '{':
                brace_count += 1
            elif text[curr] == '}':
                brace_count -= 1
            curr += 1
        if brace_count == 0:
            text = text[:start] + ' ' + text[curr:]
            idx = start
        else:
            idx = brace_start + 1

    # Remove non-nested at-rules like @font-face, @keyframes, @import
    text = re.sub(r'@(?:font-face|keyframes|import)[^{;]+(?:\{[^{}]*\}|;)', '', text, flags=re.IGNORECASE)
    return text


def clean_leaked_css_from_text(text: str) -> str:
    """
    Removes leaked raw CSS blocks (e.g., #outlook a, body { ... }, table, td { ... })
    that got dumped into plain text email content due to tag-stripping.
    Preserves actual email content and formatting.
    """
    if not text:
        return ''

    # 1. Remove nested @media / @supports queries
    text = strip_css_at_rules(text)

    # 2. Known CSS declarations to match inside rule blocks
    css_props = (
        'margin', 'padding', 'border', 'color', 'background', 'font', 'width', 'height',
        'display', 'text-align', 'line-height', 'overflow', 'outline', 'mso', 'webkit',
        '-ms-', 'text-size-adjust', 'border-collapse', 'box-sizing', 'letter-spacing',
        'text-decoration', 'vertical-align', 'white-space'
    )

    def replacer(match):
        content = match.group(0)
        low = content.lower()
        if any(f'{p}:' in low or f'-{p}:' in low or f'{p}-' in low or f'{p} ' in low for p in css_props):
            return ' '
        return content

    # Standard selector { declaration } patterns up to 500 chars per rule
    rule_re = re.compile(r'[^\n\r<>{;]{1,120}\{[^{}]{1,600}\}')
    for _ in range(8):
        new_text = rule_re.sub(replacer, text)
        if new_text == text:
            break
        text = new_text

    # Specific Outlook reset leftovers
    text = re.sub(r'#outlook[^\n\r{]*\{[^{}]*\}', '', text, flags=re.IGNORECASE)
    # Empty selectors or classes
    text = re.sub(r'^\s*[-a-zA-Z0-9_.]+\s*\{\s*\}\s*$', '', text, flags=re.MULTILINE)
    # Clean excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def clean_leaked_css_from_html(html: str) -> str:
    """
    Cleans raw CSS text that leaked outside HTML tags (for example at the top of an email
    before the first HTML container element).
    """
    if not html:
        return ''

    # 1. Remove Outlook CSS reset block if present before or around HTML
    outlook_pattern = r'#outlook\s*a\s*\{.*?(?:img\s*\{[^}]*\}|\}\s*(?=<))'
    html = re.sub(outlook_pattern, '', html, flags=re.DOTALL | re.IGNORECASE)

    # 2. Clean prefix text before the first HTML tag
    m = re.search(r'<\w+', html)
    if m:
        first_tag_pos = m.start()
        prefix = html[:first_tag_pos]
        clean_prefix = clean_leaked_css_from_text(prefix)
        # Recombine clean prefix with the rest of HTML
        if clean_prefix:
            html = clean_prefix + '\n' + html[first_tag_pos:]
        else:
            html = html[first_tag_pos:]

    # Clean leftover raw CSS rules if any still sit outside tags
    html = re.sub(r'(?:body|table|td|img)\s*\{[^}]*\}\s*(?=<)', '', html, flags=re.DOTALL | re.IGNORECASE)

    return html.strip()


def build_email_iframe_document(html_content: str, title: str = '') -> str:
    """
    Wraps email HTML into a complete, standalone, responsive HTML5 document
    for isolated rendering in a sandboxed <iframe>.
    Guarantees responsive scaling, external links opening in new window (_blank),
    and prevents CSS bleed into the host application.
    """
    if not html_content or not html_content.strip():
        return ''

    # Check if the HTML is already a complete <html> document
    has_html_tag = bool(re.search(r'<\s*html\b', html_content, re.IGNORECASE))
    if has_html_tag:
        # Ensure <base target="_blank"> is present so links open in new tab
        if '<base' not in html_content.lower():
            if '<head>' in html_content.lower():
                html_content = re.sub(
                    r'(<head[^>]*>)',
                    r'\1<base target="_blank">',
                    html_content,
                    count=1,
                    flags=re.IGNORECASE
                )
            else:
                html_content = f'<base target="_blank">{html_content}'
        return html_content

    escaped_title = (title or 'Email Message').replace('"', '&quot;').replace('<', '&lt;')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <base target="_blank">
  <style>
    *, *::before, *::after {{
      box-sizing: border-box;
    }}
    html, body {{
      margin: 0;
      padding: 0;
      background-color: #ffffff;
      color: #1f2937;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      font-size: 15px;
      line-height: 1.55;
      -webkit-text-size-adjust: 100%;
      -ms-text-size-adjust: 100%;
    }}
    body {{
      padding: 16px 20px;
    }}
    img {{
      max-width: 100%;
      height: auto;
      border: 0;
      vertical-align: middle;
    }}
    table {{
      border-collapse: collapse;
      mso-table-lspace: 0pt;
      mso-table-rspace: 0pt;
      max-width: 100%;
    }}
    a {{
      color: #2563eb;
    }}
    p {{
      margin-top: 0;
      margin-bottom: 1rem;
    }}
  </style>
</head>
<body>
{html_content}
</body>
</html>"""


def get_formatted_labels_list(gmail_labels: Any) -> List[Dict[str, str]]:
    """
    Parses raw Gmail labels into human-friendly badge structures with icons and clean names.
    """
    if not gmail_labels:
        return []

    if isinstance(gmail_labels, list):
        raw_list = [str(l).strip() for l in gmail_labels if str(l).strip()]
    else:
        raw_list = [l.strip() for l in str(gmail_labels).split(',') if l.strip()]

    LABEL_MAPPINGS = {
        'INBOX': {
            'display': 'Inbox',
            'badge': 'bg-primary-subtle text-primary border border-primary-subtle',
            'icon': 'bi-inbox-fill'
        },
        'UNREAD': {
            'display': 'Unread',
            'badge': 'bg-danger-subtle text-danger border border-danger-subtle',
            'icon': 'bi-envelope-fill'
        },
        'IMPORTANT': {
            'display': 'Important',
            'badge': 'bg-warning-subtle text-warning-emphasis border border-warning-subtle',
            'icon': 'bi-bookmark-star-fill'
        },
        'STARRED': {
            'display': 'Starred',
            'badge': 'bg-warning-subtle text-warning-emphasis border border-warning-subtle',
            'icon': 'bi-star-fill'
        },
        'CATEGORY_UPDATES': {
            'display': 'Updates',
            'badge': 'bg-info-subtle text-info border border-info-subtle',
            'icon': 'bi-bell-fill'
        },
        'CATEGORY_PROMOTIONS': {
            'display': 'Promotions',
            'badge': 'bg-success-subtle text-success border border-success-subtle',
            'icon': 'bi-tag-fill'
        },
        'CATEGORY_SOCIAL': {
            'display': 'Social',
            'badge': 'bg-primary-subtle text-primary border border-primary-subtle',
            'icon': 'bi-people-fill'
        },
        'CATEGORY_FORUMS': {
            'display': 'Forums',
            'badge': 'bg-secondary-subtle text-secondary border border-secondary-subtle',
            'icon': 'bi-chat-dots-fill'
        },
        'CATEGORY_PERSONAL': {
            'display': 'Personal',
            'badge': 'bg-dark-subtle text-dark border border-dark-subtle',
            'icon': 'bi-person-fill'
        },
        'SENT': {
            'display': 'Sent',
            'badge': 'bg-secondary-subtle text-secondary border border-secondary-subtle',
            'icon': 'bi-send-fill'
        },
        'SPAM': {
            'display': 'Spam',
            'badge': 'bg-danger-subtle text-danger border border-danger-subtle',
            'icon': 'bi-shield-slash-fill'
        },
        'TRASH': {
            'display': 'Trash',
            'badge': 'bg-secondary-subtle text-secondary border border-secondary-subtle',
            'icon': 'bi-trash-fill'
        },
    }

    results = []
    for l in raw_list:
        upper = l.strip().upper()
        if upper in LABEL_MAPPINGS:
            item = LABEL_MAPPINGS[upper].copy()
            item['raw'] = l
            results.append(item)
        else:
            # Clean custom user labels (e.g., Label_1 -> Label 1)
            display_name = l.replace('_', ' ').replace('-', ' ').strip().title()
            results.append({
                'display': display_name,
                'badge': 'bg-secondary-subtle text-secondary border border-secondary-subtle',
                'icon': 'bi-tag',
                'raw': l
            })

    return results
