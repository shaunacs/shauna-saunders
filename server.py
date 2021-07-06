"""Server for Shauna Saunders personal website"""

from flask import Flask, redirect, render_template

app = Flask(__name__)
app.secret_key = "dev"

@app.route('/')
def render_homepage():
    """Renders the homepage"""

    return render_template('homepage.html')


if __name__ == '__main__':
    app.run(debug=True, use_reloader=True, use_debugger=True)