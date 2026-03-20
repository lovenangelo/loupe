import re
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name="render_code")
def render_code(value):
    """Convert markdown code blocks and inline code to HTML."""
    text = escape(value)

    # Fenced code blocks: ```lang\n...\n```
    text = re.sub(
        r"```(\w*)\n(.*?)```",
        lambda m: (
            f'<pre class="bg-muted rounded-md p-3 overflow-x-auto my-2">'
            f'<code class="text-sm font-mono text-foreground">{m.group(2).rstrip()}</code></pre>'
        ),
        text,
        flags=re.DOTALL,
    )

    # Inline code: `code`
    text = re.sub(
        r"`([^`]+)`",
        r'<code class="bg-muted text-sm font-mono px-1.5 py-0.5 rounded">\1</code>',
        text,
    )

    return mark_safe(text)
