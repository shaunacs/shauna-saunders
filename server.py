"""Server for Shauna Saunders personal website"""

import os
from datetime import datetime, timedelta
from flask import Flask, redirect, render_template, request, jsonify, g
from flask_wtf.csrf import CSRFProtect
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv
import customers_db

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Make csrf available for import in blueprints
__all__ = ['csrf']

# Register blueprints
from traitors_blueprint import traitors_bp
from customers_blueprint import customers_bp
from admin_blueprint import admin_bp

app.register_blueprint(traitors_bp)
app.register_blueprint(customers_bp)
app.register_blueprint(admin_bp)

# Stripe webhook handler (moved from blueprint to avoid CSRF issues)
import stripe
import customers_db
from datetime import datetime

@app.route('/customers/stripe-webhook', methods=['POST'])
@csrf.exempt
def stripe_webhook():
    """Handle Stripe webhook events (CSRF exempt - validated via Stripe signature)"""
    print("🔔 Webhook endpoint reached!")
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')

    # Debug logging
    print(f"🔔 Webhook received")
    print(f"   Webhook secret configured: {'Yes' if webhook_secret else 'No'}")
    if webhook_secret:
        print(f"   Secret starts with: {webhook_secret[:15]}...")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        # Invalid payload
        print(f"❌ Webhook error - Invalid payload: {str(e)}")
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        print(f"❌ Webhook error - Signature verification failed: {str(e)}")
        print(f"   Check that STRIPE_WEBHOOK_SECRET in .env matches Stripe CLI output")
        return jsonify({'error': 'Invalid signature'}), 400

    # Log webhook event for debugging
    print(f"Received webhook event: {event['type']}")

    # Handle different event types
    if event['type'] == 'checkout.session.completed':
        session_data = event['data']['object']
        print(f"Checkout session completed: {session_data.get('id')}, mode: {session_data.get('mode')}, metadata: {session_data.get('metadata')}")
        handle_successful_payment(session_data)

    elif event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        if payment_intent.get('id'):
            customers_db.update_payment_status(payment_intent['id'], 'succeeded', datetime.now())

    elif event['type'] == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']
        if payment_intent.get('id'):
            customers_db.update_payment_status(payment_intent['id'], 'failed')

    elif event['type'] == 'customer.subscription.created':
        subscription = event['data']['object']
        print(f"Subscription created: {subscription.get('id')}, metadata: {subscription.get('metadata')}")
        handle_subscription_created(subscription)

    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        print(f"Subscription deleted: {subscription.get('id')}")
        handle_subscription_cancelled(subscription)

    elif event['type'] == 'customer.subscription.updated':
        subscription = event['data']['object']
        print(f"Subscription updated: {subscription.get('id')}")
        handle_subscription_updated(subscription)

    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        if invoice.get('subscription'):
            print(f"Subscription payment succeeded for: {invoice.get('subscription')}")
            handle_subscription_payment_succeeded(invoice)

    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        if invoice.get('subscription'):
            print(f"Subscription payment failed for: {invoice.get('subscription')}")
            handle_subscription_payment_failed(invoice)

    return jsonify({'status': 'success'}), 200


def handle_successful_payment(checkout_session):
    """Process successful payment from Stripe"""
    try:
        metadata = checkout_session.get('metadata', {})
        customer_id = metadata.get('customer_id')
        project_id = metadata.get('project_id')
        milestone_id = metadata.get('milestone_id')

        if not customer_id or not project_id:
            print(f"Missing metadata in checkout session: {checkout_session['id']}")
            return

        # Check if this is a subscription checkout
        if checkout_session.get('mode') == 'subscription':
            subscription_id = checkout_session.get('subscription')
            if subscription_id and project_id:
                # Update project with subscription ID and activate it immediately
                try:
                    customers_db.update_project(
                        int(project_id),
                        stripe_subscription_id=subscription_id,
                        subscription_status='active'
                    )
                    print(f"Activated subscription for project #{project_id}: {subscription_id}")
                except Exception as e:
                    print(f"Error updating project with subscription: {str(e)}")
            return  # Subscription payment records are handled by subscription.created webhook

        # Handle one-time payment
        amount = checkout_session['amount_total'] / 100

        # Create payment record
        payment_id = customers_db.create_payment(
            customer_id=int(customer_id),
            project_id=int(project_id) if project_id else None,
            milestone_id=int(milestone_id) if milestone_id else None,
            stripe_checkout_session_id=checkout_session['id'],
            stripe_payment_intent_id=checkout_session.get('payment_intent'),
            amount=amount,
            payment_type='one_time',
            status='succeeded',
            payment_method='stripe_card',
            description=f"Payment for project #{project_id}",
            metadata=str(metadata)
        )

        # Update project amount_paid
        if project_id:
            customers_db.update_project_paid_amount(int(project_id), amount)

        # Mark milestone as complete if provided, or find the next payment milestone
        if milestone_id:
            customers_db.mark_milestone_complete(int(milestone_id))
        else:
            # Find and complete the next unpaid payment milestone that matches this amount
            milestones = customers_db.get_milestones_by_project(int(project_id))
            for milestone in milestones:
                if (milestone['is_payment_milestone'] and
                    milestone['status'] != 'completed' and
                    milestone['payment_amount'] and
                    abs(milestone['payment_amount'] - amount) < 0.01):  # Match amount (with small tolerance)
                    customers_db.mark_milestone_complete(milestone['id'])
                    print(f"Auto-completed payment milestone: {milestone['milestone_name']}")
                    break

        # Mark payment link as used if it was admin-generated
        payment_link = customers_db.get_payment_link_by_session_id(checkout_session['id'])
        if payment_link:
            customers_db.mark_payment_link_used(checkout_session['id'])

        print(f"Payment processed successfully: ${amount} for project #{project_id}")

    except Exception as e:
        print(f"Error handling successful payment: {str(e)}")


def handle_subscription_created(subscription):
    """Handle subscription creation"""
    try:
        subscription_id = subscription['id']
        customer_email = subscription['customer_details']['email'] if subscription.get('customer_details') else None

        # Get the checkout session metadata to find project_id
        metadata = subscription.get('metadata', {})
        project_id = metadata.get('project_id')

        if not project_id:
            # Try to find project by looking for unlinked subscription projects
            print(f"Warning: No project_id in subscription metadata for {subscription_id}")
            print(f"Attempting to find matching project by customer email: {customer_email}")
            
            if customer_email:
                customer = customers_db.get_customer_by_email(customer_email)
                if customer:
                    # Find the most recent subscription project without a stripe_subscription_id
                    conn = customers_db.get_db()
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT id FROM projects 
                        WHERE customer_id = ? AND is_subscription = 1 AND stripe_subscription_id IS NULL 
                        ORDER BY created_at DESC LIMIT 1
                    ''', (customer['id'],))
                    project = cursor.fetchone()
                    conn.close()
                    
                    if project:
                        project_id = str(project['id'])
                        print(f"Found matching project: {project_id}")
                    else:
                        print(f"No unlinked subscription project found for customer {customer['id']}")
                        return
                else:
                    print(f"Customer not found for email: {customer_email}")
                    return
            else:
                print("No customer email in subscription")
                return

        # Calculate next payment date from subscription items
        next_payment_date = None
        try:
            sub_dict = dict(subscription)
            if 'items' in sub_dict and 'data' in sub_dict['items']:
                items_data = sub_dict['items']['data']
                if items_data and len(items_data) > 0:
                    item = items_data[0]  # Get first item
                    if 'current_period_end' in item and item['current_period_end']:
                        next_payment_date = datetime.fromtimestamp(item['current_period_end'])
        except Exception as e:
            print(f"Error extracting next payment date: {str(e)}")

        # Update project with subscription ID and status
        customers_db.update_project(
            int(project_id),
            stripe_subscription_id=subscription_id,
            subscription_status='active',
            next_payment_date=next_payment_date
        )

        # Create a payment record for the first payment
        if subscription.get('latest_invoice'):
            amount = subscription['items']['data'][0]['price']['unit_amount'] / 100  # Convert from cents
            customer = customers_db.get_customer_by_email(customer_email) if customer_email else None

            if customer:
                customers_db.create_payment(
                    customer_id=customer['id'],
                    project_id=int(project_id),
                    amount=amount,
                    payment_type='subscription',
                    stripe_subscription_id=subscription_id,
                    status='succeeded',
                    description='Subscription payment'
                )

        print(f"Subscription created and linked to project #{project_id}: {subscription_id}")

    except Exception as e:
        print(f"Error handling subscription created: {str(e)}")


def handle_subscription_cancelled(subscription):
    """Handle subscription cancellation"""
    try:
        subscription_id = subscription['id']

        # Find the project with this subscription ID
        conn = customers_db.get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM projects WHERE stripe_subscription_id = ?', (subscription_id,))
        project = cursor.fetchone()
        conn.close()

        if project:
            project_id = project['id']
            # Update project subscription status and main project status
            customers_db.update_project(
                project_id,
                subscription_status='cancelled',
                status='cancelled',
                next_payment_date=None
            )
            print(f"Subscription cancelled for project #{project_id}: {subscription_id}")
            
            # Send cancellation notification email
            send_cancellation_notification_webhook(project_id)
        else:
            print(f"No project found for cancelled subscription: {subscription_id}")

    except Exception as e:
        print(f"Error handling subscription cancelled: {str(e)}")


def send_cancellation_notification_webhook(project_id):
    """Send email notification when subscription is cancelled via webhook"""
    try:
        project = customers_db.get_project_by_id(project_id)
        if not project:
            print(f"Project not found for cancellation notification: {project_id}")
            return
            
        customer = customers_db.get_customer_by_id(project['customer_id'])
        sendgrid_api_key = os.environ.get('SENDGRID_API_KEY')
        
        if not sendgrid_api_key or not customer:
            print("SendGrid not configured or customer not found for cancellation notification")
            return
        
        email_body = f"""
Subscription Cancellation Notification (Stripe Dashboard)

Customer: {customer['name']} ({customer['email']})
Project: {project['project_name']}
Project Type: {project['project_type']}
Monthly Rate: ${project['total_amount']:.2f}
Cancelled via: Stripe Dashboard
Cancelled at: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}

Customer Contact Information:
- Email: {customer['email']}
- Company: {customer.get('company', 'N/A')}
- Phone: {customer.get('phone', 'N/A')}

This subscription was cancelled directly from the Stripe dashboard.
This is an automated notification from your customer management system.
"""

        message = Mail(
            from_email='noreply@shaunasaunders.com',
            to_emails='shauna.saunders@alumni.unc.edu',
            subject=f'Subscription Cancelled (Stripe): {customer["name"]} - {project["project_name"]}',
            plain_text_content=email_body
        )

        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        print(f"Webhook cancellation notification sent for customer {customer['name']}")

    except Exception as e:
        print(f"Error sending webhook cancellation notification: {str(e)}")


def handle_subscription_updated(subscription):
    """Handle subscription updates (e.g. plan changes, status changes)"""
    try:
        subscription_id = subscription['id']
        
        # Find the project with this subscription ID
        conn = customers_db.get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM projects WHERE stripe_subscription_id = ?', (subscription_id,))
        project = cursor.fetchone()
        conn.close()

        if project:
            project_id = project['id']
            
            # Calculate next payment date from subscription items
            next_payment_date = None
            try:
                sub_dict = dict(subscription)
                if 'items' in sub_dict and 'data' in sub_dict['items']:
                    items_data = sub_dict['items']['data']
                    if items_data and len(items_data) > 0:
                        item = items_data[0]  # Get first item
                        if 'current_period_end' in item and item['current_period_end']:
                            next_payment_date = datetime.fromtimestamp(item['current_period_end'])
            except Exception as e:
                print(f"Error extracting next payment date from updated subscription: {str(e)}")
            
            # Update project with latest subscription info
            update_data = {
                'next_payment_date': next_payment_date
            }
            
            # Handle subscription status changes
            if subscription.get('status') == 'active':
                update_data['subscription_status'] = 'active'
                if subscription.get('cancel_at_period_end'):
                    update_data['subscription_status'] = 'cancel_pending'
            elif subscription.get('status') == 'canceled':
                update_data['subscription_status'] = 'cancelled'
                update_data['status'] = 'cancelled'
                update_data['next_payment_date'] = None
            elif subscription.get('status') == 'past_due':
                update_data['subscription_status'] = 'past_due'
            
            customers_db.update_project(project_id, **update_data)
            print(f"Subscription updated for project #{project_id}: {subscription_id}")
        else:
            print(f"No project found for updated subscription: {subscription_id}")

    except Exception as e:
        print(f"Error handling subscription updated: {str(e)}")


def handle_subscription_payment_succeeded(invoice):
    """Handle successful subscription payments"""
    try:
        subscription_id = invoice['subscription']
        amount = invoice['amount_paid'] / 100  # Convert from cents
        
        # Find the project with this subscription ID
        conn = customers_db.get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id, customer_id FROM projects WHERE stripe_subscription_id = ?', (subscription_id,))
        project = cursor.fetchone()
        conn.close()

        if project:
            # Create payment record for successful subscription payment
            customers_db.create_payment(
                customer_id=project['customer_id'],
                project_id=project['id'],
                amount=amount,
                payment_type='subscription',
                stripe_subscription_id=subscription_id,
                status='succeeded',
                description='Monthly subscription payment'
            )
            
            # Update next payment date from subscription
            try:
                subscription = stripe.Subscription.retrieve(subscription_id)
                sub_dict = dict(subscription)
                
                if 'items' in sub_dict and 'data' in sub_dict['items']:
                    items_data = sub_dict['items']['data']
                    if items_data and len(items_data) > 0:
                        item = items_data[0]
                        if 'current_period_end' in item and item['current_period_end']:
                            next_payment_date = datetime.fromtimestamp(item['current_period_end'])
                            customers_db.update_project(
                                project['id'],
                                next_payment_date=next_payment_date,
                                subscription_status='active'
                            )
                            print(f"Updated next payment date after successful payment: {next_payment_date}")
            except Exception as e:
                print(f"Error updating next payment date after payment: {str(e)}")
            
            print(f"Subscription payment recorded: ${amount} for project #{project['id']}")
        else:
            print(f"No project found for subscription payment: {subscription_id}")

    except Exception as e:
        print(f"Error handling subscription payment succeeded: {str(e)}")


def handle_subscription_payment_failed(invoice):
    """Handle failed subscription payments"""
    try:
        subscription_id = invoice['subscription']
        amount = invoice['amount_due'] / 100  # Convert from cents
        
        # Find the project with this subscription ID
        conn = customers_db.get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id, customer_id FROM projects WHERE stripe_subscription_id = ?', (subscription_id,))
        project = cursor.fetchone()
        conn.close()

        if project:
            # Create payment record for failed subscription payment
            customers_db.create_payment(
                customer_id=project['customer_id'],
                project_id=project['id'],
                amount=amount,
                payment_type='subscription',
                stripe_subscription_id=subscription_id,
                status='failed',
                description='Failed monthly subscription payment'
            )
            
            # Update subscription status to past_due
            customers_db.update_project(
                project['id'],
                subscription_status='past_due'
            )
            
            print(f"Subscription payment failed: ${amount} for project #{project['id']}")
        else:
            print(f"No project found for failed subscription payment: {subscription_id}")

    except Exception as e:
        print(f"Error handling subscription payment failed: {str(e)}")


print(f"✅ CSRF Protection enabled with webhook exemption")
print(f"   Webhook endpoint: /customers/stripe-webhook")

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

        # Save contact submission to database
        try:
            customers_db.save_contact_submission(
                name=name,
                email=email,
                interest=interest,
                timeline=timeline,
                budget=budget,
                project_description=project_description,
                client_ip=client_ip
            )
        except Exception as db_error:
            # Log error but don't fail the request - email was already sent
            print(f"Error saving contact submission to database: {str(db_error)}")

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
    # Use port 5001 to avoid conflict with macOS AirPlay on port 5000
    app.run()