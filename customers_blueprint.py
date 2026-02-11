"""Blueprint for customer management system"""

import os
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, g
from werkzeug.security import generate_password_hash
from functools import wraps
from datetime import datetime, timedelta
import stripe
from ses_helper import send_email as ses_send_email

from customers_db import (
    get_db, verify_customer, get_customer_by_id, get_projects_by_customer,
    get_project_by_id, get_milestones_by_project, get_milestone_by_id,
    get_payments_by_project, get_payment_links_by_customer, get_customer_total_paid,
    get_outstanding_balance, get_project_completion_percentage, get_payment_history,
    get_active_subscription_projects, update_project, create_feature_request,
    get_feature_requests_by_customer, get_feature_request_by_id, get_feature_request_history,
    get_unsigned_agreements_for_customer, get_signed_agreements_for_customer,
    get_agreement_by_id, get_active_agreement_for_project, sign_agreement,
    get_agreement_signature, replace_agreement_placeholders
)

customers_bp = Blueprint('customers', __name__, url_prefix='/customers')


# Initialize Stripe
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# Base URL for production (used for Stripe redirect URLs)
BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5001')


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

        # Check idle timeout (30 minutes) — skip when admin is impersonating
        if not session.get('impersonating_customer_id'):
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
    # If admin is impersonating, stop impersonation instead of logging out
    if session.get('impersonating_customer_id'):
        return redirect(url_for('admin.stop_impersonate'))

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

    # Get unsigned agreements for warning banner
    unsigned_agreements = get_unsigned_agreements_for_customer(customer_id)

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
                         unsigned_agreements=unsigned_agreements,
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


@customers_bp.route('/projects/<int:project_id>/update-email', methods=['POST'])
@customer_login_required
def update_project_email(project_id):
    """Update project notification email"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    # Security: Ensure project belongs to logged-in customer
    if not project or project['customer_id'] != customer_id:
        flash('Project not found.', 'error')
        return redirect(url_for('customers.dashboard'))

    email = request.form.get('project_email', '').strip() or None

    update_project(project_id, email=email)

    if email:
        flash(f'Project notification email updated to {email}.', 'success')
    else:
        flash('Project notification email cleared. Updates will be sent to your account email.', 'success')

    return redirect(url_for('customers.project_detail', project_id=project_id))


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
                success_url=f'{BASE_URL}/customers/payment-success?session_id={{CHECKOUT_SESSION_ID}}',
                cancel_url=f'{BASE_URL}/customers/payment-cancel',
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
                success_url=f'{BASE_URL}/customers/payment-success?session_id={{CHECKOUT_SESSION_ID}}',
                cancel_url=f'{BASE_URL}/customers/payment-cancel',
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


@customers_bp.route('/subscription/<int:project_id>/update-payment', methods=['POST'])
@customer_login_required
def update_payment_method(project_id):
    """Create a Stripe Customer Portal session for payment method updates"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    # Security: Ensure project belongs to customer
    if not project or project['customer_id'] != customer_id:
        flash('Invalid project.', 'error')
        return redirect(url_for('customers.dashboard'))

    if not project.get('stripe_subscription_id'):
        flash('No payment information found for this project.', 'error')
        return redirect(url_for('customers.manage_subscription', project_id=project_id))

    try:
        # Get the Stripe customer ID from the subscription
        subscription = stripe.Subscription.retrieve(project['stripe_subscription_id'])
        stripe_customer_id = subscription.customer

        # Create a Stripe Customer Portal session
        session_data = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=f'{BASE_URL}/customers/subscription/{project_id}',
        )
        
        # Redirect customer to the Customer Portal
        return redirect(session_data.url)
    
    except Exception as e:
        print(f"Error creating Customer Portal session: {str(e)}")
        flash('Unable to access payment management. Please try again or contact support.', 'error')
        return redirect(url_for('customers.manage_subscription', project_id=project_id))


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
        # Cancel the subscription at period end (customer retains access until then)
        stripe.Subscription.modify(
            project['stripe_subscription_id'],
            cancel_at_period_end=True
        )

        # Update project status (webhook will handle this too, but update immediately for UI)
        update_project(project_id, subscription_status='cancel_pending')

        # Send email notification
        send_cancellation_notification(customer_id, project)

        flash('Your subscription has been cancelled. You will continue to have access until the end of your current billing period.', 'success')
    except Exception as e:
        print(f"Error cancelling subscription: {str(e)}")
        flash('Error cancelling subscription. Please try again or contact support.', 'error')

    return redirect(url_for('customers.dashboard'))


def send_cancellation_notification(customer_id, project):
    """Send email notification when a subscription is cancelled"""
    try:
        customer = get_customer_by_id(customer_id)
        if not customer:
            print("Customer not found for cancellation notification")
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

        result = ses_send_email(
            to_email='shauna.saunders@alumni.unc.edu',
            subject=f'Subscription Cancelled: {customer["name"]} - {project["project_name"]}',
            body=email_body
        )

        if result['success']:
            print(f"Cancellation notification sent for customer {customer['name']}")
        else:
            print(f"Failed to send cancellation notification: {result.get('error')}")

    except Exception as e:
        print(f"Error sending cancellation notification: {str(e)}")


# Manual Payment Routes

@customers_bp.route('/subscription/<int:project_id>/manual-payment')
@customer_login_required
def manual_payment(project_id):
    """Show manual payment options page"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    if not project or project['customer_id'] != customer_id:
        flash('Invalid project.', 'error')
        return redirect(url_for('customers.dashboard'))

    if not project.get('is_subscription'):
        flash('This project is not a subscription.', 'error')
        return redirect(url_for('customers.dashboard'))

    return render_template('customers/manual_payment.html', project=project)


@customers_bp.route('/subscription/<int:project_id>/choose-manual', methods=['POST'])
@customer_login_required
def choose_manual_payment(project_id):
    """Customer chooses to pay via manual method"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    if not project or project['customer_id'] != customer_id:
        flash('Invalid project.', 'error')
        return redirect(url_for('customers.dashboard'))

    if not project.get('is_subscription'):
        flash('This project is not a subscription.', 'error')
        return redirect(url_for('customers.dashboard'))

    flash('You have selected manual payment. Please send your payment using one of the methods below, then confirm.', 'success')
    return redirect(url_for('customers.manual_payment', project_id=project_id, step='confirm'))


@customers_bp.route('/subscription/<int:project_id>/confirm-manual-payment', methods=['POST'])
@customer_login_required
def confirm_manual_payment(project_id):
    """Customer confirms they have sent a manual payment"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    if not project or project['customer_id'] != customer_id:
        flash('Invalid project.', 'error')
        return redirect(url_for('customers.dashboard'))

    payment_method = request.form.get('payment_method', '').strip()
    if payment_method not in ('venmo', 'cashapp', 'zelle'):
        flash('Please select which payment method you used.', 'error')
        return redirect(url_for('customers.manual_payment', project_id=project_id))

    # Update project to manual payment with pending status (admin must confirm receipt)
    update_project(
        project_id,
        payment_method_type='manual',
        subscription_status='pending'
    )

    # Send email notification to admin
    send_manual_payment_notification(customer_id, project, payment_method)

    method_labels = {'venmo': 'Venmo', 'cashapp': 'CashApp', 'zelle': 'Zelle'}
    flash(f'Thank you! We have been notified that you sent payment via {method_labels[payment_method]}. Your payment status will be updated once confirmed.', 'success')
    return redirect(url_for('customers.dashboard'))


@customers_bp.route('/subscription/<int:project_id>/switch-to-manual', methods=['POST'])
@customer_login_required
def switch_to_manual(project_id):
    """Customer switches from Stripe to manual payment"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    if not project or project['customer_id'] != customer_id:
        flash('Invalid project.', 'error')
        return redirect(url_for('customers.dashboard'))

    if not project.get('is_subscription'):
        flash('This project is not a subscription.', 'error')
        return redirect(url_for('customers.dashboard'))

    update_project(project_id, payment_method_type='manual')

    flash('Your payment method has been switched to manual. Please use Venmo, CashApp, or Zelle to make payments.', 'success')
    return redirect(url_for('customers.manual_payment', project_id=project_id))


def send_manual_payment_notification(customer_id, project, payment_method_used):
    """Send email notification when a customer confirms a manual payment"""
    try:
        customer = get_customer_by_id(customer_id)
        if not customer:
            print("Customer not found for manual payment notification")
            return

        method_labels = {
            'venmo': 'Venmo (@shaunacs)',
            'cashapp': 'CashApp ($shaunacs14)',
            'zelle': 'Zelle (shauna.saunders@yahoo.com)'
        }

        email_body = f"""Manual Payment Notification

Customer: {customer['name']} ({customer['email']})
Project: {project['project_name']}
Project Type: {project['project_type']}
Monthly Rate: ${project['total_amount']:.2f}
Payment Method: {method_labels.get(payment_method_used, payment_method_used)}
Reported at: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}

Customer Contact Information:
- Email: {customer['email']}
- Company: {customer.get('company', 'N/A')}
- Phone: {customer.get('phone', 'N/A')}

ACTION REQUIRED: Please verify the payment was received and update the customer's payment status in the admin portal.

This is an automated notification from your customer management system.
"""

        result = ses_send_email(
            to_email='shauna.saunders@alumni.unc.edu',
            subject=f'Manual Payment Received: {customer["name"]} - {project["project_name"]}',
            body=email_body
        )

        if result['success']:
            print(f"Manual payment notification sent for customer {customer['name']}")
        else:
            print(f"Failed to send manual payment notification: {result.get('error')}")

    except Exception as e:
        print(f"Error sending manual payment notification: {str(e)}")


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


@customers_bp.route('/feature-requests')
@customer_login_required
def all_feature_requests():
    """View all feature requests for the logged-in customer"""
    customer_id = session['customer_id']
    customer = get_customer_by_id(customer_id)
    
    # Get all feature requests for this customer
    feature_requests = get_feature_requests_by_customer(customer_id)
    
    # Get projects for context
    projects = get_projects_by_customer(customer_id)
    projects_dict = {p['id']: p for p in projects}

    return render_template('customers/all_feature_requests.html',
                         customer=customer,
                         feature_requests=feature_requests,
                         projects_dict=projects_dict)


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

        result = ses_send_email(
            to_email='shauna.saunders@alumni.unc.edu',
            subject=f'New Feature Request: {feature_request["title"]} - {feature_request["customer_name"]}',
            body=email_body
        )

        if result['success']:
            print(f"Feature request notification sent for request #{feature_request_id}")
        else:
            print(f"Failed to send feature request notification: {result.get('error')}")

    except Exception as e:
        import traceback
        print(f"ERROR sending feature request notification: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")


def send_status_update_notification(feature_request_id, old_status, new_status, status_message=None):
    """Send email notification when feature request status is updated"""
    try:
        feature_request = get_feature_request_by_id(feature_request_id)
        if not feature_request:
            print("Feature request not found for status update notification")
            return

        # Use project-specific email if defined, otherwise fall back to customer email
        recipient_email = feature_request.get('project_email') or feature_request['customer_email']

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

        # Build the link to the feature request detail page
        feature_request_url = f"{BASE_URL}/customers/feature-request/{feature_request_id}"

        email_body = f"""
Feature Request Status Update

Hi {feature_request['customer_name']},

Your feature request has been updated:

Request: {feature_request['title']}
Project: {feature_request['project_name']}

Status changed from "{old_status_name}" to "{new_status_name}"

{f"Update: {status_message}" if status_message else ""}

{f"Admin Notes: {feature_request['admin_notes']}" if feature_request.get('admin_notes') else ""}

You can view the full details and history at: {feature_request_url}

Thanks,
Shauna Saunders
"""

        result = ses_send_email(
            to_email=recipient_email,
            subject=f'Status Update: {feature_request["title"]} - Now {new_status_name}',
            body=email_body,
            reply_to='shauna.saunders@alumni.unc.edu'
        )

        if result['success']:
            print(f"Status update notification sent to {recipient_email} for request #{feature_request_id}")
        else:
            print(f"Failed to send status update notification: {result.get('error')}")

    except Exception as e:
        print(f"Error sending status update notification: {str(e)}")


# Agreement Routes

@customers_bp.route('/agreements')
@customer_login_required
def agreements():
    """View all agreements (signed and unsigned)"""
    customer_id = session['customer_id']

    unsigned_agreements = get_unsigned_agreements_for_customer(customer_id)
    signed_agreements = get_signed_agreements_for_customer(customer_id)

    return render_template('customers/agreements.html',
                         unsigned_agreements=unsigned_agreements,
                         signed_agreements=signed_agreements)


@customers_bp.route('/agreement/<int:agreement_id>')
@customer_login_required
def view_agreement(agreement_id):
    """View a specific agreement"""
    customer_id = session['customer_id']
    agreement = get_agreement_by_id(agreement_id)

    if not agreement:
        flash('Agreement not found.', 'error')
        return redirect(url_for('customers.dashboard'))

    # Security: Ensure agreement belongs to a project owned by this customer
    if agreement['customer_id'] != customer_id:
        flash('You do not have permission to view this agreement.', 'error')
        return redirect(url_for('customers.dashboard'))

    # Check if already signed
    signature = get_agreement_signature(agreement_id, customer_id)

    return render_template('customers/view_agreement.html',
                         agreement=agreement,
                         signature=signature)


@customers_bp.route('/agreement/<int:agreement_id>/sign', methods=['GET', 'POST'])
@customer_login_required
def sign_agreement_route(agreement_id):
    """Sign an agreement"""
    customer_id = session['customer_id']
    customer = get_customer_by_id(customer_id)
    agreement = get_agreement_by_id(agreement_id)

    if not agreement:
        flash('Agreement not found.', 'error')
        return redirect(url_for('customers.dashboard'))

    # Security: Ensure agreement belongs to a project owned by this customer
    if agreement['customer_id'] != customer_id:
        flash('You do not have permission to sign this agreement.', 'error')
        return redirect(url_for('customers.dashboard'))

    # Check if already signed
    existing_signature = get_agreement_signature(agreement_id, customer_id)
    if existing_signature:
        flash('You have already signed this agreement.', 'info')
        return redirect(url_for('customers.view_agreement', agreement_id=agreement_id))

    # Check if agreement is still active
    if not agreement['is_active']:
        flash('This agreement is no longer active. Please contact support.', 'error')
        return redirect(url_for('customers.agreements'))

    if request.method == 'POST':
        signature_name = request.form.get('signature_name', '').strip()
        agree_checkbox = request.form.get('agree_terms') == 'on'

        if not signature_name:
            flash('Please type your full legal name to sign.', 'error')
            return render_template('customers/sign_agreement.html',
                                 agreement=agreement,
                                 customer=customer)

        if not agree_checkbox:
            flash('You must agree to the terms to sign this agreement.', 'error')
            return render_template('customers/sign_agreement.html',
                                 agreement=agreement,
                                 customer=customer)

        # Get client IP address
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if client_ip and ',' in client_ip:
            client_ip = client_ip.split(',')[0].strip()

        signature_id = sign_agreement(
            agreement_id=agreement_id,
            customer_id=customer_id,
            signature_name=signature_name,
            signature_ip=client_ip
        )

        if signature_id:
            flash('Agreement signed successfully! Thank you.', 'success')
            return redirect(url_for('customers.view_agreement', agreement_id=agreement_id))
        else:
            flash('Unable to sign agreement. Please try again or contact support.', 'error')

    return render_template('customers/sign_agreement.html',
                         agreement=agreement,
                         customer=customer)


@customers_bp.route('/project/<int:project_id>/agreement')
@customer_login_required
def project_agreement(project_id):
    """View or sign the agreement for a specific project"""
    customer_id = session['customer_id']
    project = get_project_by_id(project_id)

    # Security: Ensure project belongs to logged-in customer
    if not project or project['customer_id'] != customer_id:
        flash('Project not found.', 'error')
        return redirect(url_for('customers.dashboard'))

    # Get active agreement for this project
    agreement = get_active_agreement_for_project(project_id)

    if not agreement:
        flash('No agreement has been created for this project yet.', 'info')
        return redirect(url_for('customers.project_detail', project_id=project_id))

    # Check if already signed
    signature = get_agreement_signature(agreement['id'], customer_id)

    if signature:
        return redirect(url_for('customers.view_agreement', agreement_id=agreement['id']))
    else:
        return redirect(url_for('customers.sign_agreement_route', agreement_id=agreement['id']))


# Stripe webhook handler moved to server.py to avoid CSRF issues
