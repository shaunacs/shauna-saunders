"""Server for Shauna Saunders personal website"""

import os
from datetime import datetime, timedelta
from flask import Flask, redirect, render_template, request, jsonify
from flask_wtf.csrf import CSRFProtect
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")
csrf = CSRFProtect(app)

# Register Traitors blueprint
from traitors_blueprint import traitors_bp
app.register_blueprint(traitors_bp)

# Simple rate limiting: Store submission timestamps per IP
submission_tracker = {}

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


@app.route('/submit-contact', methods=['POST'])
def submit_contact_form():
    """Handles contact form submission and sends email via SendGrid"""

    try:
        # Get client IP for rate limiting
        client_ip = request.remote_addr
        current_time = datetime.now()

        # Rate limiting: Allow only 1 submission per 5 minutes per IP
        if client_ip in submission_tracker:
            last_submission = submission_tracker[client_ip]
            time_diff = current_time - last_submission
            if time_diff < timedelta(minutes=5):
                return jsonify({
                    'success': False,
                    'message': 'Please wait a few minutes before submitting another inquiry.'
                }), 429

        # Get form data
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        interest = request.form.get('interest', '').strip()
        timeline = request.form.get('timeline', '').strip()
        budget = request.form.get('budget', '').strip()
        project_description = request.form.get('project_description', '').strip()
        honeypot = request.form.get('website', '').strip()  # Honeypot field

        # Check honeypot field (should be empty for legitimate submissions)
        if honeypot:
            # Log this as a bot submission but return success to fool bots
            return jsonify({
                'success': True,
                'message': 'Thanks for reaching out! I\'ll get back to you within 24 hours.'
            })

        # Validate required fields
        if not all([name, email, interest, timeline, budget, project_description]):
            return jsonify({
                'success': False,
                'message': 'Please fill out all required fields.'
            }), 400

        # Validate email format (basic)
        if '@' not in email or '.' not in email:
            return jsonify({
                'success': False,
                'message': 'Please provide a valid email address.'
            }), 400

        # Create email content
        email_body = f"""
New Website Inquiry from {name}

Contact Information:
Name: {name}
Email: {email}

Project Details:
I'm interested in: {interest}
Timeline: {timeline}
Budget Range: {budget}

Project Description:
{project_description}

---
This inquiry was submitted on {current_time.strftime('%B %d, %Y at %I:%M %p')}
"""

        # Send email via SendGrid
        sendgrid_api_key = os.environ.get('SENDGRID_API_KEY')

        if not sendgrid_api_key:
            # If SendGrid is not configured, log the error but don't expose it to the user
            print("ERROR: SENDGRID_API_KEY not configured")
            return jsonify({
                'success': False,
                'message': 'Unable to send message at this time. Please email me directly at shauna.saunders@alumni.unc.edu'
            }), 500

        message = Mail(
            from_email='noreply@shaunasaunders.com',  # Replace with your verified sender
            to_emails='shauna.saunders@alumni.unc.edu',
            subject=f'New Website Inquiry from {name}',
            plain_text_content=email_body
        )

        # Set reply-to to client's email
        message.reply_to = email

        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)

        # Update rate limiting tracker
        submission_tracker[client_ip] = current_time

        # Clean up old entries from tracker (older than 1 hour)
        cutoff_time = current_time - timedelta(hours=1)
        submission_tracker_copy = submission_tracker.copy()
        for ip, timestamp in submission_tracker_copy.items():
            if timestamp < cutoff_time:
                del submission_tracker[ip]

        return jsonify({
            'success': True,
            'message': 'Thanks for reaching out! I\'ll get back to you within 24 hours.'
        })

    except Exception as e:
        # Log the error but don't expose details to the user
        print(f"Error processing contact form: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'An error occurred. Please try again or email me directly at shauna.saunders@alumni.unc.edu'
        }), 500


if __name__ == '__main__':
    app.run()