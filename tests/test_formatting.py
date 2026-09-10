from tests.helpers import make_store
from chief_of_staff.formatting import render_markdown


def test_agent_markdown_formats_headings_lists_and_emphasis():
    html=str(render_markdown('## Summary\n\n**No actions needed.**\n\n- Mail reviewed\n- Calendar checked'))
    assert '<h2>Summary</h2>' in html
    assert '<strong>No actions needed.</strong>' in html
    assert '<li>Mail reviewed</li>' in html


def test_agent_content_cannot_inject_html_or_unsafe_links():
    html=str(render_markdown('<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n![tracking](https://example.com/pixel.png)'))
    assert '<script>' not in html
    assert 'href="javascript:' not in html
    assert '<img' not in html
