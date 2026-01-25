"""Initialize customers database for customer management system"""

from customers_db import init_db, create_customer

def main():
    """Initialize the customers database"""
    print("Initializing customers.db database...")

    # Create all tables
    init_db()
    print("✓ Database tables created successfully!")

    # Optionally create a test customer
    create_test = input("\nWould you like to create a test customer? (y/n): ").lower().strip()

    if create_test == 'y':
        print("\n--- Create Test Customer ---")
        email = input("Email: ").strip()
        name = input("Name: ").strip()
        password = input("Password: ").strip()
        company = input("Company (optional): ").strip() or None
        phone = input("Phone (optional): ").strip() or None

        customer_id = create_customer(
            email=email,
            name=name,
            password=password,
            company=company,
            phone=phone
        )

        if customer_id:
            print(f"\n✓ Test customer created successfully! (ID: {customer_id})")
            print(f"  Email: {email}")
            print(f"  Name: {name}")
        else:
            print("\n✗ Failed to create customer. Email may already exist.")

    print("\nDatabase initialization complete!")
    print("\nNext steps:")
    print("1. Update .env with your Stripe API keys")
    print("2. Start the Flask app: python server.py")
    print("3. Customer login: http://localhost:5000/customers/login")
    print("4. Admin area: http://localhost:5000/admin (requires Traitors admin login)")


if __name__ == '__main__':
    main()
