"""Database models and functions for customer management system"""

import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'customers.db')

def get_db():
    """Get database connection to customers.db"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with tables"""
    conn = get_db()
    cursor = conn.cursor()

    # Create customers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            company TEXT,
            phone TEXT,
            password_hash TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_by_admin_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create projects table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            project_name TEXT NOT NULL,
            project_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            total_amount REAL NOT NULL,
            amount_paid REAL DEFAULT 0,
            payment_plan TEXT,
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            description TEXT,
            notes TEXT,
            is_subscription BOOLEAN DEFAULT 0,
            stripe_price_id TEXT,
            stripe_subscription_id TEXT,
            subscription_status TEXT DEFAULT 'inactive',
            next_payment_date TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
        )
    ''')

    # Create project_milestones table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS project_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            milestone_name TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            due_date TIMESTAMP,
            completed_at TIMESTAMP,
            order_index INTEGER DEFAULT 0,
            is_payment_milestone BOOLEAN DEFAULT 0,
            payment_amount REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    ''')

    # Create payments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            project_id INTEGER,
            milestone_id INTEGER,
            stripe_payment_intent_id TEXT UNIQUE,
            stripe_checkout_session_id TEXT,
            stripe_subscription_id TEXT,
            amount REAL NOT NULL,
            payment_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            payment_method TEXT,
            description TEXT,
            metadata TEXT,
            paid_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (milestone_id) REFERENCES project_milestones(id)
        )
    ''')

    # Create stripe_payment_links table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stripe_payment_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            project_id INTEGER,
            amount REAL NOT NULL,
            stripe_checkout_url TEXT NOT NULL,
            stripe_session_id TEXT UNIQUE NOT NULL,
            description TEXT,
            expires_at TIMESTAMP,
            used BOOLEAN DEFAULT 0,
            created_by_admin_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
    ''')

    # Create contact_submissions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contact_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            interest TEXT,
            timeline TEXT,
            budget TEXT,
            project_description TEXT,
            client_ip TEXT,
            converted_to_customer_id INTEGER,
            status TEXT DEFAULT 'new',
            notes TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (converted_to_customer_id) REFERENCES customers(id)
        )
    ''')

    # Create feature_requests table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feature_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT DEFAULT 'medium',
            requested_completion TEXT,
            additional_info TEXT,
            status TEXT DEFAULT 'request_received',
            admin_notes TEXT,
            estimated_hours REAL,
            actual_hours REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    ''')

    # Create task_status_history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS task_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature_request_id INTEGER NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            status_message TEXT,
            admin_notes TEXT,
            updated_by_admin_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (feature_request_id) REFERENCES feature_requests(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()


# Customer Management Functions

def create_customer(email, name, password, company=None, phone=None, created_by_admin_id=None):
    """Create a new customer account"""
    conn = get_db()
    cursor = conn.cursor()

    password_hash = generate_password_hash(password, method='pbkdf2:sha256')
    email = email.lower().strip()

    try:
        cursor.execute('''
            INSERT INTO customers (email, name, company, phone, password_hash, created_by_admin_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (email, name, company, phone, password_hash, created_by_admin_id))
        conn.commit()
        customer_id = cursor.lastrowid
        conn.close()
        return customer_id
    except sqlite3.IntegrityError:
        conn.close()
        return None  # Email already exists


def verify_customer(email, password):
    """Verify customer login credentials"""
    conn = get_db()
    cursor = conn.cursor()

    email = email.lower().strip()
    cursor.execute('SELECT * FROM customers WHERE email = ?', (email,))
    customer = cursor.fetchone()
    conn.close()

    if customer and check_password_hash(customer['password_hash'], password):
        return dict(customer)
    return None


def get_customer_by_id(customer_id):
    """Get customer by ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM customers WHERE id = ?', (customer_id,))
    customer = cursor.fetchone()
    conn.close()
    return dict(customer) if customer else None


def get_customer_by_email(email):
    """Get customer by email"""
    conn = get_db()
    cursor = conn.cursor()
    email = email.lower().strip()
    cursor.execute('SELECT * FROM customers WHERE email = ?', (email,))
    customer = cursor.fetchone()
    conn.close()
    return dict(customer) if customer else None


def get_all_customers(active_only=False):
    """Get all customers"""
    conn = get_db()
    cursor = conn.cursor()

    if active_only:
        cursor.execute('SELECT * FROM customers WHERE is_active = 1 ORDER BY created_at DESC')
    else:
        cursor.execute('SELECT * FROM customers ORDER BY created_at DESC')

    customers = cursor.fetchall()
    conn.close()
    return [dict(customer) for customer in customers]


def update_customer(customer_id, **kwargs):
    """Update customer information"""
    conn = get_db()
    cursor = conn.cursor()

    allowed_fields = ['name', 'email', 'company', 'phone', 'is_active']
    updates = []
    values = []

    for field, value in kwargs.items():
        if field in allowed_fields:
            updates.append(f"{field} = ?")
            if field == 'email':
                value = value.lower().strip()
            values.append(value)

    if updates:
        updates.append("updated_at = ?")
        values.append(datetime.now())
        values.append(customer_id)

        query = f"UPDATE customers SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()

    conn.close()


def deactivate_customer(customer_id):
    """Deactivate a customer account"""
    update_customer(customer_id, is_active=False)


def activate_customer(customer_id):
    """Activate a customer account"""
    update_customer(customer_id, is_active=True)


def delete_customer(customer_id):
    """Delete a customer and all associated data"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM customers WHERE id = ?', (customer_id,))
    conn.commit()
    conn.close()


# Project Management Functions

def create_project(customer_id, project_name, project_type, total_amount, payment_plan=None,
                   description=None, notes=None, is_subscription=False, stripe_price_id=None):
    """Create a new project for a customer"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO projects (customer_id, project_name, project_type, total_amount,
                              payment_plan, description, notes, is_subscription, stripe_price_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (customer_id, project_name, project_type, total_amount, payment_plan, description, notes,
          is_subscription, stripe_price_id))

    conn.commit()
    project_id = cursor.lastrowid
    conn.close()
    return project_id


def get_project_by_id(project_id):
    """Get project by ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
    project = cursor.fetchone()
    conn.close()
    return dict(project) if project else None


def get_projects_by_customer(customer_id):
    """Get all projects for a customer"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM projects WHERE customer_id = ? ORDER BY created_at DESC
    ''', (customer_id,))
    projects = cursor.fetchall()
    conn.close()
    return [dict(project) for project in projects]


def get_all_projects():
    """Get all projects"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.*, c.name as customer_name, c.email as customer_email
        FROM projects p
        JOIN customers c ON p.customer_id = c.id
        ORDER BY p.created_at DESC
    ''')
    projects = cursor.fetchall()
    conn.close()
    return [dict(project) for project in projects]


def update_project(project_id, **kwargs):
    """Update project information"""
    conn = get_db()
    cursor = conn.cursor()

    allowed_fields = ['project_name', 'project_type', 'status', 'total_amount',
                     'payment_plan', 'start_date', 'end_date', 'description', 'notes',
                     'is_subscription', 'stripe_price_id', 'stripe_subscription_id', 'subscription_status', 'next_payment_date']
    updates = []
    values = []

    for field, value in kwargs.items():
        if field in allowed_fields:
            updates.append(f"{field} = ?")
            values.append(value)

    if updates:
        updates.append("updated_at = ?")
        values.append(datetime.now())
        values.append(project_id)

        query = f"UPDATE projects SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()

    conn.close()


def update_project_paid_amount(project_id, amount_to_add):
    """Update the amount paid on a project"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE projects
        SET amount_paid = amount_paid + ?, updated_at = ?
        WHERE id = ?
    ''', (amount_to_add, datetime.now(), project_id))
    conn.commit()
    conn.close()


def delete_project(project_id):
    """Delete a project and all associated data"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
    conn.commit()
    conn.close()


# Milestone Management Functions

def create_milestone(project_id, milestone_name, description=None, due_date=None,
                    is_payment_milestone=False, payment_amount=None, order_index=0):
    """Create a new milestone for a project"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO project_milestones (project_id, milestone_name, description, due_date,
                                        is_payment_milestone, payment_amount, order_index)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (project_id, milestone_name, description, due_date, is_payment_milestone,
          payment_amount, order_index))

    conn.commit()
    milestone_id = cursor.lastrowid
    conn.close()
    return milestone_id


def get_milestone_by_id(milestone_id):
    """Get milestone by ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM project_milestones WHERE id = ?', (milestone_id,))
    milestone = cursor.fetchone()
    conn.close()
    return dict(milestone) if milestone else None


def get_milestones_by_project(project_id):
    """Get all milestones for a project"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM project_milestones
        WHERE project_id = ?
        ORDER BY order_index, created_at
    ''', (project_id,))
    milestones = cursor.fetchall()
    conn.close()
    return [dict(milestone) for milestone in milestones]


def update_milestone(milestone_id, **kwargs):
    """Update milestone information"""
    conn = get_db()
    cursor = conn.cursor()

    allowed_fields = ['milestone_name', 'description', 'status', 'due_date',
                     'is_payment_milestone', 'payment_amount', 'order_index']
    updates = []
    values = []

    for field, value in kwargs.items():
        if field in allowed_fields:
            updates.append(f"{field} = ?")
            values.append(value)

    if updates:
        updates.append("updated_at = ?")
        values.append(datetime.now())
        values.append(milestone_id)

        query = f"UPDATE project_milestones SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()

    conn.close()


def mark_milestone_complete(milestone_id):
    """Mark a milestone as completed"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE project_milestones
        SET status = 'completed', completed_at = ?, updated_at = ?
        WHERE id = ?
    ''', (datetime.now(), datetime.now(), milestone_id))
    conn.commit()
    conn.close()


def delete_milestone(milestone_id):
    """Delete a milestone"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM project_milestones WHERE id = ?', (milestone_id,))
    conn.commit()
    conn.close()


# Payment Management Functions

def create_payment(customer_id, amount, payment_type, project_id=None, milestone_id=None,
                  stripe_payment_intent_id=None, stripe_checkout_session_id=None,
                  stripe_subscription_id=None, status='pending', payment_method=None,
                  description=None, metadata=None):
    """Create a payment record"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO payments (customer_id, project_id, milestone_id, stripe_payment_intent_id,
                             stripe_checkout_session_id, stripe_subscription_id, amount,
                             payment_type, status, payment_method, description, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (customer_id, project_id, milestone_id, stripe_payment_intent_id,
          stripe_checkout_session_id, stripe_subscription_id, amount, payment_type,
          status, payment_method, description, metadata))

    conn.commit()
    payment_id = cursor.lastrowid
    conn.close()
    return payment_id


def get_payment_by_id(payment_id):
    """Get payment by ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM payments WHERE id = ?', (payment_id,))
    payment = cursor.fetchone()
    conn.close()
    return dict(payment) if payment else None


def get_payment_by_intent_id(intent_id):
    """Get payment by Stripe payment intent ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM payments WHERE stripe_payment_intent_id = ?', (intent_id,))
    payment = cursor.fetchone()
    conn.close()
    return dict(payment) if payment else None


def get_payments_by_customer(customer_id):
    """Get all payments for a customer"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM payments WHERE customer_id = ? ORDER BY created_at DESC
    ''', (customer_id,))
    payments = cursor.fetchall()
    conn.close()
    return [dict(payment) for payment in payments]


def get_payments_by_project(project_id):
    """Get all payments for a project"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM payments WHERE project_id = ? ORDER BY created_at DESC
    ''', (project_id,))
    payments = cursor.fetchall()
    conn.close()
    return [dict(payment) for payment in payments]


def update_payment_status(payment_intent_id, status, paid_at=None):
    """Update payment status"""
    conn = get_db()
    cursor = conn.cursor()

    if paid_at:
        cursor.execute('''
            UPDATE payments
            SET status = ?, paid_at = ?, updated_at = ?
            WHERE stripe_payment_intent_id = ?
        ''', (status, paid_at, datetime.now(), payment_intent_id))
    else:
        cursor.execute('''
            UPDATE payments
            SET status = ?, updated_at = ?
            WHERE stripe_payment_intent_id = ?
        ''', (status, datetime.now(), payment_intent_id))

    conn.commit()
    conn.close()


def get_payment_history(customer_id=None, project_id=None, limit=50):
    """Get payment history with optional filters"""
    conn = get_db()
    cursor = conn.cursor()

    query = '''
        SELECT p.*, c.name as customer_name, c.email as customer_email,
               pr.project_name
        FROM payments p
        JOIN customers c ON p.customer_id = c.id
        LEFT JOIN projects pr ON p.project_id = pr.id
        WHERE 1=1
    '''
    params = []

    if customer_id:
        query += ' AND p.customer_id = ?'
        params.append(customer_id)

    if project_id:
        query += ' AND p.project_id = ?'
        params.append(project_id)

    query += ' ORDER BY p.created_at DESC LIMIT ?'
    params.append(limit)

    cursor.execute(query, params)
    payments = cursor.fetchall()
    conn.close()
    return [dict(payment) for payment in payments]


# Payment Link Management Functions

def save_payment_link(customer_id, amount, stripe_checkout_url, stripe_session_id,
                     project_id=None, description=None, expires_at=None, created_by_admin_id=None):
    """Save an admin-generated payment link"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO stripe_payment_links (customer_id, project_id, amount, stripe_checkout_url,
                                          stripe_session_id, description, expires_at,
                                          created_by_admin_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (customer_id, project_id, amount, stripe_checkout_url, stripe_session_id,
          description, expires_at, created_by_admin_id))

    conn.commit()
    link_id = cursor.lastrowid
    conn.close()
    return link_id


def get_payment_link_by_session_id(session_id):
    """Get payment link by Stripe session ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM stripe_payment_links WHERE stripe_session_id = ?', (session_id,))
    link = cursor.fetchone()
    conn.close()
    return dict(link) if link else None


def get_payment_links_by_customer(customer_id, include_used=False):
    """Get payment links for a customer"""
    conn = get_db()
    cursor = conn.cursor()

    if include_used:
        cursor.execute('''
            SELECT * FROM stripe_payment_links
            WHERE customer_id = ?
            ORDER BY created_at DESC
        ''', (customer_id,))
    else:
        cursor.execute('''
            SELECT * FROM stripe_payment_links
            WHERE customer_id = ? AND used = 0
            ORDER BY created_at DESC
        ''', (customer_id,))

    links = cursor.fetchall()
    conn.close()
    return [dict(link) for link in links]


def mark_payment_link_used(session_id):
    """Mark a payment link as used"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE stripe_payment_links SET used = 1 WHERE stripe_session_id = ?
    ''', (session_id,))
    conn.commit()
    conn.close()


# Contact Form Management Functions

def save_contact_submission(name, email, interest, timeline, budget, project_description, client_ip):
    """Save a contact form submission"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO contact_submissions (name, email, interest, timeline, budget,
                                         project_description, client_ip)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (name, email, interest, timeline, budget, project_description, client_ip))

    conn.commit()
    submission_id = cursor.lastrowid
    conn.close()
    return submission_id


def get_contact_submission_by_id(submission_id):
    """Get contact submission by ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM contact_submissions WHERE id = ?', (submission_id,))
    submission = cursor.fetchone()
    conn.close()
    return dict(submission) if submission else None


def get_all_contact_submissions(status=None):
    """Get all contact submissions, optionally filtered by status"""
    conn = get_db()
    cursor = conn.cursor()

    if status:
        cursor.execute('''
            SELECT * FROM contact_submissions WHERE status = ? ORDER BY submitted_at DESC
        ''', (status,))
    else:
        cursor.execute('SELECT * FROM contact_submissions ORDER BY submitted_at DESC')

    submissions = cursor.fetchall()
    conn.close()
    return [dict(submission) for submission in submissions]


def convert_contact_to_customer(submission_id, password):
    """Convert a contact submission to a customer account"""
    submission = get_contact_submission_by_id(submission_id)
    if not submission:
        return None

    # Create customer account
    customer_id = create_customer(
        email=submission['email'],
        name=submission['name'],
        password=password
    )

    if customer_id:
        # Update submission to mark as converted
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE contact_submissions
            SET converted_to_customer_id = ?, status = 'converted'
            WHERE id = ?
        ''', (customer_id, submission_id))
        conn.commit()
        conn.close()

        return customer_id

    return None


def update_contact_submission_status(submission_id, status, notes=None):
    """Update contact submission status"""
    conn = get_db()
    cursor = conn.cursor()

    if notes:
        cursor.execute('''
            UPDATE contact_submissions SET status = ?, notes = ? WHERE id = ?
        ''', (status, notes, submission_id))
    else:
        cursor.execute('''
            UPDATE contact_submissions SET status = ? WHERE id = ?
        ''', (status, submission_id))

    conn.commit()
    conn.close()


# Utility Functions

def get_customer_total_paid(customer_id):
    """Get total amount paid by a customer"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT SUM(amount) as total FROM payments
        WHERE customer_id = ? AND status = 'succeeded'
    ''', (customer_id,))
    result = cursor.fetchone()
    conn.close()
    return result['total'] if result['total'] else 0


def get_outstanding_balance(customer_id):
    """Get outstanding balance for a customer across all projects"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT SUM(total_amount - amount_paid) as balance
        FROM projects
        WHERE customer_id = ? AND status != 'cancelled'
    ''', (customer_id,))
    result = cursor.fetchone()
    conn.close()
    return result['balance'] if result['balance'] else 0


def get_project_completion_percentage(project_id):
    """Get project completion percentage based on milestones"""
    milestones = get_milestones_by_project(project_id)
    if not milestones:
        return 0

    completed = sum(1 for m in milestones if m['status'] == 'completed')
    return int((completed / len(milestones)) * 100)


def get_active_subscription_projects():
    """Get all projects with active subscriptions that need next payment date updates"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, stripe_subscription_id, next_payment_date
        FROM projects 
        WHERE is_subscription = 1 
        AND subscription_status = 'active' 
        AND stripe_subscription_id IS NOT NULL
    ''')
    projects = cursor.fetchall()
    conn.close()
    return [dict(project) for project in projects]


# Feature Request Management Functions

def create_feature_request(customer_id, project_id, title, description, priority='medium', 
                          requested_completion=None, additional_info=None):
    """Create a new feature request"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO feature_requests (customer_id, project_id, title, description, 
                                     priority, requested_completion, additional_info)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (customer_id, project_id, title, description, priority, requested_completion, additional_info))

    conn.commit()
    feature_request_id = cursor.lastrowid
    
    # Create initial status history entry
    cursor.execute('''
        INSERT INTO task_status_history (feature_request_id, new_status, status_message)
        VALUES (?, ?, ?)
    ''', (feature_request_id, 'request_received', 'Feature request submitted by customer'))
    
    conn.commit()
    conn.close()
    return feature_request_id


def get_feature_request_by_id(request_id):
    """Get feature request by ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT fr.*, c.name as customer_name, c.email as customer_email, 
               p.project_name
        FROM feature_requests fr
        JOIN customers c ON fr.customer_id = c.id
        JOIN projects p ON fr.project_id = p.id
        WHERE fr.id = ?
    ''', (request_id,))
    request = cursor.fetchone()
    conn.close()
    return dict(request) if request else None


def get_feature_requests_by_customer(customer_id, project_id=None):
    """Get feature requests for a customer, optionally filtered by project"""
    conn = get_db()
    cursor = conn.cursor()
    
    if project_id:
        cursor.execute('''
            SELECT fr.*, p.project_name
            FROM feature_requests fr
            JOIN projects p ON fr.project_id = p.id
            WHERE fr.customer_id = ? AND fr.project_id = ?
            ORDER BY fr.created_at DESC
        ''', (customer_id, project_id))
    else:
        cursor.execute('''
            SELECT fr.*, p.project_name
            FROM feature_requests fr
            JOIN projects p ON fr.project_id = p.id
            WHERE fr.customer_id = ?
            ORDER BY fr.created_at DESC
        ''', (customer_id,))
    
    requests = cursor.fetchall()
    conn.close()
    return [dict(request) for request in requests]


def get_all_feature_requests(status=None):
    """Get all feature requests, optionally filtered by status"""
    conn = get_db()
    cursor = conn.cursor()
    
    if status:
        cursor.execute('''
            SELECT fr.*, c.name as customer_name, c.email as customer_email, 
                   p.project_name
            FROM feature_requests fr
            JOIN customers c ON fr.customer_id = c.id
            JOIN projects p ON fr.project_id = p.id
            WHERE fr.status = ?
            ORDER BY fr.created_at DESC
        ''', (status,))
    else:
        cursor.execute('''
            SELECT fr.*, c.name as customer_name, c.email as customer_email, 
                   p.project_name
            FROM feature_requests fr
            JOIN customers c ON fr.customer_id = c.id
            JOIN projects p ON fr.project_id = p.id
            ORDER BY fr.created_at DESC
        ''')
    
    requests = cursor.fetchall()
    conn.close()
    return [dict(request) for request in requests]


def update_feature_request_status(request_id, new_status, status_message=None, 
                                 admin_notes=None, admin_id=None):
    """Update feature request status and create history entry"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get current status
    cursor.execute('SELECT status FROM feature_requests WHERE id = ?', (request_id,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        return False
    
    old_status = result['status']
    
    # Update the feature request
    update_fields = ['status = ?', 'updated_at = ?']
    update_values = [new_status, datetime.now()]
    
    if new_status == 'completed':
        update_fields.append('completed_at = ?')
        update_values.append(datetime.now())
    
    if admin_notes:
        update_fields.append('admin_notes = ?')
        update_values.append(admin_notes)
    
    update_values.append(request_id)
    
    cursor.execute(f'''
        UPDATE feature_requests 
        SET {', '.join(update_fields)}
        WHERE id = ?
    ''', update_values)
    
    # Create status history entry
    cursor.execute('''
        INSERT INTO task_status_history (feature_request_id, old_status, new_status, 
                                        status_message, admin_notes, updated_by_admin_id)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (request_id, old_status, new_status, status_message, admin_notes, admin_id))
    
    conn.commit()
    conn.close()
    return True


def get_feature_request_history(request_id):
    """Get status history for a feature request"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM task_status_history 
        WHERE feature_request_id = ? 
        ORDER BY created_at ASC
    ''', (request_id,))
    history = cursor.fetchall()
    conn.close()
    return [dict(h) for h in history]


def update_feature_request(request_id, **kwargs):
    """Update feature request fields"""
    conn = get_db()
    cursor = conn.cursor()

    allowed_fields = ['title', 'description', 'priority', 'requested_completion', 
                     'additional_info', 'admin_notes', 'estimated_hours', 'actual_hours']
    updates = []
    values = []

    for field, value in kwargs.items():
        if field in allowed_fields:
            updates.append(f"{field} = ?")
            values.append(value)

    if updates:
        updates.append("updated_at = ?")
        values.append(datetime.now())
        values.append(request_id)

        query = f"UPDATE feature_requests SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()

    conn.close()
