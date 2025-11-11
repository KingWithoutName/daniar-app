from flask import Flask
from flask_migrate import Migrate
from daniar_app import create_app, db

app = create_app()
migrate = Migrate(app, db)

# Ini penting agar perintah `flask db` dikenali
from flask.cli import with_appcontext
import click

@app.cli.command("hello")
@with_appcontext
def hello():
    click.echo("Hello from Flask CLI!")
