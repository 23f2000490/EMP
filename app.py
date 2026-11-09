from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, ExaminerProfile

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-later"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///emp.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

DASHBOARDS = {
    "Admin": "admin_dashboard",
    "Examiner": "examiner_dashboard",
    "Student": "student_dashboard",
}


def role_required(role):
    """Allow only logged-in users with the given role."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))
            if session.get("role") != role:
                flash("You are not allowed to access that page.", "danger")
                return redirect(url_for(DASHBOARDS[session["role"]]))
            return f(*args, **kwargs)
        return wrapper
    return decorator


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for(DASHBOARDS[session["role"]]))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        full_name = request.form["full_name"].strip()
        role = request.form["role"]
        phone = request.form.get("phone", "").strip()
        department = request.form.get("department", "").strip()

        # Admin registration is never allowed
        if role not in ("Student", "Examiner"):
            flash("Invalid user type.", "danger")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.", "danger")
            return redirect(url_for("register"))

        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            full_name=full_name,
            role=role,
            phone=phone,
            department=department,
        )
        db.session.add(user)
        db.session.flush()  # gets user.id before commit

        if role == "Examiner":
            db.session.add(ExaminerProfile(
                user_id=user.id,
                contact_details=phone,
                department=department,
                status="Pending",
            ))
            db.session.commit()
            flash("Registered. You can log in after the Admin approves your account.", "info")
        else:
            db.session.commit()
            flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login"))

        if not user.is_active:
            flash("Your account has been deactivated.", "danger")
            return redirect(url_for("login"))

        if user.role == "Examiner":
            status = user.examiner_profile.status if user.examiner_profile else "Pending"
            if status == "Pending":
                flash("Your account is awaiting Admin approval.", "warning")
                return redirect(url_for("login"))
            if status == "Deactivated":
                flash("Your examiner account has been deactivated.", "danger")
                return redirect(url_for("login"))

        session.clear()
        session["user_id"] = user.id
        session["role"] = user.role
        session["name"] = user.full_name
        return redirect(url_for(DASHBOARDS[user.role]))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))


@app.route("/admin/dashboard")
@role_required("Admin")
def admin_dashboard():
    return render_template("admin_dashboard.html")


@app.route("/examiner/dashboard")
@role_required("Examiner")
def examiner_dashboard():
    return render_template("examiner_dashboard.html")


@app.route("/student/dashboard")
@role_required("Student")
def student_dashboard():
    return render_template("student_dashboard.html")


if __name__ == "__main__":
    app.run(debug=True)