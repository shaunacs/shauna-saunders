"""Blueprint for customer management system"""

import os
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, g
from werkzeug.security import generate_password_hash
from functools import wraps
from datetime import datetime, timedelta
import stripe
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from customers_db import *

customers_bp = Blueprint('customers', __name__, url_prefix='/customers')


# Initialize Stripe
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')


# Template filters
@customers_bp.app_template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    """Convert Unix timestamp to readable date"""
    if timestamp:
        return datetime.fromtimestamp(timestamp).strftime('%B %d, %Y')
    return 'N/A'

@customers_bp.app_template_filter('format_date')
def format_date(date_string):
    """Convert date string to MM-DD-YYYY format"""
    if not date_string:
        return 'N/A'
    try:
        # Handle both full datetime strings and date-only strings
        if 'T' in str(date_string):
            # ISO format with time
            date_obj = datetime.fromisoformat(str(date_string).replace('Z', '+00:00'))
        elif ' ' in str(date_string):
            # Format: YYYY-MM-DD HH:MM:SS
            date_obj = datetime.strptime(str(date_string)[:10], '%Y-%m-%d')
        else:
            # Format: YYYY-MM-DD
            date_obj = datetime.strptime(str(date_string), '%Y-%m-%d')
        
        return date_obj.strftime('%m-%d-%Y')
    except:
        return str(date_string)[:10] if len(str(date_string)) >= 10 else str(date_string)


def customer_login_required(f):
    """Decorator to require customer login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'customer_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('customers.login'))

        # Check idle timeout (30 minutes)
        IDLE_TIMEOUT_MINUTES = 30
        last_activity = session.get('last_activity')
        if last_activity:
            last_activity_time = datetime.fromisoformat(last_activity)
            if datetime.now() - last_activity_time > timedelta(minutes=IDLE_TIMEOUT_MINUTES):
                session.clear()
                flash('Your session has expired due to inactivity. Please log in again.', 'warning')
                return redirect(url_for('customers.login'))

        # Update last activity time
        session['last_activity'] = datetime.now().isoformat()

        # Check if customer is active
        customer = get_customer_by_id(session['customer_id'])
        if not customer or not customer['is_active']:
            session.clear()
            flash('Your account is inactive. Please contact support.', 'error')
            return redirect(url_for('customers.login'))

        return f(*args, **kwargs)
    return decorated_function


# Authentication Routes

@customers_bp.route('/')
def index():
    """Redirect to dashboard or login"""
    if 'customer_id' in session:
        return redirect(url_for('customers.dashboard'))
    return redirect(url_for('customers.login'))


@customers_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Customer login page"""
    # Prevent login if already logged in as customer
    if 'customer_id' in session:
        return redirect(url_for('customers.dashboard'))

    # Prevent customers from logging in if logged in as Traitors user
    if 'user_id' in session:
        flash('Please logout of your account first before accessing the customer portal.', 'warning')
        return redirect(url_for('render_homepage'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        customer = verify_customer(email, password)
        if customer and customer['is_active']:
            session['customer_id'] = customer['id']
            session['customer_email'] = customer['email']
            session['customer_name'] = customer['name']
            session['last_activity'] = datetime.now().isoformat()
            flash(f'Welcome back, {customer["name"]}!', 'success')
            return redirect(url_for('customers.dashboard'))
        else:
            flash('Invalid email or password, or account is inactive.', 'error')

    return render_template('customers/login.html')


@customers_bp.route('/logout')
def logout():
    """Customer logout"""
    # Only clear customer session keys
    session.pop('customer_id', None)
    session.pop('customer_email', None)
    session.pop('customer_name', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('customers.login'))


@customers_bp.route('/change-password', methods=['GET', 'POST'])
@customer_login_required
def change_password():
    """Allow customers to change their password"""
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Verify current password
        customer = get_customer_by_id(session['customer_id'])
        if not verify_customer(customer['email'], current_password):
            flash('Current password is incorrect.', 'error')
            return render_template('customers/change_password.html')

        # Validate new password
        if len(new_password) < 8:
            flash('New password must be at least 8 characters.', 'error')
            return render_template('customers/change_password.html')

        if new_password != confirm_password:
            flash('New passwords do not match.', 'error')
            return render_template('customers/change_password.html')

        # Update password
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE customers SET password_hash = ? WHERE id = ?
        ''', (generate_password_hash(new_password, method='pbkdf2:sha256'), session['customer_id']))
        conn.commit()
        conn.close()

        flash('Password changed successfully!', 'success')
        return redirect(url_for('customers.dashboard'))

    return render_template('customers/change_password.html')


# Customer Dashboard Routes

@customers_bp.route('/dashboard')
@customer_login_required
def dashboard():
    """Customer dashboard"""
    customer_id = session['customer_id']
    customer = get_customer_by_id(customer_id)
    projects = get_projects_by_customer(customer_id)
    
    # Auto-backfill next payment dates for existing subscriptions (runs once per session)
    if 'payment_dates_backfilled' not in session:
        try:
            backfill_subscription_payment_dates()
            session['payment_dates_backfilled'] = True
        except Exception as e:
            print(f"Error during auto-backfill: {str(e)}")
            # Don't fail the dashboard load if backfill fails

    # Get active (unused) payment links
    payment_links = get_payment_links_by_customer(customer_id, include_used=False)

    # Calculate totals
    total_paid = get_customer_total_paid(customer_id)
    outstanding_balance = get_outstanding_balance(customer_id)

    # Get recent payments
    recent_payments = get_payment_history(customer_id=customer_id, limit=5)

    # Add completion percentage to projects
    for project in projects:
        project['completion_percentage'] = get_project_completion_percentage(project['id'])

    return render_template('customers/dashboard.html',
                         customer=customer,
                         projects=projects,
                         payment_links=payment_links,
                         total_paid=total_paid,
                         outstanding_balance=outstanding_balance,
                         recent_payments=recent_payments)


@customers_bp.route('/projects/<int:project_id>')
@customer_login_required
def project_detail(project_id):
    """View project details"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    # Security: Ensure project belongs to logged-in customer
    if not project or project['customer_id'] != customer_id:
        flash('Project not found.', 'error')
        return redirect(url_for('customers.dashboard'))

    # Get milestones
    milestones = get_milestones_by_project(project_id)

    # Get payments for this project
    payments = get_payments_by_project(project_id)

    # Calculate completion percentage
    completion_percentage = get_project_completion_percentage(project_id)

    # Calculate remaining balance
    remaining_balance = project['total_amount'] - project['amount_paid']

    return render_template('customers/project_detail.html',
                         project=project,
                         milestones=milestones,
                         payments=payments,
                         completion_percentage=completion_percentage,
                         remaining_balance=remaining_balance)


# Stripe Payment Routes

@customers_bp.route('/create-checkout-session', methods=['POST'])
@customer_login_required
def create_checkout_session():
    """Create Stripe Checkout session for customer payment"""
    try:
        project_id = request.form.get('project_id')
        milestone_id = request.form.get('milestone_id')  # Optional

        customer_id = session['customer_id']
        customer = get_customer_by_id(customer_id)
        project = get_project_by_id(project_id)

        # Security: Ensure project belongs to customer
        if not project or project['customer_id'] != customer_id:
            flash('Invalid project.', 'error')
            return redirect(url_for('customers.dashboard'))

        # Check if this is a subscription project
        if project.get('is_subscription'):
            # Handle subscription checkout
            if not project.get('stripe_price_id'):
                flash('Subscription configuration error. Please contact support.', 'error')
                return redirect(url_for('customers.dashboard'))

            # Create subscription checkout session
            checkout_session = stripe.checkout.Session.create(
                customer_email=customer['email'],
                payment_method_types=['card'],
                line_items=[{
                    'price': project['stripe_price_id'],
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=url_for('customers.payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('customers.payment_cancel', _external=True),
                metadata={
                    'customer_id': customer_id,
                    'project_id': project_id,
                },
                subscription_data={
                    'metadata': {
                        'customer_id': str(customer_id),
                        'project_id': str(project_id),
                    }
                }
            )
        else:
            # Handle one-time payment
            # Determine amount based on payment plan
            if milestone_id:
                milestone = get_milestone_by_id(milestone_id)
                if not milestone or milestone['project_id'] != int(project_id):
                    flash('Invalid milestone.', 'error')
                    return redirect(url_for('customers.project_detail', project_id=project_id))

                amount = milestone['payment_amount']
                description = f"{project['project_name']} - {milestone['milestone_name']}"
            else:
                # Calculate next payment amount based on payment plan
                remaining = project['total_amount'] - project['amount_paid']

                if project['payment_plan'] == '50_50':
                    amount = project['total_amount'] * 0.5
                elif project['payment_plan'] == 'full_upfront':
                    amount = remaining
                else:
                    # Default to remaining balance
                    amount = remaining

                description = f"{project['project_name']} - Payment"

            # Create one-time payment Checkout Session
            checkout_session = stripe.checkout.Session.create(
                customer_email=customer['email'],
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': project['project_name'],
                            'description': description
                        },
                        'unit_amount': int(amount * 100),  # Convert to cents
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=url_for('customers.payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('customers.payment_cancel', _external=True),
                metadata={
                    'customer_id': customer_id,
                    'project_id': project_id,
                    'milestone_id': milestone_id or ''
                }
            )

        return redirect(checkout_session.url, code=303)

    except Exception as e:
        print(f"Error creating checkout session: {str(e)}")
        flash('An error occurred processing your payment. Please try again.', 'error')
        return redirect(url_for('customers.dashboard'))


@customers_bp.route('/payment-success')
@customer_login_required
def payment_success():
    """Payment success page"""
    session_id = request.args.get('session_id')

    if session_id:
        try:
            # Retrieve the session to show payment details
            checkout_session = stripe.checkout.Session.retrieve(session_id)
            amount = checkout_session.amount_total / 100

            return render_template('customers/payment_success.html',
                                 amount=amount,
                                 session_id=session_id)
        except Exception as e:
            print(f"Error retrieving session: {str(e)}")

    return render_template('customers/payment_success.html',
                         amount=None,
                         session_id=None)


@customers_bp.route('/payment-cancel')
@customer_login_required
def payment_cancel():
    """Payment cancel page"""
    return render_template('customers/payment_cancel.html')


# Subscription Management Routes

@customers_bp.route('/subscription/<int:project_id>')
@customer_login_required
def manage_subscription(project_id):
    """Manage subscription for a project"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    # Security: Ensure project belongs to customer
    if not project or project['customer_id'] != customer_id:
        flash('Invalid project.', 'error')
        return redirect(url_for('customers.dashboard'))

    if not project.get('is_subscription'):
        flash('This project is not a subscription.', 'error')
        return redirect(url_for('customers.dashboard'))

    # Retrieve subscription details from Stripe
    subscription_details = None
    if project.get('stripe_subscription_id'):
        try:
            subscription_details = stripe.Subscription.retrieve(project['stripe_subscription_id'])
        except Exception as e:
            print(f"Error retrieving subscription: {str(e)}")
            flash('Error loading subscription details.', 'error')

    return render_template('customers/manage_subscription.html',
                         project=project,
                         subscription=subscription_details)


@customers_bp.route('/subscription/<int:project_id>/cancel', methods=['POST'])
@customer_login_required
def cancel_subscription(project_id):
    """Cancel a subscription"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    # Security: Ensure project belongs to customer
    if not project or project['customer_id'] != customer_id:
        flash('Invalid project.', 'error')
        return redirect(url_for('customers.dashboard'))

    if not project.get('stripe_subscription_id'):
        flash('No active subscription found.', 'error')
        return redirect(url_for('customers.dashboard'))

    try:
        # Cancel the subscription in Stripe
        stripe.Subscription.delete(project['stripe_subscription_id'])

        # Update project status (webhook will handle this too, but update immediately for UI)
        update_project(project_id, subscription_status='cancelled', status='cancelled', next_payment_date=None)

        # Send email notification
        send_cancellation_notification(customer_id, project)

        flash('Your subscription has been cancelled successfully.', 'success')
    except Exception as e:
        print(f"Error cancelling subscription: {str(e)}")
        flash('Error cancelling subscription. Please try again or contact support.', 'error')

    return redirect(url_for('customers.dashboard'))


def send_cancellation_notification(customer_id, project):
    """Send email notification when a subscription is cancelled"""
    try:
        customer = get_customer_by_id(customer_id)
        sendgrid_api_key = os.environ.get('SENDGRID_API_KEY')
        
        if not sendgrid_api_key or not customer:
            print("SendGrid not configured or customer not found for cancellation notification")
            return
        
        email_body = f"""
Subscription Cancellation Notification

Customer: {customer['name']} ({customer['email']})
Project: {project['project_name']}
Project Type: {project['project_type']}
Monthly Rate: ${project['total_amount']:.2f}
Cancelled at: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}

Customer Contact Information:
- Email: {customer['email']}
- Company: {customer.get('company', 'N/A')}
- Phone: {customer.get('phone', 'N/A')}

This is an automated notification from your customer management system.
"""

        message = Mail(
            from_email='noreply@shaunasaunders.com',
            to_emails='shauna.saunders@alumni.unc.edu',
            subject=f'Subscription Cancelled: {customer["name"]} - {project["project_name"]}',
            plain_text_content=email_body
        )

        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        print(f"Cancellation notification sent for customer {customer['name']}")

    except Exception as e:
        print(f"Error sending cancellation notification: {str(e)}")


def backfill_subscription_payment_dates():
    """Backfill next payment dates for existing active subscriptions"""
    try:
        projects = get_active_subscription_projects()
        updated_count = 0
        
        for project in projects:
            if not project['next_payment_date'] and project['stripe_subscription_id']:
                try:
                    # Fetch subscription details from Stripe
                    subscription = stripe.Subscription.retrieve(project['stripe_subscription_id'])
                    
                    # Get subscription as dictionary to access items properly
                    sub_dict = dict(subscription)
                    
                    # Check for current_period_end in subscription items
                    if 'items' in sub_dict and 'data' in sub_dict['items']:
                        items_data = sub_dict['items']['data']
                        
                        if items_data and len(items_data) > 0:
                            item = items_data[0]  # Get first item
                            
                            if 'current_period_end' in item and item['current_period_end']:
                                next_payment_date = datetime.fromtimestamp(item['current_period_end'])
                                update_project(
                                    project['id'],
                                    next_payment_date=next_payment_date
                                )
                                updated_count += 1
                                print(f"Updated next payment date for project #{project['id']}: {next_payment_date}")
                        
                except Exception as e:
                    print(f"Error updating project #{project['id']}: {str(e)}")
                    
        print(f"Backfill completed: {updated_count} projects updated")
        return updated_count
        
    except Exception as e:
        print(f"Error during backfill: {str(e)}")
        return 0


# Feature Request Routes

@customers_bp.route('/project/<int:project_id>/request-feature', methods=['GET', 'POST'])
@customer_login_required
def request_feature(project_id):
    """Submit a feature request for a project"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    # Security: Ensure project belongs to logged-in customer
    if not project or project['customer_id'] != customer_id:
        flash('Project not found.', 'error')
        return redirect(url_for('customers.dashboard'))

    # Only allow feature requests for ongoing maintenance projects
    if project['project_type'] != 'ongoing_maintenance':
        flash('Feature requests are only available for ongoing maintenance projects.', 'error')
        return redirect(url_for('customers.project_detail', project_id=project_id))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        priority = request.form.get('priority', 'medium')
        requested_completion = request.form.get('requested_completion', '').strip()
        additional_info = request.form.get('additional_info', '').strip()

        # Validation
        if not title or not description:
            flash('Title and description are required.', 'error')
            return render_template('customers/request_feature.html', project=project)

        try:
            # Create feature request
            feature_request_id = create_feature_request(
                customer_id=customer_id,
                project_id=project_id,
                title=title,
                description=description,
                priority=priority,
                requested_completion=requested_completion if requested_completion else None,
                additional_info=additional_info if additional_info else None
            )

            # Send notification email to admin
            send_feature_request_notification(feature_request_id)

            flash('Your feature request has been submitted successfully! You will receive email updates as we work on it.', 'success')
            return redirect(url_for('customers.view_feature_requests', project_id=project_id))

        except Exception as e:
            print(f"Error creating feature request: {str(e)}")
            flash('An error occurred while submitting your request. Please try again.', 'error')

    return render_template('customers/request_feature.html', project=project)


@customers_bp.route('/project/<int:project_id>/feature-requests')
@customer_login_required
def view_feature_requests(project_id):
    """View feature requests for a project"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    # Security: Ensure project belongs to logged-in customer
    if not project or project['customer_id'] != customer_id:
        flash('Project not found.', 'error')
        return redirect(url_for('customers.dashboard'))

    # Get feature requests for this project
    feature_requests = get_feature_requests_by_customer(customer_id, project_id)

    return render_template('customers/feature_requests.html', 
                         project=project, 
                         feature_requests=feature_requests)


@customers_bp.route('/feature-request/<int:request_id>')
@customer_login_required
def view_feature_request(request_id):
    """View details of a specific feature request"""
    customer_id = session['customer_id']
    feature_request = get_feature_request_by_id(request_id)

    if not feature_request or feature_request['customer_id'] != customer_id:
        flash('Feature request not found.', 'error')
        return redirect(url_for('customers.dashboard'))

    # Get status history
    status_history = get_feature_request_history(request_id)

    return render_template('customers/feature_request_detail.html',
                         feature_request=feature_request,
                         status_history=status_history)


def send_feature_request_notification(feature_request_id):
    """Send email notification when a new feature request is submitted"""
    try:
        feature_request = get_feature_request_by_id(feature_request_id)
        if not feature_request:
            print("Feature request not found for notification")
            return

        sendgrid_api_key = os.environ.get('SENDGRID_API_KEY')
        
        if not sendgrid_api_key:
            print("SendGrid not configured for feature request notification")
            return
        
        email_body = f"""
New Feature Request Submitted

Request ID: #{feature_request['id']}
Customer: {feature_request['customer_name']} ({feature_request['customer_email']})
Project: {feature_request['project_name']}

Title: {feature_request['title']}
Priority: {feature_request['priority'].title()}

Description:
{feature_request['description']}

{f"Requested Completion: {feature_request['requested_completion']}" if feature_request['requested_completion'] else ""}

{f"Additional Information: {feature_request['additional_info']}" if feature_request['additional_info'] else ""}

Submitted: {feature_request['created_at']}

You can manage this request in your admin panel.
This is an automated notification from your customer management system.
"""

        message = Mail(
            from_email='noreply@shaunasaunders.com',
            to_emails='shauna.saunders@alumni.unc.edu',
            subject=f'New Feature Request: {feature_request["title"]} - {feature_request["customer_name"]}',
            plain_text_content=email_body
        )

        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        print(f"Feature request notification sent for request #{feature_request_id}")

    except Exception as e:
        print(f"Error sending feature request notification: {str(e)}")


def send_status_update_notification(feature_request_id, old_status, new_status, status_message=None):
    """Send email notification when feature request status is updated"""
    try:
        feature_request = get_feature_request_by_id(feature_request_id)
        if not feature_request:
            print("Feature request not found for status update notification")
            return

        sendgrid_api_key = os.environ.get('SENDGRID_API_KEY')
        
        if not sendgrid_api_key:
            print("SendGrid not configured for status update notification")
            return

        # Create user-friendly status names
        status_names = {
            'request_received': 'Request Received',
            'in_review': 'In Review',
            'approved': 'Approved',
            'in_progress': 'In Progress',
            'testing': 'Testing',
            'completed': 'Completed',
            'on_hold': 'On Hold',
            'rejected': 'Rejected'
        }

        old_status_name = status_names.get(old_status, old_status.replace('_', ' ').title())
        new_status_name = status_names.get(new_status, new_status.replace('_', ' ').title())
        
        email_body = f"""
Feature Request Status Update

Hi {feature_request['customer_name']},

Your feature request has been updated:

Request: {feature_request['title']}
Project: {feature_request['project_name']}

Status changed from "{old_status_name}" to "{new_status_name}"

{f"Update: {status_message}" if status_message else ""}

{f"Admin Notes: {feature_request['admin_notes']}" if feature_request.get('admin_notes') else ""}

You can view the full details and history at: [Your customer portal link]

Thanks,
Shauna Saunders
"""

        message = Mail(
            from_email='noreply@shaunasaunders.com',
            to_emails=feature_request['customer_email'],
            subject=f'Status Update: {feature_request["title"]} - Now {new_status_name}',
            plain_text_content=email_body
        )

        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        print(f"Status update notification sent to {feature_request['customer_email']} for request #{feature_request_id}")

    except Exception as e:
        print(f"Error sending status update notification: {str(e)}")


# Stripe webhook handler moved to server.py to avoid CSRF issues
