"""Blueprint for admin interface - customer and project management"""

import os
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
from functools import wraps
import stripe

from customers_db import *

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

        if not all([name, email]):
            flash('Name and email are required.', 'error')
            return render_template('admin/customer_form.html', customer=customer)

        update_customer(customer_id, name=name, email=email, company=company, phone=phone)
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
        is_subscription = request.form.get('is_subscription') == '1'
        stripe_price_id = request.form.get('stripe_price_id', '').strip() or None

        # Validation
        if not all([customer_id, project_name, project_type, total_amount]):
            flash('Customer, project name, type, and amount are required.', 'error')
            customers = get_all_customers(active_only=True)
            return render_template('admin/project_form.html', project=None, customers=customers)

        if is_subscription and not stripe_price_id:
            flash('Stripe Price ID is required for subscription projects.', 'error')
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
            stripe_price_id=stripe_price_id
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

    return render_template('admin/project_detail.html',
                         project=project,
                         customer=customer,
                         milestones=milestones,
                         payments=payments,
                         completion_percentage=completion_percentage)


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
        is_subscription = request.form.get('is_subscription') == '1'
        stripe_price_id = request.form.get('stripe_price_id', '').strip() or None

        if not all([project_name, project_type, total_amount]):
            flash('Project name, type, and amount are required.', 'error')
            customers = get_all_customers(active_only=True)
            return render_template('admin/project_form.html', project=project, customers=customers)

        if is_subscription and not stripe_price_id:
            flash('Stripe Price ID is required for subscription projects.', 'error')
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
            is_subscription=is_subscription,
            stripe_price_id=stripe_price_id
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
            customers = get_all_customers(active_only=True)
            return render_template('admin/payment_link_form.html', customers=customers)

        try:
            amount = float(amount)
        except ValueError:
            flash('Invalid amount.', 'error')
            customers = get_all_customers(active_only=True)
            return render_template('admin/payment_link_form.html', customers=customers)

        customer = get_customer_by_id(int(customer_id))

        # Create Stripe Checkout Session
        try:
            checkout_session = stripe.checkout.Session.create(
                customer_email=customer['email'],
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': description or 'Payment',
                        },
                        'unit_amount': int(amount * 100),
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=url_for('customers.payment_success', _external=True),
                cancel_url=url_for('customers.payment_cancel', _external=True),
                expires_at=int((datetime.now() + timedelta(days=7)).timestamp()),
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
                stripe_checkout_url=checkout_session.url,
                stripe_session_id=checkout_session.id,
                description=description,
                expires_at=datetime.now() + timedelta(days=7),
                created_by_admin_id=session.get('user_id')
            )

            flash(f'Payment link created! URL: {checkout_session.url}', 'success')
            return redirect(url_for('admin.customer_detail', customer_id=customer_id))

        except Exception as e:
            flash(f'Error creating payment link: {str(e)}', 'error')
            customers = get_all_customers(active_only=True)
            return render_template('admin/payment_link_form.html', customers=customers)

    customers = get_all_customers(active_only=True)
    return render_template('admin/payment_link_form.html', customers=customers)


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
