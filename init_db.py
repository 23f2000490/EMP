from werkzeug.security import generate_password_hash
from app import app
from models import db, User

with app.app_context():
    db.create_all()

    if not User.query.filter_by(role="Admin").first():
        admin = User(
            email="admin@emp.com",
            password_hash=generate_password_hash("Admin@123"),
            full_name="System Admin",
            role="Admin",
        )
        db.session.add(admin)
        db.session.commit()
        print("Admin created: admin@emp.com / Admin@123")
    else:
        print("Admin already exists")

    print("Database ready.")