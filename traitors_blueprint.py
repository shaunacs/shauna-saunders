"""Blueprint for Traitors fantasy draft game"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import os
import sqlite3

from traitors_db import *

traitors_bp = Blueprint('traitors', __name__, url_prefix='/traitors')

# Redirect /traitors to dashboard
@traitors_bp.route('/')
def index():
    """Redirect to dashboard or login"""
    if 'user_id' in session:
        return redirect(url_for('traitors.dashboard'))
    return redirect(url_for('traitors.login'))

# File upload configuration
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    """Decorator to require login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('traitors.login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('traitors.login'))

        user = get_user_by_id(session['user_id'])
        if not user or not user['is_admin']:
            flash('Admin access required.', 'error')
            return redirect(url_for('traitors.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# Authentication Routes

@traitors_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if 'user_id' in session:
        return redirect(url_for('traitors.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = verify_user(username, password)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = bool(user['is_admin'])
            flash(f'Welcome back, {user["username"]}!', 'success')
            return redirect(url_for('traitors.dashboard'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template('traitors/login.html')


@traitors_bp.route('/logout')
def logout():
    """Logout and redirect to login"""
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('traitors.login'))


@traitors_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Allow users to change their password"""
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Verify current password
        user = get_user_by_id(session['user_id'])
        if not check_password_hash(user['password_hash'], current_password):
            flash('Current password is incorrect.', 'error')
            return render_template('traitors/change_password.html')

        # Validate new password
        if len(new_password) < 6:
            flash('New password must be at least 6 characters.', 'error')
            return render_template('traitors/change_password.html')

        if new_password != confirm_password:
            flash('New passwords do not match.', 'error')
            return render_template('traitors/change_password.html')

        # Update password
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users SET password_hash = ? WHERE id = ?
        ''', (generate_password_hash(new_password, method='pbkdf2:sha256'), session['user_id']))
        conn.commit()
        conn.close()

        flash('Password changed successfully!', 'success')
        return redirect(url_for('traitors.dashboard'))

    return render_template('traitors/change_password.html')


# User Routes

@traitors_bp.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard"""
    leaderboard = get_leaderboard()
    user_picks = get_user_drafts(session['user_id'])
    user_score = get_user_score(session['user_id'])
    breakdown = get_user_points_breakdown(session['user_id'])
    recent_events = get_recent_events(10)
    draft_locked = is_draft_locked()
    game_started = is_game_started()
    current_episode = get_current_episode()

    return render_template('traitors/dashboard.html',
                           leaderboard=leaderboard,
                           user_picks=user_picks,
                           user_score=user_score,
                           breakdown=breakdown,
                           recent_events=recent_events,
                           draft_locked=draft_locked,
                           game_started=game_started,
                           current_episode=current_episode)


@traitors_bp.route('/draft', methods=['GET', 'POST'])
@login_required
def draft():
    """Draft interface"""
    all_cast = get_all_cast_members()
    user_picks = get_user_drafts(session['user_id'])
    user_pick_ids = [pick['id'] for pick in user_picks]
    draft_locked = is_draft_locked()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            cast_member_id = int(request.form.get('cast_member_id'))

            # Check if already at max picks
            if len(user_picks) >= 5:
                flash('You already have 5 picks. Remove one first.', 'error')
            elif cast_member_id in user_pick_ids:
                flash('You have already drafted this cast member.', 'error')
            else:
                if add_draft_pick(session['user_id'], cast_member_id):
                    flash('Cast member added to your draft!', 'success')
                else:
                    flash('Error adding cast member.', 'error')
            return redirect(url_for('traitors.draft'))

        elif action == 'remove':
            cast_member_id = int(request.form.get('cast_member_id'))
            remove_draft_pick(session['user_id'], cast_member_id)
            flash('Cast member removed from your draft.', 'success')
            return redirect(url_for('traitors.draft'))

        elif action == 'swap':
            old_cast_member_id = int(request.form.get('old_cast_member_id'))
            new_cast_member_id = int(request.form.get('new_cast_member_id'))

            if new_cast_member_id in user_pick_ids:
                flash('You have already drafted this cast member.', 'error')
            else:
                if swap_draft_pick(session['user_id'], old_cast_member_id, new_cast_member_id):
                    if draft_locked:
                        flash('Draft pick swapped! -20 points penalty applied.', 'warning')
                    else:
                        flash('Draft pick swapped!', 'success')
                else:
                    flash('Error swapping draft pick.', 'error')
            return redirect(url_for('traitors.draft'))

    return render_template('traitors/draft.html',
                           cast_members=all_cast,
                           user_picks=user_picks,
                           user_pick_ids=user_pick_ids,
                           draft_locked=draft_locked)


@traitors_bp.route('/cast/<int:cast_id>')
@login_required
def cast_detail(cast_id):
    """Cast member detail page"""
    cast_member = get_cast_member_by_id(cast_id)
    if not cast_member:
        flash('Cast member not found.', 'error')
        return redirect(url_for('traitors.draft'))

    user_picks = get_user_drafts(session['user_id'])
    user_pick_ids = [pick['id'] for pick in user_picks]
    has_drafted = cast_id in user_pick_ids
    can_draft = len(user_picks) < 5 and not has_drafted

    # Get all users who drafted this cast member (only if game started)
    drafted_by = []
    if is_game_started():
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.username, u.id
            FROM users u
            JOIN draft_picks dp ON u.id = dp.user_id
            WHERE dp.cast_member_id = ?
            ORDER BY u.username
        ''', (cast_id,))
        drafted_by = [dict(row) for row in cursor.fetchall()]
        conn.close()

    return render_template('traitors/cast_detail.html',
                           cast_member=cast_member,
                           has_drafted=has_drafted,
                           can_draft=can_draft,
                           drafted_by=drafted_by)


@traitors_bp.route('/predict', methods=['GET', 'POST'])
@login_required
def predict():
    """Weekly prediction page"""
    current_episode = get_current_episode()
    predictions_locked = are_predictions_locked()
    all_cast = get_all_cast_members()
    # Only show cast members who are not eliminated
    available_cast = [c for c in all_cast if not c['is_eliminated']]

    # Get user's prediction for current episode
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM weekly_predictions
        WHERE user_id = ? AND episode_number = ?
    ''', (session['user_id'], current_episode))
    existing_prediction = cursor.fetchone()
    conn.close()

    if request.method == 'POST':
        if predictions_locked:
            flash('Predictions are locked for this episode.', 'error')
            return redirect(url_for('traitors.predict'))

        predicted_banished_id = int(request.form.get('predicted_banished_id'))

        conn = get_db()
        cursor = conn.cursor()
        if existing_prediction:
            # Update existing prediction
            cursor.execute('''
                UPDATE weekly_predictions
                SET predicted_banished_id = ?
                WHERE user_id = ? AND episode_number = ?
            ''', (predicted_banished_id, session['user_id'], current_episode))
        else:
            # Create new prediction
            cursor.execute('''
                INSERT INTO weekly_predictions (user_id, episode_number, predicted_banished_id)
                VALUES (?, ?, ?)
            ''', (session['user_id'], current_episode, predicted_banished_id))

        conn.commit()
        conn.close()

        flash('Prediction saved!', 'success')
        return redirect(url_for('traitors.predict'))

    return render_template('traitors/predict.html',
                           current_episode=current_episode,
                           predictions_locked=predictions_locked,
                           available_cast=available_cast,
                           existing_prediction=dict(existing_prediction) if existing_prediction else None)


@traitors_bp.route('/all-drafts')
@login_required
def all_drafts():
    """View everyone's draft picks"""
    if not is_game_started():
        flash('Drafts will be visible once the game starts.', 'error')
        return redirect(url_for('traitors.dashboard'))

    users = get_all_users()
    all_drafts = []

    for user in users:
        picks = get_user_drafts(user['id'])
        score = get_user_score(user['id'])

        # Get swap count
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as swap_count
            FROM episode_events
            WHERE user_id = ? AND event_type = 'draft_swap_penalty'
        ''', (user['id'],))
        swap_count = cursor.fetchone()['swap_count']
        conn.close()

        all_drafts.append({
            'user': user,
            'picks': picks,
            'score': score,
            'swap_count': swap_count
        })

    # Sort by score
    all_drafts.sort(key=lambda x: x['score'], reverse=True)

    return render_template('traitors/all_drafts.html', all_drafts=all_drafts)


@traitors_bp.route('/predictions')
@login_required
def predictions():
    """View weekly predictions (only after locked)"""
    current_episode = get_current_episode()

    # Get all locked predictions
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT episode_number FROM weekly_predictions
        WHERE episode_number <= ?
        ORDER BY episode_number DESC
    ''', (current_episode,))
    locked_episodes = [row['episode_number'] for row in cursor.fetchall()]

    # Get predictions for each episode
    episode_predictions = {}
    for episode in locked_episodes:
        cursor.execute('''
            SELECT wp.*, u.username, cm.name as cast_member_name, cm.image_filename
            FROM weekly_predictions wp
            JOIN users u ON wp.user_id = u.id
            JOIN cast_members cm ON wp.predicted_banished_id = cm.id
            WHERE wp.episode_number = ?
            ORDER BY u.username
        ''', (episode,))
        episode_predictions[episode] = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return render_template('traitors/predictions.html',
                           episode_predictions=episode_predictions,
                           locked_episodes=locked_episodes)


# Photo serving route
@traitors_bp.route('/photos/<filename>')
def serve_photo(filename):
    """Serve cast member photos"""
    return send_from_directory(CAST_PHOTOS_DIR, filename)


# Admin Routes

@traitors_bp.route('/admin')
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    current_episode = get_current_episode()
    draft_locked = is_draft_locked()
    game_started = is_game_started()
    predictions_locked = are_predictions_locked()

    return render_template('traitors/admin/dashboard.html',
                           current_episode=current_episode,
                           draft_locked=draft_locked,
                           game_started=game_started,
                           predictions_locked=predictions_locked)


@traitors_bp.route('/admin/cast', methods=['GET', 'POST'])
@admin_required
def admin_cast():
    """Manage cast members"""
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            name = request.form.get('name', '').strip()
            bio = request.form.get('bio', '').strip()

            # Handle file upload
            image_filename = None
            if 'photo' in request.files:
                file = request.files['photo']
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Make unique filename
                    import uuid
                    unique_filename = f"{uuid.uuid4()}_{filename}"
                    filepath = os.path.join(CAST_PHOTOS_DIR, unique_filename)
                    file.save(filepath)
                    image_filename = unique_filename

            if name:
                add_cast_member(name, bio if bio else None, image_filename)
                flash(f'Cast member "{name}" added successfully!', 'success')
            else:
                flash('Name is required.', 'error')

        elif action == 'edit':
            cast_id = int(request.form.get('cast_id'))
            name = request.form.get('name', '').strip()
            bio = request.form.get('bio', '').strip()
            is_traitor = request.form.get('is_traitor') == 'on'
            is_eliminated = request.form.get('is_eliminated') == 'on'
            elimination_episode = request.form.get('elimination_episode', '').strip()
            placement = request.form.get('placement', '').strip()

            update_data = {'name': name, 'bio': bio if bio else None}

            # Handle photo upload
            if 'photo' in request.files:
                file = request.files['photo']
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    import uuid
                    unique_filename = f"{uuid.uuid4()}_{filename}"
                    filepath = os.path.join(CAST_PHOTOS_DIR, unique_filename)
                    file.save(filepath)
                    update_data['image_filename'] = unique_filename

            update_data['is_traitor'] = 1 if is_traitor else 0
            update_data['is_eliminated'] = 1 if is_eliminated else 0
            update_data['elimination_episode'] = int(elimination_episode) if elimination_episode else None
            update_data['placement'] = int(placement) if placement else None

            update_cast_member(cast_id, **update_data)
            flash('Cast member updated!', 'success')

        elif action == 'delete':
            cast_id = int(request.form.get('cast_id'))
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM cast_members WHERE id = ?', (cast_id,))
            conn.commit()
            conn.close()
            flash('Cast member deleted.', 'success')

        return redirect(url_for('traitors.admin_cast'))

    all_cast = get_all_cast_members()
    return render_template('traitors/admin/cast.html', cast_members=all_cast)


@traitors_bp.route('/admin/users', methods=['GET', 'POST'])
@admin_required
def admin_users():
    """Manage users"""
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', 'traitors123')

            if username:
                user_id = create_user(username, password, is_admin=False)
                if user_id:
                    flash(f'User "{username}" created with password "traitors123"', 'success')
                else:
                    flash('Username already exists.', 'error')
            else:
                flash('Username is required.', 'error')

        elif action == 'toggle_admin':
            user_id = int(request.form.get('user_id'))
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET is_admin = NOT is_admin WHERE id = ?', (user_id,))
            conn.commit()
            conn.close()
            flash('Admin status toggled.', 'success')

        elif action == 'delete':
            user_id = int(request.form.get('user_id'))
            if user_id == session['user_id']:
                flash('Cannot delete your own account.', 'error')
            else:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
                conn.commit()
                conn.close()
                flash('User deleted.', 'success')

        return redirect(url_for('traitors.admin_users'))

    users = get_all_users()
    # Add scores to users
    for user in users:
        user['total_score'] = get_user_score(user['id'])

    return render_template('traitors/admin/users.html', users=users)


@traitors_bp.route('/admin/episode', methods=['GET', 'POST'])
@admin_required
def admin_episode():
    """Record episode events"""
    current_episode = get_current_episode()
    all_cast = get_all_cast_members()
    alive_cast = [c for c in all_cast if not c['is_eliminated']]

    if request.method == 'POST':
        episode_number = int(request.form.get('episode_number', current_episode))

        # Process each event type
        events_to_record = []

        # Murdered
        murdered_ids = request.form.getlist('murdered')
        for cast_id in murdered_ids:
            events_to_record.append((int(cast_id), 'murdered', -10, 'Murdered'))

        # Banished
        banished_ids = request.form.getlist('banished')
        for cast_id in banished_ids:
            events_to_record.append((int(cast_id), 'banished', -15, 'Banished at round table'))

        # Shield found
        shield_ids = request.form.getlist('shield_found')
        for cast_id in shield_ids:
            events_to_record.append((int(cast_id), 'shield_found', 8, 'Found a shield'))

        # Traitor revealed
        traitor_revealed_ids = request.form.getlist('traitor_revealed')
        for cast_id in traitor_revealed_ids:
            events_to_record.append((int(cast_id), 'traitor_revealed', 15, 'Revealed as traitor (Episode 1)'))

        # Traitor recruited
        traitor_recruited_ids = request.form.getlist('traitor_recruited')
        for cast_id in traitor_recruited_ids:
            events_to_record.append((int(cast_id), 'traitor_recruited', 20, 'Recruited as traitor'))

        # Faithful correct vote
        faithful_correct_ids = request.form.getlist('faithful_correct_vote')
        for cast_id in faithful_correct_ids:
            events_to_record.append((int(cast_id), 'faithful_correct_vote', 5, 'Voted correctly for a traitor'))

        # Traitor survived round table
        traitor_survived_ids = request.form.getlist('traitor_survived_roundtable')
        for cast_id in traitor_survived_ids:
            events_to_record.append((int(cast_id), 'traitor_survived_roundtable', 10, 'Survived round table as traitor'))

        # Faithful survived round table
        faithful_survived_ids = request.form.getlist('faithful_survived_roundtable')
        for cast_id in faithful_survived_ids:
            events_to_record.append((int(cast_id), 'faithful_survived_roundtable', 5, 'Survived round table as faithful'))

        # Won season
        winner_ids = request.form.getlist('won_season')
        for cast_id in winner_ids:
            events_to_record.append((int(cast_id), 'won_season', 20, 'Won the season!'))

        # Record all events
        for cast_id, event_type, points, notes in events_to_record:
            record_episode_event(episode_number, cast_id, event_type, points, notes)

        flash(f'Episode {episode_number} events recorded!', 'success')
        return redirect(url_for('traitors.admin_episode'))

    return render_template('traitors/admin/episode.html',
                           current_episode=current_episode,
                           cast_members=all_cast,
                           alive_cast=alive_cast)


@traitors_bp.route('/admin/predictions', methods=['GET', 'POST'])
@admin_required
def admin_predictions():
    """Manage predictions"""
    current_episode = get_current_episode()
    predictions_locked = are_predictions_locked()

    # Get all predictions for current episode
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT wp.*, u.username, cm.name as cast_member_name, cm.image_filename
        FROM weekly_predictions wp
        JOIN users u ON wp.user_id = u.id
        JOIN cast_members cm ON wp.predicted_banished_id = cm.id
        WHERE wp.episode_number = ?
        ORDER BY u.username
    ''', (current_episode,))
    current_predictions = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'lock':
            set_setting('predictions_locked', 'true')
            flash('Predictions locked!', 'success')
        elif action == 'unlock':
            set_setting('predictions_locked', 'false')
            flash('Predictions unlocked!', 'success')

        return redirect(url_for('traitors.admin_predictions'))

    return render_template('traitors/admin/predictions.html',
                           current_episode=current_episode,
                           predictions_locked=predictions_locked,
                           current_predictions=current_predictions)


@traitors_bp.route('/admin/game-settings', methods=['GET', 'POST'])
@admin_required
def admin_game_settings():
    """Game settings"""
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'toggle_draft_lock':
            current = is_draft_locked()
            set_setting('draft_locked', 'false' if current else 'true')
            flash(f'Draft {"unlocked" if current else "locked"}!', 'success')

        elif action == 'toggle_game_started':
            current = is_game_started()
            set_setting('game_started', 'false' if current else 'true')
            flash(f'Game {"stopped" if current else "started"}!', 'success')

        elif action == 'set_episode':
            episode = int(request.form.get('episode_number', 0))
            set_setting('current_episode', episode)
            flash(f'Current episode set to {episode}!', 'success')

        elif action == 'toggle_predictions_lock':
            current = are_predictions_locked()
            set_setting('predictions_locked', 'false' if current else 'true')
            flash(f'Predictions {"unlocked" if current else "locked"}!', 'success')

        elif action == 'reset_game':
            confirm = request.form.get('confirm_reset')
            if confirm == 'RESET':
                # Delete database and reinitialize
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute('DROP TABLE IF EXISTS episode_events')
                cursor.execute('DROP TABLE IF EXISTS weekly_predictions')
                cursor.execute('DROP TABLE IF EXISTS draft_picks')
                cursor.execute('DROP TABLE IF EXISTS cast_members')
                cursor.execute('DROP TABLE IF EXISTS users')
                cursor.execute('DROP TABLE IF EXISTS game_settings')
                conn.commit()
                conn.close()

                init_db()
                seed_cast_members()

                # Log out current user
                session.clear()
                flash('Game reset! Please create a new admin account.', 'success')
                return redirect(url_for('traitors.login'))
            else:
                flash('Reset confirmation failed. Type "RESET" exactly.', 'error')

        return redirect(url_for('traitors.admin_game_settings'))

    draft_locked = is_draft_locked()
    game_started = is_game_started()
    current_episode = get_current_episode()
    predictions_locked = are_predictions_locked()

    return render_template('traitors/admin/game_settings.html',
                           draft_locked=draft_locked,
                           game_started=game_started,
                           current_episode=current_episode,
                           predictions_locked=predictions_locked)


@traitors_bp.route('/admin/audit')
@admin_required
def admin_audit():
    """Audit log"""
    # Get filter parameters
    user_filter = request.args.get('user_id', type=int)
    episode_filter = request.args.get('episode', type=int)
    event_type_filter = request.args.get('event_type')

    conn = get_db()
    cursor = conn.cursor()

    query = '''
        SELECT ee.*, cm.name as cast_member_name, u.username
        FROM episode_events ee
        JOIN cast_members cm ON ee.cast_member_id = cm.id
        JOIN users u ON ee.user_id = u.id
        WHERE 1=1
    '''
    params = []

    if user_filter:
        query += ' AND ee.user_id = ?'
        params.append(user_filter)

    if episode_filter:
        query += ' AND ee.episode_number = ?'
        params.append(episode_filter)

    if event_type_filter:
        query += ' AND ee.event_type = ?'
        params.append(event_type_filter)

    query += ' ORDER BY ee.created_at DESC LIMIT 100'

    cursor.execute(query, params)
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()

    users = get_all_users()
    event_types = ['murdered', 'banished', 'shield_found', 'traitor_revealed', 'traitor_recruited',
                   'faithful_correct_vote', 'traitor_survived_roundtable', 'faithful_survived_roundtable',
                   'won_season', 'draft_swap_penalty']

    return render_template('traitors/admin/audit.html',
                           events=events,
                           users=users,
                           event_types=event_types,
                           user_filter=user_filter,
                           episode_filter=episode_filter,
                           event_type_filter=event_type_filter)
