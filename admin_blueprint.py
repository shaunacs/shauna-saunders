"""Blueprint for admin interface - customer and project management"""

import os
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
from functools import wraps
import stripe
from ses_helper import send_email as ses_send_email
import twilio_helper

from customers_db import (
    get_db, get_all_customers, get_customer_by_id, create_customer, update_customer,
    update_customer_password, deactivate_customer, activate_customer, delete_customer, get_all_projects,
    get_project_by_id, create_project, update_project, delete_project, get_projects_by_customer,
    get_milestones_by_project, get_milestone_by_id, create_milestone, mark_milestone_complete,
    delete_milestone, get_payments_by_customer, get_payments_by_project, get_payment_history,
    get_payment_links_by_customer, save_payment_link, get_customer_total_paid,
    get_outstanding_balance, get_project_completion_percentage, get_all_contact_submissions,
    convert_contact_to_customer, update_contact_submission_status, get_all_feature_requests,
    get_feature_request_by_id, update_feature_request_status, update_feature_request,
    get_feature_request_history, create_feature_request, get_all_agreements, get_agreement_by_id,
    create_agreement, get_agreements_by_project, get_all_signatures_for_agreement,
    get_agreement_template, replace_agreement_placeholders, get_active_agreement_for_project,
    get_agreement_signature, create_payment, update_project_paid_amount,
    get_payment_link_by_id, confirm_payment_link_manual
)
from customers_blueprint import send_status_update_notification

# Import database functions from traitors_db for admin authentication
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from traitors_db import verify_user, get_user_by_id

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Initialize Stripe
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')


# Admin Authentication Decorator
def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access the admin panel.', 'error')
            return redirect(url_for('admin.login'))

        user = get_user_by_id(session['user_id'])
        if not user or not user['is_admin']:
            flash('Admin access required.', 'error')
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated_function


# Admin Login/Logout

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Admin login page"""
    if 'user_id' in session:
        user = get_user_by_id(session['user_id'])
        if user and user['is_admin']:
            return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = verify_user(username, password)
        if user and user['is_admin']:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = True
            flash(f'Welcome, {user["username"]}!', 'success')
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Invalid credentials or insufficient permissions.', 'error')

    return render_template('admin/login.html')


@admin_bp.route('/logout')
def logout():
    """Admin logout"""
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('admin.login'))


# Admin Dashboard

@admin_bp.route('/')
@admin_required
def dashboard():
    """Admin dashboard with overview statistics"""
    # Get statistics
    total_customers = len(get_all_customers())
    active_customers = len(get_all_customers(active_only=True))
    all_projects = get_all_projects()
    active_projects = [p for p in all_projects if p['status'] in ['pending', 'in_progress']]

    # Calculate revenue
    all_payments = get_payment_history(limit=1000)
    total_revenue = sum(p['amount'] for p in all_payments if p['status'] == 'succeeded')
    this_month_revenue = sum(
        p['amount'] for p in all_payments
        if p['status'] == 'succeeded' and p['created_at'] and p['created_at'].startswith(datetime.now().strftime('%Y-%m'))
    )

    # Pending payments (projects with outstanding balance)
    pending_payments = sum(
        p['total_amount'] - p['amount_paid']
        for p in all_projects
        if p['status'] != 'cancelled'
    )

    # Recent activity
    recent_payments = get_payment_history(limit=10)
    recent_contacts = get_all_contact_submissions()[:10]

    return render_template('admin/dashboard.html',
                         total_customers=total_customers,
                         active_customers=active_customers,
                         total_projects=len(all_projects),
                         active_projects_count=len(active_projects),
                         total_revenue=total_revenue,
                         this_month_revenue=this_month_revenue,
                         pending_payments=pending_payments,
                         recent_payments=recent_payments,
                         recent_contacts=recent_contacts)


# Customer Management

@admin_bp.route('/customers')
@admin_required
def customers():
    """List all customers"""
    all_customers = get_all_customers()
    return render_template('admin/customers.html', customers=all_customers)


@admin_bp.route('/customers/create', methods=['GET', 'POST'])
@admin_required
def create_customer_route():
    """Create a new customer"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        name = request.form.get('name', '').strip()
        password = request.form.get('password', '')
        company = request.form.get('company', '').strip() or None
        phone = request.form.get('phone', '').strip() or None
        sms_opted_in = bool(request.form.get('sms_opted_in')) and bool(phone)

        # Validation
        if not all([email, name, password]):
            flash('Email, name, and password are required.', 'error')
            return render_template('admin/customer_form.html', customer=None)

        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return render_template('admin/customer_form.html', customer=None)

        # Create customer using the imported database function
        from customers_db import create_customer as db_create_customer
        customer_id = db_create_customer(
            email=email,
            name=name,
            password=password,
            company=company,
            phone=phone,
            sms_opted_in=sms_opted_in,
            created_by_admin_id=session.get('user_id')
        )

        if customer_id:
            flash(f'Customer "{name}" created successfully!', 'success')
            return redirect(url_for('admin.customer_detail', customer_id=customer_id))
        else:
            flash('Email already exists. Please use a different email.', 'error')
            return render_template('admin/customer_form.html', customer=None)

    return render_template('admin/customer_form.html', customer=None)


@admin_bp.route('/customers/<int:customer_id>')
@admin_required
def customer_detail(customer_id):
    """View customer details"""
    customer = get_customer_by_id(customer_id)
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('admin.customers'))

    projects = get_projects_by_customer(customer_id)
    payments = get_payments_by_customer(customer_id)
    payment_links = get_payment_links_by_customer(customer_id, include_used=True)

    total_paid = get_customer_total_paid(customer_id)
    outstanding = get_outstanding_balance(customer_id)

    return render_template('admin/customer_detail.html',
                         customer=customer,
                         projects=projects,
                         payments=payments,
                         payment_links=payment_links,
                         total_paid=total_paid,
                         outstanding=outstanding)


@admin_bp.route('/customers/<int:customer_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_customer(customer_id):
    """Edit customer details"""
    customer = get_customer_by_id(customer_id)
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('admin.customers'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        company = request.form.get('company', '').strip() or None
        phone = request.form.get('phone', '').strip() or None
        sms_opted_in = bool(request.form.get('sms_opted_in')) and bool(phone)

        if not all([name, email]):
            flash('Name and email are required.', 'error')
            return render_template('admin/customer_form.html', customer=customer)

        update_customer(customer_id, name=name, email=email, company=company, phone=phone, sms_opted_in=sms_opted_in)
        flash(f'Customer "{name}" updated successfully!', 'success')
        return redirect(url_for('admin.customer_detail', customer_id=customer_id))

    return render_template('admin/customer_form.html', customer=customer)


@admin_bp.route('/customers/<int:customer_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_customer_active(customer_id):
    """Toggle customer active status"""
    customer = get_customer_by_id(customer_id)
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('admin.customers'))

    if customer['is_active']:
        deactivate_customer(customer_id)
        flash(f'Customer "{customer["name"]}" deactivated.', 'success')
    else:
        activate_customer(customer_id)
        flash(f'Customer "{customer["name"]}" activated.', 'success')

    return redirect(url_for('admin.customer_detail', customer_id=customer_id))


@admin_bp.route('/customers/<int:customer_id>/delete', methods=['POST'])
@admin_required
def delete_customer_route(customer_id):
    """Delete a customer"""
    customer = get_customer_by_id(customer_id)
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('admin.customers'))

    delete_customer(customer_id)
    flash(f'Customer "{customer["name"]}" deleted.', 'success')
    return redirect(url_for('admin.customers'))


@admin_bp.route('/customers/<int:customer_id>/change-password', methods=['POST'])
@admin_required
def change_customer_password(customer_id):
    """Change a customer's password"""
    customer = get_customer_by_id(customer_id)
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('admin.customers'))

    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if len(new_password) < 8:
        flash('Password must be at least 8 characters.', 'error')
        return redirect(url_for('admin.customer_detail', customer_id=customer_id))

    if new_password != confirm_password:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('admin.customer_detail', customer_id=customer_id))

    update_customer_password(customer_id, new_password)
    flash(f'Password for "{customer["name"]}" updated successfully.', 'success')
    return redirect(url_for('admin.customer_detail', customer_id=customer_id))


# Project Management

@admin_bp.route('/projects')
@admin_required
def projects():
    """List all projects"""
    all_projects = get_all_projects()
    return render_template('admin/projects.html', projects=all_projects)


@admin_bp.route('/projects/create', methods=['GET', 'POST'])
@admin_required
def create_project_route():
    """Create a new project"""
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        project_name = request.form.get('project_name', '').strip()
        project_type = request.form.get('project_type')
        total_amount = request.form.get('total_amount')
        payment_plan = request.form.get('payment_plan')
        description = request.form.get('description', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        email = request.form.get('email', '').strip() or None
        is_subscription = request.form.get('is_subscription') == '1'
        payment_method_type = request.form.get('payment_method_type', 'stripe')
        stripe_price_id = request.form.get('stripe_price_id', '').strip() or None

        # Validation
        if not all([customer_id, project_name, project_type, total_amount]):
            flash('Customer, project name, type, and amount are required.', 'error')
            customers = get_all_customers(active_only=True)
            return render_template('admin/project_form.html', project=None, customers=customers)

        if is_subscription and payment_method_type in ('stripe', 'both') and not stripe_price_id:
            flash('Stripe Price ID is required for Stripe subscription projects.', 'error')
            customers = get_all_customers(active_only=True)
            return render_template('admin/project_form.html', project=None, customers=customers)

        try:
            total_amount = float(total_amount)
        except ValueError:
            flash('Invalid amount.', 'error')
            customers = get_all_customers(active_only=True)
            return render_template('admin/project_form.html', project=None, customers=customers)

        # Create project
        project_id = create_project(
            customer_id=int(customer_id),
            project_name=project_name,
            project_type=project_type,
            total_amount=total_amount,
            payment_plan=payment_plan,
            description=description,
            notes=notes,
            is_subscription=is_subscription,
            stripe_price_id=stripe_price_id,
            email=email,
            payment_method_type=payment_method_type if is_subscription else 'stripe'
        )

        flash(f'Project "{project_name}" created successfully!', 'success')
        return redirect(url_for('admin.project_detail', project_id=project_id))

    customers = get_all_customers(active_only=True)
    return render_template('admin/project_form.html', project=None, customers=customers)


@admin_bp.route('/projects/<int:project_id>')
@admin_required
def project_detail(project_id):
    """View project details"""
    project = get_project_by_id(project_id)
    if not project:
        flash('Project not found.', 'error')
        return redirect(url_for('admin.projects'))

    customer = get_customer_by_id(project['customer_id'])
    milestones = get_milestones_by_project(project_id)
    payments = get_payments_by_project(project_id)

    completion_percentage = get_project_completion_percentage(project_id)

    # Get agreement info
    agreement = get_active_agreement_for_project(project_id)
    agreement_signature = None
    if agreement:
        agreement_signature = get_agreement_signature(agreement['id'], customer['id'])

    return render_template('admin/project_detail.html',
                         project=project,
                         customer=customer,
                         milestones=milestones,
                         payments=payments,
                         completion_percentage=completion_percentage,
                         agreement=agreement,
                         agreement_signature=agreement_signature)


@admin_bp.route('/projects/<int:project_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_project(project_id):
    """Edit project details"""
    project = get_project_by_id(project_id)
    if not project:
        flash('Project not found.', 'error')
        return redirect(url_for('admin.projects'))

    if request.method == 'POST':
        project_name = request.form.get('project_name', '').strip()
        project_type = request.form.get('project_type')
        status = request.form.get('status')
        total_amount = request.form.get('total_amount')
        payment_plan = request.form.get('payment_plan')
        description = request.form.get('description', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        email = request.form.get('email', '').strip() or None
        is_subscription = request.form.get('is_subscription') == '1'
        payment_method_type = request.form.get('payment_method_type', 'stripe')
        stripe_price_id = request.form.get('stripe_price_id', '').strip() or None

        if not all([project_name, project_type, total_amount]):
            flash('Project name, type, and amount are required.', 'error')
            customers = get_all_customers(active_only=True)
            return render_template('admin/project_form.html', project=project, customers=customers)

        if is_subscription and payment_method_type in ('stripe', 'both') and not stripe_price_id:
            flash('Stripe Price ID is required for Stripe subscription projects.', 'error')
            customers = get_all_customers(active_only=True)
            return render_template('admin/project_form.html', project=project, customers=customers)

        try:
            total_amount = float(total_amount)
        except ValueError:
            flash('Invalid amount.', 'error')
            customers = get_all_customers(active_only=True)
            return render_template('admin/project_form.html', project=project, customers=customers)

        update_project(
            project_id,
            project_name=project_name,
            project_type=project_type,
            status=status,
            total_amount=total_amount,
            payment_plan=payment_plan,
            description=description,
            notes=notes,
            email=email,
            is_subscription=is_subscription,
            stripe_price_id=stripe_price_id,
            payment_method_type=payment_method_type if is_subscription else 'stripe'
        )

        flash(f'Project "{project_name}" updated successfully!', 'success')
        return redirect(url_for('admin.project_detail', project_id=project_id))

    customers = get_all_customers(active_only=True)
    return render_template('admin/project_form.html', project=project, customers=customers)


@admin_bp.route('/projects/<int:project_id>/delete', methods=['POST'])
@admin_required
def delete_project_route(project_id):
    """Delete a project"""
    project = get_project_by_id(project_id)
    if not project:
        flash('Project not found.', 'error')
        return redirect(url_for('admin.projects'))

    delete_project(project_id)
    flash(f'Project "{project["project_name"]}" deleted.', 'success')
    return redirect(url_for('admin.projects'))


def send_payment_link_notification(customer, amount, description, link_url):
    """Email and SMS the customer that a payment link has been generated for them"""
    if not customer:
        return

    dashboard_url = "https://shaunasaunders.com/customers/dashboard"

    body = f"""Hi {customer['name']},

A payment of ${amount:.2f} is ready for you{f' — {description}' if description else ''}.

You can view and complete your payment in your dashboard:
{dashboard_url}

If you have any questions, feel free to reply to this email.

— Shauna
"""
    try:
        ses_send_email(
            to_email=customer['email'],
            subject='Payment Ready',
            body=body,
            reply_to='shauna.saunders@alumni.unc.edu'
        )
    except Exception as e:
        print(f"Error sending payment link email: {str(e)}")

    if customer.get('phone') and customer.get('sms_opted_in'):
        sms_body = (
            f"Hi {customer['name']}, you have a payment of ${amount:.2f} due"
            f"{f' ({description})' if description else ''}."
            f" Log in to your dashboard to complete your payment: {dashboard_url}"
        )
        try:
            twilio_helper.send_sms(to_phone=customer['phone'], body=sms_body)
        except Exception as e:
            print(f"Error sending payment link SMS: {str(e)}")


def send_payment_waived_notification(project, amount, next_payment_date,
                                      operating_cost_amount=None, operating_cost_description=None,
                                      operating_cost_link=None):
    """Email the customer (and project email if set) that a payment has been waived"""
    try:
        from customers_db import get_customer_by_id
        customer = get_customer_by_id(project['customer_id'])
        if not customer:
            print("Customer not found for waive notification")
            return

        # Build recipient list, deduping if project email matches customer email
        recipients = [customer['email']]
        project_email = (project.get('email') or '').strip()
        if project_email and project_email.lower() != customer['email'].lower():
            recipients.append(project_email)

        dashboard_url = "https://shaunasaunders.com/customers/dashboard"

        next_payment_str = (
            next_payment_date.strftime('%B %d, %Y')
            if next_payment_date
            else 'not yet scheduled'
        )

        if operating_cost_amount and operating_cost_link:
            cost_description = operating_cost_description or 'operating costs'
            operating_cost_section = f"""
While your payment has been waived, there are still outstanding operating costs that need to be covered:

${operating_cost_amount:.2f} – {cost_description}

You can pay by card or via Venmo, CashApp, or Zelle — visit your dashboard to view the payment and choose your preferred method:
{dashboard_url}
"""
        else:
            operating_cost_section = ''

        no_action = ' No action is needed from you.' if not operating_cost_section else ''

        body = f"""Hi {customer['name']},

Your payment of ${amount:.2f} for {project['project_name']} has been waived for this period.{no_action}
{operating_cost_section}
Your next payment date is: {next_payment_str}

You can track your account and payment history in your dashboard at any time:
{dashboard_url}

Feel free to reach out if you have any questions.

— Shauna

---
This is an automated message.
"""

        ses_send_email(
            to_email=recipients,
            subject=f'Payment Waived – {project["project_name"]}',
            body=body,
            reply_to='shauna.saunders@alumni.unc.edu'
        )

    except Exception as e:
        print(f"Error sending payment waived notification: {str(e)}")


# Subscription Management

@admin_bp.route('/projects/<int:project_id>/subscription', methods=['GET', 'POST'])
@admin_required
def manage_subscription(project_id):
    """Manage subscription details for a project"""
    project = get_project_by_id(project_id)
    if not project:
        flash('Project not found.', 'error')
        return redirect(url_for('admin.projects'))

    customer = get_customer_by_id(project['customer_id'])

    # Get current Stripe subscription info if exists
    stripe_subscription = None
    if project.get('stripe_subscription_id'):
        try:
            stripe_subscription = stripe.Subscription.retrieve(project['stripe_subscription_id'])
        except stripe.error.StripeError:
            pass

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_details':
            # Manual update of subscription details
            subscription_status = request.form.get('subscription_status')
            stripe_subscription_id = request.form.get('stripe_subscription_id', '').strip() or None
            next_payment_date_str = request.form.get('next_payment_date', '').strip()

            next_payment_date = None
            if next_payment_date_str:
                try:
                    next_payment_date = datetime.strptime(next_payment_date_str, '%Y-%m-%d')
                except ValueError:
                    flash('Invalid date format for next payment date.', 'error')
                    return redirect(url_for('admin.manage_subscription', project_id=project_id))

            update_project(
                project_id,
                subscription_status=subscription_status,
                stripe_subscription_id=stripe_subscription_id,
                next_payment_date=next_payment_date
            )
            flash('Subscription details updated successfully!', 'success')
            return redirect(url_for('admin.manage_subscription', project_id=project_id))

        elif action == 'create_stripe_subscription':
            # Create a Stripe subscription with a future billing date
            if not project.get('stripe_price_id'):
                flash('Stripe Price ID is required to create a subscription.', 'error')
                return redirect(url_for('admin.manage_subscription', project_id=project_id))

            first_payment_date_str = request.form.get('first_payment_date', '').strip()
            if not first_payment_date_str:
                flash('First payment date is required.', 'error')
                return redirect(url_for('admin.manage_subscription', project_id=project_id))

            try:
                first_payment_date = datetime.strptime(first_payment_date_str, '%Y-%m-%d')
                # Stripe requires trial_end to be at least 48 hours in the future
                min_date = datetime.now() + timedelta(hours=48)
                if first_payment_date < min_date:
                    flash('First payment date must be at least 48 hours in the future.', 'error')
                    return redirect(url_for('admin.manage_subscription', project_id=project_id))
                billing_anchor = int(first_payment_date.timestamp())
            except ValueError:
                flash('Invalid date format.', 'error')
                return redirect(url_for('admin.manage_subscription', project_id=project_id))

            try:
                # Find or create Stripe customer
                stripe_customers = stripe.Customer.list(email=customer['email'], limit=1)
                if stripe_customers.data:
                    stripe_customer = stripe_customers.data[0]
                else:
                    stripe_customer = stripe.Customer.create(
                        email=customer['email'],
                        name=customer['name'],
                        metadata={
                            'customer_id': str(customer['id']),
                            'project_id': str(project_id)
                        }
                    )

                # Create subscription with future billing anchor
                # Using trial_end to delay the first charge
                subscription = stripe.Subscription.create(
                    customer=stripe_customer.id,
                    items=[{'price': project['stripe_price_id']}],
                    trial_end=billing_anchor,
                    metadata={
                        'customer_id': str(customer['id']),
                        'project_id': str(project_id)
                    }
                )

                # Update project with subscription info
                update_project(
                    project_id,
                    stripe_subscription_id=subscription.id,
                    subscription_status='active',
                    next_payment_date=first_payment_date
                )

                flash(f'Stripe subscription created! First payment on {first_payment_date_str}. Subscription ID: {subscription.id}', 'success')
                return redirect(url_for('admin.manage_subscription', project_id=project_id))

            except stripe.error.StripeError as e:
                flash(f'Stripe error: {str(e)}', 'error')
                return redirect(url_for('admin.manage_subscription', project_id=project_id))

        elif action == 'sync_from_stripe':
            # Sync local data from Stripe subscription
            if not project.get('stripe_subscription_id'):
                flash('No Stripe subscription ID to sync from.', 'error')
                return redirect(url_for('admin.manage_subscription', project_id=project_id))

            try:
                sub = stripe.Subscription.retrieve(project['stripe_subscription_id'])
                next_payment = datetime.fromtimestamp(sub.current_period_end)

                status_map = {
                    'active': 'active',
                    'past_due': 'past_due',
                    'canceled': 'cancelled',
                    'unpaid': 'past_due',
                    'trialing': 'active'
                }
                local_status = status_map.get(sub.status, 'inactive')

                update_project(
                    project_id,
                    subscription_status=local_status,
                    next_payment_date=next_payment
                )
                flash(f'Synced from Stripe! Status: {local_status}, Next payment: {next_payment.strftime("%Y-%m-%d")}', 'success')
            except stripe.error.StripeError as e:
                flash(f'Stripe error: {str(e)}', 'error')

            return redirect(url_for('admin.manage_subscription', project_id=project_id))

        elif action == 'record_manual_payment':
            # Record a manual payment (Venmo/CashApp/Zelle/Waived)
            payment_amount_str = request.form.get('payment_amount', '').strip()
            payment_method = request.form.get('payment_method', '').strip()
            payment_date_str = request.form.get('payment_date', '').strip()
            next_payment_date_str = request.form.get('next_payment_date_manual', '').strip()
            payment_notes = request.form.get('payment_notes', '').strip() or None
            operating_cost_amount_str = request.form.get('operating_cost_amount', '').strip()
            operating_cost_description = request.form.get('operating_cost_description', '').strip() or None

            if not payment_amount_str or not payment_method:
                flash('Payment amount and method are required.', 'error')
                return redirect(url_for('admin.manage_subscription', project_id=project_id))

            if payment_method not in ('venmo', 'cashapp', 'zelle', 'waived'):
                flash('Invalid payment method.', 'error')
                return redirect(url_for('admin.manage_subscription', project_id=project_id))

            try:
                payment_amount = float(payment_amount_str)
            except ValueError:
                flash('Invalid payment amount.', 'error')
                return redirect(url_for('admin.manage_subscription', project_id=project_id))

            paid_at = None
            if payment_date_str:
                try:
                    paid_at = datetime.strptime(payment_date_str, '%Y-%m-%d')
                except ValueError:
                    flash('Invalid payment date format.', 'error')
                    return redirect(url_for('admin.manage_subscription', project_id=project_id))

            next_payment_date = None
            if next_payment_date_str:
                try:
                    next_payment_date = datetime.strptime(next_payment_date_str, '%Y-%m-%d')
                except ValueError:
                    flash('Invalid next payment date format.', 'error')
                    return redirect(url_for('admin.manage_subscription', project_id=project_id))

            method_labels = {'venmo': 'Venmo', 'cashapp': 'CashApp', 'zelle': 'Zelle', 'waived': 'Waived'}
            is_waived = payment_method == 'waived'

            if is_waived:
                description = 'Payment waived' + (f' - {payment_notes}' if payment_notes else '')
            else:
                description = f'Manual payment via {method_labels[payment_method]}' + (f' - {payment_notes}' if payment_notes else '')

            # Create payment record
            create_payment(
                customer_id=project['customer_id'],
                amount=payment_amount,
                payment_type='subscription',
                project_id=project_id,
                status='succeeded',
                payment_method=payment_method,
                description=description,
                stripe_payment_intent_id=f'manual_{project_id}_{int(datetime.now().timestamp())}'
            )

            # Only update amount paid if it was actually received (not waived)
            if not is_waived:
                update_project_paid_amount(project_id, payment_amount)

            # Update next payment date if provided
            if next_payment_date:
                update_project(project_id, next_payment_date=next_payment_date)

            if is_waived:
                operating_cost_amount = None
                operating_cost_link = None
                if operating_cost_amount_str:
                    try:
                        operating_cost_amount = float(operating_cost_amount_str)
                    except ValueError:
                        pass

                if operating_cost_amount:
                    try:
                        customer = get_customer_by_id(project['customer_id'])
                        price = stripe.Price.create(
                            currency='usd',
                            unit_amount=int(operating_cost_amount * 100),
                            product_data={'name': operating_cost_description or 'Operating Costs'},
                        )
                        payment_link = stripe.PaymentLink.create(
                            line_items=[{'price': price.id, 'quantity': 1}],
                            after_completion={
                                'type': 'redirect',
                                'redirect': {'url': 'https://shaunasaunders.com/customers/payment-success'},
                            },
                            restrictions={'completed_sessions': {'limit': 1}},
                            metadata={
                                'customer_id': str(project['customer_id']),
                                'project_id': str(project_id),
                                'admin_generated': 'true'
                            }
                        )
                        operating_cost_link = payment_link.url
                        save_payment_link(
                            customer_id=project['customer_id'],
                            project_id=project_id,
                            amount=operating_cost_amount,
                            stripe_checkout_url=payment_link.url,
                            stripe_session_id=payment_link.id,
                            description=operating_cost_description or 'Operating Costs',
                            created_by_admin_id=session.get('user_id')
                        )
                    except Exception as e:
                        print(f"Error creating operating cost payment link: {str(e)}")

                send_payment_waived_notification(
                    project, payment_amount, next_payment_date,
                    operating_cost_amount=operating_cost_amount,
                    operating_cost_description=operating_cost_description,
                    operating_cost_link=operating_cost_link
                )
                flash(f'Payment of ${payment_amount:.2f} recorded as waived.', 'success')
            else:
                flash(f'Manual payment of ${payment_amount:.2f} via {method_labels[payment_method]} recorded successfully!', 'success')
            return redirect(url_for('admin.manage_subscription', project_id=project_id))

        elif action == 'switch_payment_method':
            new_method_type = request.form.get('new_payment_method_type', '').strip()
            if new_method_type not in ('stripe', 'manual', 'both'):
                flash('Invalid payment method type.', 'error')
                return redirect(url_for('admin.manage_subscription', project_id=project_id))

            update_project(project_id, payment_method_type=new_method_type)
            labels = {'stripe': 'Stripe Only (Autopay)', 'manual': 'Manual Only (Venmo/CashApp/Zelle)', 'both': 'Both (Customer Chooses)'}
            flash(f'Payment method switched to {labels[new_method_type]}.', 'success')
            return redirect(url_for('admin.manage_subscription', project_id=project_id))

    return render_template('admin/subscription_form.html',
                          project=project,
                          customer=customer,
                          stripe_subscription=stripe_subscription,
                          now=datetime.now())


# Milestone Management

@admin_bp.route('/projects/<int:project_id>/milestones/create', methods=['POST'])
@admin_required
def create_milestone_route(project_id):
    """Create a milestone for a project"""
    project = get_project_by_id(project_id)
    if not project:
        flash('Project not found.', 'error')
        return redirect(url_for('admin.projects'))

    milestone_name = request.form.get('milestone_name', '').strip()
    description = request.form.get('description', '').strip() or None
    is_payment_milestone = request.form.get('is_payment_milestone') == 'on'
    payment_amount = request.form.get('payment_amount')

    if not milestone_name:
        flash('Milestone name is required.', 'error')
        return redirect(url_for('admin.project_detail', project_id=project_id))

    if is_payment_milestone and payment_amount:
        try:
            payment_amount = float(payment_amount)
        except ValueError:
            payment_amount = None
    else:
        payment_amount = None

    # Get next order index
    existing_milestones = get_milestones_by_project(project_id)
    order_index = len(existing_milestones)

    create_milestone(
        project_id=project_id,
        milestone_name=milestone_name,
        description=description,
        is_payment_milestone=is_payment_milestone,
        payment_amount=payment_amount,
        order_index=order_index
    )

    flash(f'Milestone "{milestone_name}" created successfully!', 'success')
    return redirect(url_for('admin.project_detail', project_id=project_id))


@admin_bp.route('/milestones/<int:milestone_id>/complete', methods=['POST'])
@admin_required
def complete_milestone(milestone_id):
    """Mark milestone as complete"""
    milestone = get_milestone_by_id(milestone_id)
    if not milestone:
        flash('Milestone not found.', 'error')
        return redirect(url_for('admin.projects'))

    mark_milestone_complete(milestone_id)
    flash(f'Milestone "{milestone["milestone_name"]}" marked as complete!', 'success')
    return redirect(url_for('admin.project_detail', project_id=milestone['project_id']))


@admin_bp.route('/milestones/<int:milestone_id>/delete', methods=['POST'])
@admin_required
def delete_milestone_route(milestone_id):
    """Delete a milestone"""
    milestone = get_milestone_by_id(milestone_id)
    if not milestone:
        flash('Milestone not found.', 'error')
        return redirect(url_for('admin.projects'))

    project_id = milestone['project_id']
    delete_milestone(milestone_id)
    flash(f'Milestone "{milestone["milestone_name"]}" deleted.', 'success')
    return redirect(url_for('admin.project_detail', project_id=project_id))


# Payment Link Generation

@admin_bp.route('/payment-links/create', methods=['GET', 'POST'])
@admin_required
def create_payment_link():
    """Generate a Stripe payment link for a customer"""
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        project_id = request.form.get('project_id') or None
        amount = request.form.get('amount')
        description = request.form.get('description', '').strip()

        # Validation
        if not all([customer_id, amount]):
            flash('Customer and amount are required.', 'error')
            return redirect(url_for('admin.create_payment_link'))

        try:
            amount = float(amount)
        except ValueError:
            flash('Invalid amount.', 'error')
            return redirect(url_for('admin.create_payment_link'))

        customer = get_customer_by_id(int(customer_id))

        # Create Stripe Payment Link (no expiry, single-use)
        try:
            price = stripe.Price.create(
                currency='usd',
                unit_amount=int(amount * 100),
                product_data={'name': description or 'Payment'},
            )

            payment_link = stripe.PaymentLink.create(
                line_items=[{'price': price.id, 'quantity': 1}],
                after_completion={
                    'type': 'redirect',
                    'redirect': {'url': 'https://shaunasaunders.com/customers/payment-success'},
                },
                restrictions={'completed_sessions': {'limit': 1}},
                metadata={
                    'customer_id': customer_id,
                    'project_id': project_id or '',
                    'admin_generated': 'true'
                }
            )

            # Save payment link
            save_payment_link(
                customer_id=int(customer_id),
                project_id=int(project_id) if project_id else None,
                amount=amount,
                stripe_checkout_url=payment_link.url,
                stripe_session_id=payment_link.id,
                description=description,
                created_by_admin_id=session.get('user_id')
            )

            # Notify customer via email and SMS
            send_payment_link_notification(customer, amount, description, payment_link.url)

            flash(f'Payment link created! URL: {payment_link.url}', 'success')
            return redirect(url_for('admin.customer_detail', customer_id=customer_id))

        except Exception as e:
            flash(f'Error creating payment link: {str(e)}', 'error')
            return redirect(url_for('admin.create_payment_link'))

    customers = get_all_customers(active_only=True)
    all_projects = get_all_projects()
    # Group projects by customer_id for the template
    projects_by_customer = {}
    for project in all_projects:
        cid = project['customer_id']
        projects_by_customer.setdefault(cid, []).append({
            'id': project['id'],
            'name': project['project_name']
        })
    return render_template('admin/payment_link_form.html', customers=customers,
                           projects_by_customer=projects_by_customer)


@admin_bp.route('/payment-links/<int:link_id>/confirm-manual', methods=['POST'])
@admin_required
def confirm_manual_payment_link(link_id):
    """Admin confirms receipt of a manual payment for an admin-generated payment link"""
    link = get_payment_link_by_id(link_id)
    if not link:
        flash('Payment link not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    if link['used']:
        flash('This payment link is already marked as paid.', 'error')
        return redirect(url_for('admin.customer_detail', customer_id=link['customer_id']))

    # Record the payment
    create_payment(
        customer_id=link['customer_id'],
        project_id=link['project_id'],
        amount=link['amount'],
        payment_type='one_time',
        status='succeeded',
        payment_method='manual',
        description=link['description'] or 'One-time payment',
    )

    # Update project amount_paid if linked to a project
    if link['project_id']:
        update_project_paid_amount(link['project_id'], link['amount'])

    # Mark the link as fully paid
    confirm_payment_link_manual(link_id)

    flash(f'Payment of ${link["amount"]:.2f} confirmed.', 'success')
    return redirect(url_for('admin.customer_detail', customer_id=link['customer_id']))


# Payment History

@admin_bp.route('/payments')
@admin_required
def payments():
    """View all payments"""
    all_payments = get_payment_history(limit=100)
    return render_template('admin/payments.html', payments=all_payments)


# Contact Form Submissions

@admin_bp.route('/contacts')
@admin_required
def contacts():
    """View contact form submissions"""
    submissions = get_all_contact_submissions()
    return render_template('admin/contacts.html', submissions=submissions)


@admin_bp.route('/contacts/<int:submission_id>/convert', methods=['POST'])
@admin_required
def convert_contact(submission_id):
    """Convert contact submission to customer"""
    password = request.form.get('password', '')

    if len(password) < 8:
        flash('Password must be at least 8 characters.', 'error')
        return redirect(url_for('admin.contacts'))

    customer_id = convert_contact_to_customer(submission_id, password)

    if customer_id:
        flash('Contact converted to customer successfully!', 'success')
        return redirect(url_for('admin.customer_detail', customer_id=customer_id))
    else:
        flash('Failed to convert contact. Email may already exist.', 'error')
        return redirect(url_for('admin.contacts'))


@admin_bp.route('/contacts/<int:submission_id>/archive', methods=['POST'])
@admin_required
def archive_contact(submission_id):
    """Archive a contact submission"""
    update_contact_submission_status(submission_id, 'archived')
    flash('Contact archived.', 'success')
    return redirect(url_for('admin.contacts'))


# Feature Request Management

@admin_bp.route('/feature-requests')
@admin_required
def feature_requests():
    """View all feature requests"""
    status_filter = request.args.get('status')
    requests = get_all_feature_requests(status=status_filter)
    
    # Get status options
    status_options = [
        ('', 'All Requests'),
        ('request_received', 'Request Received'),
        ('in_review', 'In Review'),
        ('approved', 'Approved'),
        ('in_progress', 'In Progress'),
        ('testing', 'Testing'),
        ('completed', 'Completed'),
        ('on_hold', 'On Hold'),
        ('rejected', 'Rejected')
    ]
    
    return render_template('admin/feature_requests.html', 
                         requests=requests, 
                         status_options=status_options,
                         current_status=status_filter)


@admin_bp.route('/feature-requests/<int:request_id>')
@admin_required
def feature_request_detail(request_id):
    """View feature request details"""
    feature_request = get_feature_request_by_id(request_id)
    if not feature_request:
        flash('Feature request not found.', 'error')
        return redirect(url_for('admin.feature_requests'))

    # Get status history
    status_history = get_feature_request_history(request_id)

    return render_template('admin/feature_request_detail.html',
                         feature_request=feature_request,
                         status_history=status_history)


@admin_bp.route('/feature-requests/create', methods=['GET', 'POST'])
@admin_bp.route('/feature-requests/create/<int:project_id>', methods=['GET', 'POST'])
@admin_required
def create_feature_request_route(project_id=None):
    """Create a feature request on behalf of a customer"""
    # Get all projects for the dropdown (only ongoing_maintenance projects can have feature requests)
    all_projects = get_all_projects()
    maintenance_projects = [p for p in all_projects if p['project_type'] == 'ongoing_maintenance']

    if request.method == 'POST':
        selected_project_id = request.form.get('project_id')
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        priority = request.form.get('priority', 'medium')
        requested_completion = request.form.get('requested_completion', '').strip() or None
        additional_info = request.form.get('additional_info', '').strip() or None

        if not selected_project_id or not title or not description:
            flash('Project, title, and description are required.', 'error')
            return render_template('admin/create_feature_request.html',
                                 projects=maintenance_projects,
                                 selected_project_id=project_id)

        # Get the project to find the customer
        project = get_project_by_id(selected_project_id)
        if not project:
            flash('Project not found.', 'error')
            return redirect(url_for('admin.feature_requests'))

        # Create the feature request (no email notification to customer)
        feature_request_id = create_feature_request(
            customer_id=project['customer_id'],
            project_id=selected_project_id,
            title=title,
            description=description,
            priority=priority,
            requested_completion=requested_completion,
            additional_info=additional_info,
            created_by_admin=True
        )

        flash(f'Feature request created successfully! Customer will be notified when you update the status.', 'success')
        return redirect(url_for('admin.feature_request_detail', request_id=feature_request_id))

    return render_template('admin/create_feature_request.html',
                         projects=maintenance_projects,
                         selected_project_id=project_id)


@admin_bp.route('/feature-requests/<int:request_id>/update-status', methods=['POST'])
@admin_required
def update_feature_request_status_route(request_id):
    """Update feature request status"""
    feature_request = get_feature_request_by_id(request_id)
    if not feature_request:
        flash('Feature request not found.', 'error')
        return redirect(url_for('admin.feature_requests'))
    
    new_status = request.form.get('status')
    status_message = request.form.get('status_message', '').strip() or None
    admin_notes = request.form.get('admin_notes', '').strip() or None
    estimated_hours = request.form.get('estimated_hours', '').strip()
    actual_hours = request.form.get('actual_hours', '').strip()
    skip_notification = request.form.get('skip_notification') == 'on'
    
    # Parse hours
    try:
        estimated_hours = float(estimated_hours) if estimated_hours else None
    except ValueError:
        estimated_hours = None
        
    try:
        actual_hours = float(actual_hours) if actual_hours else None
    except ValueError:
        actual_hours = None
    
    # Update status and send notification
    old_status = feature_request['status']
    success = update_feature_request_status(
        request_id, 
        new_status, 
        status_message=status_message,
        admin_notes=admin_notes,
        admin_id=session.get('user_id')
    )
    
    if success:
        # Update additional fields
        update_data = {}
        if estimated_hours is not None:
            update_data['estimated_hours'] = estimated_hours
        if actual_hours is not None:
            update_data['actual_hours'] = actual_hours
        if admin_notes:
            update_data['admin_notes'] = admin_notes
            
        if update_data:
            update_feature_request(request_id, **update_data)

        # Send status update notification to customer (unless skipped)
        if skip_notification:
            flash('Feature request updated (notification skipped).', 'success')
        else:
            send_status_update_notification(request_id, old_status, new_status, status_message)
            flash('Feature request updated and customer notified!', 'success')
    else:
        flash('Error updating feature request.', 'error')
    
    return redirect(url_for('admin.feature_request_detail', request_id=request_id))


@admin_bp.route('/feature-requests/<int:request_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_feature_request(request_id):
    """Edit feature request details"""
    feature_request = get_feature_request_by_id(request_id)
    if not feature_request:
        flash('Feature request not found.', 'error')
        return redirect(url_for('admin.feature_requests'))
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        priority = request.form.get('priority')
        requested_completion = request.form.get('requested_completion', '').strip() or None
        additional_info = request.form.get('additional_info', '').strip() or None
        admin_notes = request.form.get('admin_notes', '').strip() or None
        estimated_hours = request.form.get('estimated_hours', '').strip()
        actual_hours = request.form.get('actual_hours', '').strip()
        
        if not title or not description:
            flash('Title and description are required.', 'error')
            return render_template('admin/feature_request_form.html', feature_request=feature_request)
        
        # Parse hours
        try:
            estimated_hours = float(estimated_hours) if estimated_hours else None
        except ValueError:
            estimated_hours = None
            
        try:
            actual_hours = float(actual_hours) if actual_hours else None
        except ValueError:
            actual_hours = None
        
        # Update feature request
        update_feature_request(
            request_id,
            title=title,
            description=description,
            priority=priority,
            requested_completion=requested_completion,
            additional_info=additional_info,
            admin_notes=admin_notes,
            estimated_hours=estimated_hours,
            actual_hours=actual_hours
        )
        
        flash('Feature request updated successfully!', 'success')
        return redirect(url_for('admin.feature_request_detail', request_id=request_id))
    
    return render_template('admin/feature_request_form.html', feature_request=feature_request)


@admin_bp.route('/feature-requests/<int:request_id>/delete', methods=['POST'])
@admin_required
def delete_feature_request(request_id):
    """Delete a feature request"""
    feature_request = get_feature_request_by_id(request_id)
    if not feature_request:
        flash('Feature request not found.', 'error')
        return redirect(url_for('admin.feature_requests'))

    # Delete from database
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM feature_requests WHERE id = ?', (request_id,))
    conn.commit()
    conn.close()

    flash(f'Feature request "{feature_request["title"]}" deleted.', 'success')
    return redirect(url_for('admin.feature_requests'))


# Agreement Management

@admin_bp.route('/agreements')
@admin_required
def agreements():
    """View all agreements"""
    include_inactive = request.args.get('include_inactive') == '1'
    all_agreements = get_all_agreements(include_inactive=include_inactive)
    return render_template('admin/agreements.html',
                         agreements=all_agreements,
                         include_inactive=include_inactive)


@admin_bp.route('/agreements/create', methods=['GET', 'POST'])
@admin_required
def create_agreement_route():
    """Create a new agreement for a project"""
    if request.method == 'POST':
        project_id = request.form.get('project_id')
        title = request.form.get('title', '').strip()
        agreement_type = request.form.get('agreement_type')
        content = request.form.get('content', '').strip()
        use_template = request.form.get('use_template') == '1'
        auto_replace = request.form.get('auto_replace') == '1'

        if not all([project_id, title, agreement_type]):
            flash('Project, title, and agreement type are required.', 'error')
            projects = get_all_projects()
            return render_template('admin/agreement_form.html', projects=projects, agreement=None)

        project = get_project_by_id(int(project_id))
        if not project:
            flash('Project not found.', 'error')
            projects = get_all_projects()
            return render_template('admin/agreement_form.html', projects=projects, agreement=None)

        # Get template content if requested
        if use_template or not content:
            content = get_agreement_template(agreement_type)

        # Auto-replace placeholders if requested
        if auto_replace:
            customer = get_customer_by_id(project['customer_id'])
            content = replace_agreement_placeholders(
                content,
                customer_name=customer['name'],
                project_name=project['project_name'],
                amount=project['total_amount']
            )

        agreement_id = create_agreement(
            project_id=int(project_id),
            title=title,
            content=content,
            agreement_type=agreement_type,
            created_by_admin_id=session.get('user_id')
        )

        flash(f'Agreement "{title}" created successfully!', 'success')
        return redirect(url_for('admin.agreement_detail', agreement_id=agreement_id))

    projects = get_all_projects()
    return render_template('admin/agreement_form.html', projects=projects, agreement=None)


@admin_bp.route('/agreements/<int:agreement_id>')
@admin_required
def agreement_detail(agreement_id):
    """View agreement details"""
    agreement = get_agreement_by_id(agreement_id)
    if not agreement:
        flash('Agreement not found.', 'error')
        return redirect(url_for('admin.agreements'))

    signatures = get_all_signatures_for_agreement(agreement_id)
    version_history = get_agreements_by_project(agreement['project_id'])

    return render_template('admin/agreement_detail.html',
                         agreement=agreement,
                         signatures=signatures,
                         version_history=version_history)


@admin_bp.route('/agreements/<int:agreement_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_agreement(agreement_id):
    """Edit agreement - creates a new version"""
    agreement = get_agreement_by_id(agreement_id)
    if not agreement:
        flash('Agreement not found.', 'error')
        return redirect(url_for('admin.agreements'))

    # Check if this agreement has signatures
    signatures = get_all_signatures_for_agreement(agreement_id)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        agreement_type = request.form.get('agreement_type')

        if not all([title, content, agreement_type]):
            flash('All fields are required.', 'error')
            projects = get_all_projects()
            return render_template('admin/agreement_form.html',
                                 projects=projects,
                                 agreement=agreement,
                                 has_signatures=len(signatures) > 0)

        # Create a new version (supersedes the old one)
        new_agreement_id = create_agreement(
            project_id=agreement['project_id'],
            title=title,
            content=content,
            agreement_type=agreement_type,
            created_by_admin_id=session.get('user_id')
        )

        flash(f'New agreement version created! Customers will need to sign the updated agreement.', 'success')
        return redirect(url_for('admin.agreement_detail', agreement_id=new_agreement_id))

    projects = get_all_projects()
    return render_template('admin/agreement_form.html',
                         projects=projects,
                         agreement=agreement,
                         has_signatures=len(signatures) > 0)


@admin_bp.route('/agreements/templates')
@admin_required
def agreement_templates():
    """View available agreement templates"""
    template_types = [
        ('custom_website', 'Custom Website Development'),
        ('ongoing_maintenance', 'Ongoing Website Maintenance'),
        ('consultation', 'Consultation Services'),
        ('generic', 'Generic Service Agreement')
    ]

    templates = []
    for type_key, type_name in template_types:
        templates.append({
            'type': type_key,
            'name': type_name,
            'content': get_agreement_template(type_key)
        })

    return render_template('admin/agreement_templates.html', templates=templates)


@admin_bp.route('/projects/<int:project_id>/create-agreement', methods=['GET', 'POST'])
@admin_required
def create_agreement_for_project(project_id):
    """Create agreement for a specific project"""
    project = get_project_by_id(project_id)
    if not project:
        flash('Project not found.', 'error')
        return redirect(url_for('admin.projects'))

    customer = get_customer_by_id(project['customer_id'])

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        agreement_type = request.form.get('agreement_type')
        content = request.form.get('content', '').strip()
        auto_replace = request.form.get('auto_replace') == '1'

        if not all([title, agreement_type, content]):
            flash('All fields are required.', 'error')
            template_content = get_agreement_template(project['project_type'])
            return render_template('admin/agreement_form_project.html',
                                 project=project,
                                 customer=customer,
                                 template_content=template_content)

        # Auto-replace placeholders if requested
        if auto_replace:
            content = replace_agreement_placeholders(
                content,
                customer_name=customer['name'],
                project_name=project['project_name'],
                amount=project['total_amount']
            )

        agreement_id = create_agreement(
            project_id=project_id,
            title=title,
            content=content,
            agreement_type=agreement_type,
            created_by_admin_id=session.get('user_id')
        )

        flash(f'Agreement created successfully!', 'success')
        return redirect(url_for('admin.project_detail', project_id=project_id))

    # Get template based on project type
    template_content = get_agreement_template(project['project_type'])

    return render_template('admin/agreement_form_project.html',
                         project=project,
                         customer=customer,
                         template_content=template_content)


# Impersonate Customer Routes

@admin_bp.route('/impersonate/<int:customer_id>', methods=['POST'])
@admin_required
def impersonate_customer(customer_id):
    """Log in as a customer to see their dashboard"""
    customer = get_customer_by_id(customer_id)
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('admin.customers'))

    if not customer['is_active']:
        flash('Cannot impersonate an inactive customer.', 'error')
        return redirect(url_for('admin.customer_detail', customer_id=customer_id))

    # Set customer session keys (admin keys remain intact)
    session['customer_id'] = customer['id']
    session['customer_email'] = customer['email']
    session['customer_name'] = customer['name']
    session['impersonating_customer_id'] = customer['id']
    session['last_activity'] = datetime.now().isoformat()

    flash(f'Now viewing portal as {customer["name"]}.', 'info')
    return redirect(url_for('customers.dashboard'))


@admin_bp.route('/stop-impersonate')
def stop_impersonate():
    """Stop impersonating a customer and return to admin"""
    customer_id = session.pop('impersonating_customer_id', None)
    session.pop('customer_id', None)
    session.pop('customer_email', None)
    session.pop('customer_name', None)

    if customer_id:
        return redirect(url_for('admin.customer_detail', customer_id=customer_id))
    return redirect(url_for('admin.dashboard'))
