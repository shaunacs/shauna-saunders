#!/usr/bin/env python3
"""Initialize the Traitors Fantasy Draft database"""

import os
from traitors_db import init_db, seed_cast_members, create_user

def main():
    print("=" * 50)
    print("Traitors Fantasy Draft - Database Initialization")
    print("=" * 50)
    print()

    # Initialize database
    print("Creating database tables...")
    init_db()
    print("✓ Database tables created successfully!")
    print()

    # Seed cast members
    print("Seeding cast members (The Traitors US Season 4)...")
    seed_cast_members()
    print("✓ 23 cast members added!")
    print()

    # Create admin user
    print("Creating admin account...")
    admin_username = input("Enter admin username (default: admin): ").strip() or "admin"
    admin_password = input("Enter admin password (default: admin123): ").strip() or "admin123"

    user_id = create_user(admin_username, admin_password, is_admin=True)
    if user_id:
        print(f"✓ Admin account created!")
        print(f"  Username: {admin_username}")
        print(f"  Password: {admin_password}")
        print()
    else:
        print("✗ Admin account already exists or error occurred.")
        print()

    # Create additional test users
    create_test = input("Create test users? (y/n): ").strip().lower()
    if create_test == 'y':
        test_users = [
            ("player1", "traitors123"),
            ("player2", "traitors123"),
            ("player3", "traitors123"),
        ]

        print("Creating test users...")
        for username, password in test_users:
            user_id = create_user(username, password, is_admin=False)
            if user_id:
                print(f"  ✓ Created: {username} (password: {password})")
            else:
                print(f"  ✗ User {username} already exists")
        print()

    print("=" * 50)
    print("Initialization complete!")
    print("=" * 50)
    print()
    print("Next steps:")
    print("1. Run the Flask server: python server.py")
    print("2. Visit http://localhost:5000/traitors/login")
    print("3. Login with your admin credentials")
    print("4. Configure game settings in the admin panel")
    print()
    import os
    base_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Database location: {os.path.join(base_dir, 'traitors.db')}")
    print(f"Cast photos directory: {os.path.join(base_dir, 'static', 'img', 'traitors_cast_photos')}")
    print()

if __name__ == "__main__":
    main()
