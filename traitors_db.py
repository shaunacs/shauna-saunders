"""Database models and functions for Traitors fantasy draft game"""

import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

import os as _os
BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
DB_PATH = _os.path.join(BASE_DIR, 'traitors.db')
CAST_PHOTOS_DIR = _os.path.join(BASE_DIR, 'static', 'img', 'traitors_cast_photos')

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with tables and default settings"""
    conn = get_db()
    cursor = conn.cursor()

    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create cast_members table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cast_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            bio TEXT,
            image_filename TEXT,
            is_traitor BOOLEAN DEFAULT 0,
            is_eliminated BOOLEAN DEFAULT 0,
            elimination_episode INTEGER,
            placement INTEGER
        )
    ''')

    # Create draft_picks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS draft_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            cast_member_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (cast_member_id) REFERENCES cast_members(id),
            UNIQUE(user_id, cast_member_id)
        )
    ''')

    # Create weekly_predictions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS weekly_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            episode_number INTEGER NOT NULL,
            predicted_banished_id INTEGER NOT NULL,
            is_locked BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (predicted_banished_id) REFERENCES cast_members(id),
            UNIQUE(user_id, episode_number)
        )
    ''')

    # Create episode_events table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS episode_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_number INTEGER NOT NULL,
            cast_member_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            points INTEGER NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cast_member_id) REFERENCES cast_members(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # Create game_settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_name TEXT UNIQUE NOT NULL,
            setting_value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Initialize default game settings
    default_settings = [
        ('draft_locked', 'false'),
        ('game_started', 'false'),
        ('current_episode', '0'),
        ('predictions_locked', 'false')
    ]

    for setting_name, setting_value in default_settings:
        cursor.execute('''
            INSERT OR IGNORE INTO game_settings (setting_name, setting_value)
            VALUES (?, ?)
        ''', (setting_name, setting_value))

    conn.commit()
    conn.close()

    # Create cast photos directory
    os.makedirs(CAST_PHOTOS_DIR, exist_ok=True)

def get_setting(setting_name, default=None):
    """Retrieve setting value"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT setting_value FROM game_settings WHERE setting_name = ?', (setting_name,))
    row = cursor.fetchone()
    conn.close()
    return row['setting_value'] if row else default

def set_setting(setting_name, value):
    """Update or create setting"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO game_settings (setting_name, setting_value, updated_at)
        VALUES (?, ?, ?)
    ''', (setting_name, str(value), datetime.now()))
    conn.commit()
    conn.close()

def is_draft_locked():
    """Returns boolean"""
    return get_setting('draft_locked', 'false').lower() == 'true'

def is_game_started():
    """Returns boolean"""
    return get_setting('game_started', 'false').lower() == 'true'

def get_current_episode():
    """Returns integer"""
    return int(get_setting('current_episode', '0'))

def are_predictions_locked():
    """Returns boolean"""
    return get_setting('predictions_locked', 'false').lower() == 'true'

def create_user(username, password, is_admin=False):
    """Create a new user"""
    conn = get_db()
    cursor = conn.cursor()
    password_hash = generate_password_hash(password, method='pbkdf2:sha256')
    try:
        cursor.execute('''
            INSERT INTO users (username, password_hash, is_admin)
            VALUES (?, ?, ?)
        ''', (username, password_hash, 1 if is_admin else 0))
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

def verify_user(username, password):
    """Verify user credentials"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    conn.close()

    if user and check_password_hash(user['password_hash'], password):
        return dict(user)
    return None

def get_user_by_id(user_id):
    """Get user by ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def get_all_users():
    """Get all users"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users ORDER BY username')
    users = cursor.fetchall()
    conn.close()
    return [dict(user) for user in users]

def get_user_score(user_id):
    """Calculate total score for a user"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COALESCE(SUM(points), 0) as total_score
        FROM episode_events
        WHERE user_id = ?
    ''', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result['total_score']

def get_leaderboard():
    """Get leaderboard with all users and their scores"""
    users = get_all_users()
    leaderboard = []

    for user in users:
        score = get_user_score(user['id'])
        user['total_score'] = score
        leaderboard.append(user)

    leaderboard.sort(key=lambda x: x['total_score'], reverse=True)

    # Add rank
    for i, user in enumerate(leaderboard, 1):
        user['rank'] = i

    return leaderboard

def get_user_drafts(user_id):
    """Get all draft picks for a user with cast member details"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT cm.*, dp.id as draft_pick_id, dp.created_at as drafted_at
        FROM draft_picks dp
        JOIN cast_members cm ON dp.cast_member_id = cm.id
        WHERE dp.user_id = ?
        ORDER BY dp.created_at
    ''', (user_id,))
    picks = cursor.fetchall()
    conn.close()
    return [dict(pick) for pick in picks]

def get_draft_pick_count(user_id):
    """Get number of draft picks for a user"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as count FROM draft_picks WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result['count']

def add_draft_pick(user_id, cast_member_id):
    """Add a draft pick"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO draft_picks (user_id, cast_member_id)
            VALUES (?, ?)
        ''', (user_id, cast_member_id))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def remove_draft_pick(user_id, cast_member_id):
    """Remove a draft pick"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        DELETE FROM draft_picks
        WHERE user_id = ? AND cast_member_id = ?
    ''', (user_id, cast_member_id))
    conn.commit()
    conn.close()

def swap_draft_pick(user_id, old_cast_member_id, new_cast_member_id):
    """Swap a draft pick and record penalty if draft is locked"""
    conn = get_db()
    cursor = conn.cursor()

    try:
        # Remove old pick
        cursor.execute('''
            DELETE FROM draft_picks
            WHERE user_id = ? AND cast_member_id = ?
        ''', (user_id, old_cast_member_id))

        # Add new pick
        cursor.execute('''
            INSERT INTO draft_picks (user_id, cast_member_id)
            VALUES (?, ?)
        ''', (user_id, new_cast_member_id))

        # If draft is locked, add penalty
        if is_draft_locked():
            # Get cast member names for notes
            cursor.execute('SELECT name FROM cast_members WHERE id = ?', (old_cast_member_id,))
            old_name = cursor.fetchone()['name']
            cursor.execute('SELECT name FROM cast_members WHERE id = ?', (new_cast_member_id,))
            new_name = cursor.fetchone()['name']

            cursor.execute('''
                INSERT INTO episode_events
                (episode_number, cast_member_id, user_id, event_type, points, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (get_current_episode(), new_cast_member_id, user_id, 'draft_swap_penalty', -20,
                  f'Swapped {old_name} for {new_name}'))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.close()
        return False

def get_all_cast_members():
    """Get all cast members"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM cast_members ORDER BY name')
    members = cursor.fetchall()
    conn.close()
    return [dict(member) for member in members]

def get_cast_member_by_id(cast_id):
    """Get cast member by ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM cast_members WHERE id = ?', (cast_id,))
    member = cursor.fetchone()
    conn.close()
    return dict(member) if member else None

def add_cast_member(name, bio=None, image_filename=None):
    """Add a new cast member"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO cast_members (name, bio, image_filename)
        VALUES (?, ?, ?)
    ''', (name, bio, image_filename))
    conn.commit()
    member_id = cursor.lastrowid
    conn.close()
    return member_id

def update_cast_member(cast_id, **kwargs):
    """Update cast member fields"""
    conn = get_db()
    cursor = conn.cursor()

    fields = []
    values = []

    for key, value in kwargs.items():
        if key in ['name', 'bio', 'image_filename', 'is_traitor', 'is_eliminated', 'elimination_episode', 'placement']:
            fields.append(f'{key} = ?')
            values.append(value)

    if fields:
        values.append(cast_id)
        query = f'UPDATE cast_members SET {", ".join(fields)} WHERE id = ?'
        cursor.execute(query, values)
        conn.commit()

    conn.close()

def get_user_points_breakdown(user_id):
    """Get points breakdown by cast member for a user"""
    conn = get_db()
    cursor = conn.cursor()

    # Get all draft picks with points
    cursor.execute('''
        SELECT
            cm.id,
            cm.name,
            cm.image_filename,
            cm.is_eliminated,
            cm.is_traitor,
            COALESCE(SUM(ee.points), 0) as total_points
        FROM draft_picks dp
        JOIN cast_members cm ON dp.cast_member_id = cm.id
        LEFT JOIN episode_events ee ON ee.cast_member_id = cm.id AND ee.user_id = dp.user_id
        WHERE dp.user_id = ? AND ee.event_type != 'draft_swap_penalty'
        GROUP BY cm.id, cm.name, cm.image_filename, cm.is_eliminated, cm.is_traitor
    ''', (user_id,))
    picks = cursor.fetchall()

    # Get swap penalties
    cursor.execute('''
        SELECT COALESCE(SUM(points), 0) as swap_penalties
        FROM episode_events
        WHERE user_id = ? AND event_type = 'draft_swap_penalty'
    ''', (user_id,))
    swap_result = cursor.fetchone()

    conn.close()

    return {
        'picks': [dict(pick) for pick in picks],
        'swap_penalties': swap_result['swap_penalties']
    }

def record_episode_event(episode_number, cast_member_id, event_type, points, notes=None):
    """Record an episode event and award points to users who drafted that cast member"""
    conn = get_db()
    cursor = conn.cursor()

    # Find all users who drafted this cast member
    cursor.execute('''
        SELECT user_id FROM draft_picks WHERE cast_member_id = ?
    ''', (cast_member_id,))
    users = cursor.fetchall()

    # Record event for each user
    for user in users:
        cursor.execute('''
            INSERT INTO episode_events
            (episode_number, cast_member_id, user_id, event_type, points, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (episode_number, cast_member_id, user['user_id'], event_type, points, notes))

    conn.commit()
    conn.close()

def get_recent_events(limit=10):
    """Get recent episode events"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT ee.*, cm.name as cast_member_name, u.username
        FROM episode_events ee
        JOIN cast_members cm ON ee.cast_member_id = cm.id
        JOIN users u ON ee.user_id = u.id
        ORDER BY ee.created_at DESC
        LIMIT ?
    ''', (limit,))
    events = cursor.fetchall()
    conn.close()
    return [dict(event) for event in events]

def seed_cast_members():
    """Seed initial cast members"""
    cast_data = [
        ("Candiace Dillard Bassett", "Star of The Real Housewives of Potomac, known for her outspoken personality and musical talents."),
        ("Caroline Stanbury", "Reality star from The Real Housewives of Dubai and Ladies of London, bringing British sophistication to the castle."),
        ("Colton Underwood", "Former Bachelor lead who came out as gay in 2021, featured in Netflix's 'Coming Out Colton'."),
        ("Donna Kelce", "Mother of NFL stars Travis and Jason Kelce, fan favorite and Hallmark movie actress."),
        ("Dorinda Medley", "The Real Housewives of New York City alum returning for redemption after early elimination in Season 3."),
        ("Eric Nam", "K-pop artist, TV personality, and singer-songwriter with international appeal."),
        ("Ian Terry", "Big Brother 14 winner (2012) who returned for All-Stars in 2020."),
        ("Johnny Weir", "Two-time Olympic figure skater and beloved sports commentator with flair and style."),
        ("Kristen Kish", "Top Chef Season 10 winner and current host of Top Chef."),
        ("Lisa Rinna", "Iconic Real Housewives of Beverly Hills star known for memorable one-liners and dramatic moments."),
        ("Mark Ballas", "Dancing with the Stars professional dancer and two-time champion."),
        ("Maura Higgins", "Love Island UK finalist and social media presenter for Love Island USA."),
        ("Michael Rapaport", "Actor, comedian, and podcaster known for his bold personality and New York attitude."),
        ("Monét X Change", "RuPaul's Drag Race All Stars Season 4 winner, bringing charisma and wit."),
        ("Natalie Anderson", "Survivor: San Juan del Sur winner (2014) and runner-up on Winners at War (2019)."),
        ("Porsha Williams", "The Real Housewives of Atlanta star from 2012-2021, reality TV veteran."),
        ("Rob Cesternino", "Survivor legend finishing 3rd on The Amazon, hosts 'Rob Has a Podcast'."),
        ("Rob Rausch", "Love Island USA Season 6 villain known for his controversial gameplay and drama."),
        ("Ron Funches", "Actor and comedian featured in Adventure Time, BoJack Horseman, and Loot."),
        ("Stephen Colletti", "Heartthrob from Laguna Beach and One Tree Hill, bringing reality TV roots."),
        ("Tara Lipinski", "1998 Olympic figure skating champion and current sports commentator."),
        ("Tiffany Mitchell", "Big Brother contestant bringing strategic gameplay to the castle."),
        ("Yamil 'Yam Yam' Arocho", "Survivor Season 44 winner (2023), fan favorite for charm and strategic play."),
    ]

    conn = get_db()
    cursor = conn.cursor()

    for name, bio in cast_data:
        cursor.execute('''
            INSERT OR IGNORE INTO cast_members (name, bio)
            VALUES (?, ?)
        ''', (name, bio))

    conn.commit()
    conn.close()
