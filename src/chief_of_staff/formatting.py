"""Render untrusted agent Markdown without embedded HTML or remote images."""
from markdown_it import MarkdownIt
from markupsafe import Markup
import re

_renderer = MarkdownIt('commonmark', {'html': False, 'breaks': False}).disable('image')

def render_markdown(value):
    text = str(value or '')
    # Presentation only; preserve the stored agent response and source snapshots.
    text = re.sub(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]', '', text)
    text = re.sub(r'(?im)^#{1,6}\s+(?:summary digest)\s*\n', '', text)
    text = re.sub(r'(?m)^(#{1,6})[ \t]+', r'\1 ', text)
    return Markup(_renderer.render(text.strip()))


def source_preview(value):
    """Readable display excerpt; original snapshot remains available unchanged."""
    import re
    from html import unescape
    text = unescape(str(value or ''))
    text = re.sub(r'https?://[^\s\]<>]+', '', text)
    text = re.sub(r'\[\s*\]', '', text)
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and line.lower() not in {'jira logo','avatar','view work item','download on the app store','get it on google play'}]
    text = '\n'.join(lines)
    return text[:1800] + ('…' if len(text)>1800 else '')
