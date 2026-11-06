"""gunicorn 入口：gunicorn 'foot_web.wsgi:app'"""
from . import create_app

app = create_app()
# gunicorn每个worker均可检查计划；flock与SQLite触发唯一键保证不重复派发。
app.extensions['scheduler'].start()
