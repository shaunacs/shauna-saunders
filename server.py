"""Server for Shauna Saunders personal website"""

from flask import Flask, redirect, render_template

app = Flask(__name__)
app.secret_key = "dev"


if __name__ = '__main__':
    connect_to_db(app)
    app.run(debug=True, use_reloader=True, use_debugger=True)