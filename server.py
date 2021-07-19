"""Server for Shauna Saunders personal website"""

from flask import Flask, redirect, render_template

app = Flask(__name__)
app.secret_key = "dev"

@app.route('/')
def render_homepage():
    """Renders the homepage"""

    return render_template('homepage.html')


@app.route('/about-me')
def render_about_me_page():
    """Renders about me page"""

    return render_template('about-me.html')


if __name__ == '__main__':
    app.run()