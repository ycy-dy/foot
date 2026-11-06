"""仅渲染未发布 AI 草稿；外部内容不得直接作为可信 HTML。"""
import bleach
import markdown

TAGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'br', 'hr', 'em', 'strong', 'a', 'ul', 'ol', 'li',
        'pre', 'code', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'del'}


def render_draft(text):
    rendered = markdown.markdown(text, extensions=['tables', 'fenced_code'])
    return bleach.clean(rendered, tags=TAGS, attributes={'a': ['href', 'title'], 'td': ['align'], 'th': ['align']},
                        protocols={'http', 'https', 'mailto'}, strip=True)
