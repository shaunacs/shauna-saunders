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


@app.route('/portfolio')
def render_portfolio_page():
    """Renders portfolio page"""

    return render_template('portfolio.html')


@app.route('/contact')
def render_contact_page():
    """Renders contact page"""

    return render_template('contact.html')


@app.route('/services')
def render_services_page():
    """Renders services page"""

    return render_template('services.html')


if __name__ == '__main__':
    app.run()