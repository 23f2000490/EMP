from functools import wraps
from datetime import datetime
from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from werkzeug.security import generate_password_hash
from sqlalchemy import or_
from models import (db, User, ExaminerProfile, Course, Examination,
                    ExaminationRubric, EvaluationScore,
                    ExaminationSlot, Booking)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        if session.get("role") != "Admin":
            flash("You are not allowed to access that page.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


def _like(q):
    return f"%{q}%"


# ---------- Dashboard ----------

@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    stats = {
        "courses": Course.query.count(),
        "examinations": Examination.query.count(),
        "examiners": ExaminerProfile.query.count(),
        "students": User.query.filter_by(role="Student").count(),
        "slots": ExaminationSlot.query.count(),
        "bookings": Booking.query.count(),
    }
    pending = ExaminerProfile.query.filter_by(status="Pending").count()
    return render_template("admin/dashboard.html", stats=stats, pending=pending)


# ---------- Courses ----------

@admin_bp.route("/courses")
@admin_required
def courses():
    all_courses = Course.query.order_by(Course.code).all()
    return render_template("admin/courses.html", courses=all_courses)


@admin_bp.route("/courses/new", methods=["GET", "POST"])
@admin_required
def course_new():
    if request.method == "POST":
        code = request.form["code"].strip().upper()
        name = request.form["name"].strip()
        description = request.form.get("description", "").strip()
        status = request.form.get("status", "Active")

        if not code or not name:
            flash("Course code and name are required.", "danger")
            return redirect(url_for("admin.course_new"))
        if Course.query.filter_by(code=code).first():
            flash("A course with this code already exists.", "danger")
            return redirect(url_for("admin.course_new"))

        db.session.add(Course(code=code, name=name,
                              description=description, status=status))
        db.session.commit()
        flash("Course created.", "success")
        return redirect(url_for("admin.courses"))
    return render_template("admin/course_form.html", course=None)


@admin_bp.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
@admin_required
def course_edit(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == "POST":
        code = request.form["code"].strip().upper()
        name = request.form["name"].strip()

        if not code or not name:
            flash("Course code and name are required.", "danger")
            return redirect(url_for("admin.course_edit", course_id=course_id))
        clash = Course.query.filter(Course.code == code, Course.id != course_id).first()
        if clash:
            flash("Another course already uses this code.", "danger")
            return redirect(url_for("admin.course_edit", course_id=course_id))

        course.code = code
        course.name = name
        course.description = request.form.get("description", "").strip()
        course.status = request.form.get("status", "Active")
        db.session.commit()
        flash("Course updated.", "success")
        return redirect(url_for("admin.courses"))
    return render_template("admin/course_form.html", course=course)


@admin_bp.route("/courses/<int:course_id>/delete", methods=["POST"])
@admin_required
def course_delete(course_id):
    course = Course.query.get_or_404(course_id)
    if course.examinations:
        flash("This course has examinations, so it can't be deleted. "
              "Set it to Inactive instead.", "warning")
        return redirect(url_for("admin.courses"))
    db.session.delete(course)
    db.session.commit()
    flash("Course deleted.", "success")
    return redirect(url_for("admin.courses"))


# ---------- Examiners ----------

@admin_bp.route("/examiners")
@admin_required
def examiners():
    q = request.args.get("q", "").strip()
    query = ExaminerProfile.query.join(User, ExaminerProfile.user_id == User.id)
    if q:
        conds = [User.full_name.ilike(_like(q)), User.email.ilike(_like(q))]
        if q.isdigit():
            conds.append(ExaminerProfile.id == int(q))
        query = query.filter(or_(*conds))
    return render_template("admin/examiners.html",
                           profiles=query.order_by(ExaminerProfile.id).all(), q=q)


@admin_bp.route("/examiners/new", methods=["GET", "POST"])
@admin_required
def examiner_new():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        full_name = request.form["full_name"].strip()
        phone = request.form.get("phone", "").strip()
        department = request.form.get("department", "").strip()

        if not email or not password or not full_name:
            flash("Email, password and name are required.", "danger")
            return redirect(url_for("admin.examiner_new"))
        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.", "danger")
            return redirect(url_for("admin.examiner_new"))

        user = User(email=email, password_hash=generate_password_hash(password),
                    full_name=full_name, role="Examiner",
                    phone=phone, department=department)
        db.session.add(user)
        db.session.flush()
        db.session.add(ExaminerProfile(user_id=user.id, contact_details=phone,
                                       department=department, status="Approved"))
        db.session.commit()
        flash("Examiner added and approved.", "success")
        return redirect(url_for("admin.examiners"))
    return render_template("admin/examiner_new.html")


@admin_bp.route("/examiners/<int:profile_id>", methods=["GET", "POST"])
@admin_required
def examiner_view(profile_id):
    profile = ExaminerProfile.query.get_or_404(profile_id)
    if request.method == "POST":
        status = request.form.get("status", profile.status)
        if status not in ("Pending", "Approved", "Deactivated"):
            flash("Invalid status.", "danger")
            return redirect(url_for("admin.examiner_view", profile_id=profile_id))
        profile.user.full_name = request.form["full_name"].strip()
        profile.user.phone = request.form.get("phone", "").strip()
        profile.contact_details = request.form.get("contact_details", "").strip()
        profile.department = request.form.get("department", "").strip()
        profile.user.department = profile.department
        profile.status = status
        db.session.commit()
        flash("Examiner updated.", "success")
        return redirect(url_for("admin.examiners"))
    return render_template("admin/examiner_form.html", profile=profile)


@admin_bp.route("/examiners/<int:profile_id>/status", methods=["POST"])
@admin_required
def examiner_status(profile_id):
    profile = ExaminerProfile.query.get_or_404(profile_id)
    new_status = request.form.get("status")
    if new_status not in ("Approved", "Deactivated"):
        flash("Invalid action.", "danger")
        return redirect(url_for("admin.examiners"))
    profile.status = new_status
    db.session.commit()
    flash(f"{profile.user.full_name} is now {new_status}.", "success")
    return redirect(url_for("admin.examiners"))


# ---------- Examinations ----------

EXAM_TYPES = ["Viva", "Practical", "Project Demo", "Assessment"]

# status -> list of (new_status, button label, button style)
TRANSITIONS = {
    "Draft": [("Slot Creation", "Open Slot Creation", "success")],
    "Slot Creation": [("Draft", "Close Slot Creation", "outline-secondary"),
                      ("Booking Open", "Open Booking", "success")],
    "Booking Open": [("Closed", "Close Booking", "outline-danger")],
    "Closed": [("Booking Open", "Reopen Booking", "success"),
               ("Completed", "Mark Completed", "dark")],
    "Completed": [],
}


def _date(value):
    value = (value or "").strip()
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def _read_exam_form(form):
    """Return (data, error). data is a dict of cleaned values."""
    try:
        data = {
            "course_id": int(form["course_id"]),
            "name": form["name"].strip(),
            "exam_type": form["exam_type"],
            "duration": int(form["duration"]),
            "max_marks": int(form["max_marks"]),
            "slot_creation_start": _date(form.get("slot_creation_start")),
            "slot_creation_end": _date(form.get("slot_creation_end")),
            "booking_start": _date(form.get("booking_start")),
            "booking_end": _date(form.get("booking_end")),
        }
    except (ValueError, KeyError):
        return None, "Please fill all fields with valid values."

    if not data["name"]:
        return None, "Examination name is required."
    if data["exam_type"] not in EXAM_TYPES:
        return None, "Invalid examination type."
    if data["duration"] <= 0 or data["max_marks"] <= 0:
        return None, "Duration and maximum marks must be positive."
    if not Course.query.get(data["course_id"]):
        return None, "Selected course does not exist."
    for a, b, label in [("slot_creation_start", "slot_creation_end", "Slot creation"),
                        ("booking_start", "booking_end", "Booking")]:
        if data[a] and data[b] and data[b] < data[a]:
            return None, f"{label} end date cannot be before its start date."
    return data, None


def _selected_examiners(form):
    ids = [int(i) for i in form.getlist("examiner_ids") if i.isdigit()]
    if not ids:
        return []
    return ExaminerProfile.query.filter(
        ExaminerProfile.id.in_(ids), ExaminerProfile.status == "Approved").all()


@admin_bp.route("/examinations")
@admin_required
def examinations():
    q = request.args.get("q", "").strip()
    query = Examination.query
    if q:
        conds = [Examination.name.ilike(_like(q))]
        if q.isdigit():
            conds.append(Examination.id == int(q))
        query = query.filter(or_(*conds))
    return render_template("admin/examinations.html",
                           exams=query.order_by(Examination.id).all(),
                           transitions=TRANSITIONS, q=q)


@admin_bp.route("/examinations/new", methods=["GET", "POST"])
@admin_required
def examination_new():
    if request.method == "POST":
        data, error = _read_exam_form(request.form)
        if error:
            flash(error, "danger")
            return redirect(url_for("admin.examination_new"))
        exam = Examination(**data, status="Draft")
        exam.examiners = _selected_examiners(request.form)
        db.session.add(exam)
        db.session.commit()
        flash("Examination created.", "success")
        return redirect(url_for("admin.examinations"))
    return render_template(
        "admin/examination_form.html", exam=None, types=EXAM_TYPES,
        courses=Course.query.filter_by(status="Active").order_by(Course.code).all(),
        examiners=ExaminerProfile.query.filter_by(status="Approved").all())


@admin_bp.route("/examinations/<int:exam_id>/edit", methods=["GET", "POST"])
@admin_required
def examination_edit(exam_id):
    exam = Examination.query.get_or_404(exam_id)
    if request.method == "POST":
        data, error = _read_exam_form(request.form)
        if error:
            flash(error, "danger")
            return redirect(url_for("admin.examination_edit", exam_id=exam_id))
        for key, value in data.items():
            setattr(exam, key, value)
        exam.examiners = _selected_examiners(request.form)
        db.session.commit()
        flash("Examination updated.", "success")
        return redirect(url_for("admin.examinations"))
    return render_template(
        "admin/examination_form.html", exam=exam, types=EXAM_TYPES,
        courses=Course.query.order_by(Course.code).all(),
        examiners=ExaminerProfile.query.filter_by(status="Approved").all())

@admin_bp.route("/examinations/<int:exam_id>/status", methods=["POST"])
@admin_required
def examination_status(exam_id):
    exam = Examination.query.get_or_404(exam_id)
    new_status = request.form.get("status")
    allowed = [t[0] for t in TRANSITIONS.get(exam.status, [])]
    if new_status not in allowed:
        flash("That status change is not allowed from the current status.", "danger")
        return redirect(url_for("admin.examinations"))
    if new_status == "Slot Creation" and not exam.examiners:
        flash("Assign at least one examiner (Edit) before opening slot creation.", "warning")
        return redirect(url_for("admin.examinations"))

    if new_status == "Completed":
        pending = Booking.query.filter_by(exam_id=exam.id, status="Booked").count()
        if pending:
            flash(f"{pending} booked student(s) are not evaluated yet. Ask the examiner "
                  "to evaluate them, or cancel their bookings from the Bookings page.",
                  "warning")
            return redirect(url_for("admin.examinations"))
        for s in exam.slots:
            if s.status != "Cancelled":
                s.status = "Completed"

    exam.status = new_status
    db.session.commit()
    flash(f"'{exam.name}' is now: {new_status}.", "success")
    return redirect(url_for("admin.examinations"))
@admin_bp.route("/examinations/<int:exam_id>/delete", methods=["POST"])
@admin_required
def examination_delete(exam_id):
    exam = Examination.query.get_or_404(exam_id)
    if exam.slots:
        flash("This examination has slots, so it can't be deleted. "
              "Close it instead to keep the history.", "warning")
        return redirect(url_for("admin.examinations"))
    db.session.delete(exam)
    db.session.commit()
    flash("Examination deleted.", "success")
    return redirect(url_for("admin.examinations"))
@admin_bp.route("/examinations/<int:exam_id>/publish", methods=["POST"])
@admin_required
def examination_publish(exam_id):
    exam = Examination.query.get_or_404(exam_id)
    if exam.results_published:
        exam.results_published = False
        flash(f"Results for '{exam.name}' are now hidden.", "info")
    else:
        if exam.status not in ("Closed", "Completed"):
            flash("Close the examination before publishing results.", "warning")
            return redirect(url_for("admin.examinations"))
        exam.results_published = True
        flash(f"Results for '{exam.name}' are now published.", "success")
    db.session.commit()
    return redirect(url_for("admin.examinations"))

# ---------- Rubrics ----------

def _read_rubric_form(form, exam, rubric_id=None):
    """Return (data, error)."""
    try:
        data = {
            "criterion_name": form["criterion_name"].strip(),
            "max_marks": int(form["max_marks"]),
            "weightage": float(form.get("weightage") or 0),
            "description": form.get("description", "").strip(),
        }
    except (ValueError, KeyError):
        return None, "Please enter valid numbers for marks and weightage."

    if not data["criterion_name"]:
        return None, "Criterion name is required."
    if data["max_marks"] <= 0:
        return None, "Maximum marks must be positive."
    if not 0 <= data["weightage"] <= 100:
        return None, "Weightage must be between 0 and 100."

    others = sum(r.max_marks for r in exam.rubrics if r.id != rubric_id)
    if others + data["max_marks"] > exam.max_marks:
        left = exam.max_marks - others
        return None, (f"Total rubric marks would exceed the examination's "
                      f"maximum of {exam.max_marks}. Marks still available: {left}.")
    return data, None


@admin_bp.route("/examinations/<int:exam_id>/rubrics")
@admin_required
def rubrics(exam_id):
    exam = Examination.query.get_or_404(exam_id)
    total = sum(r.max_marks for r in exam.rubrics)
    return render_template("admin/rubrics.html", exam=exam, total=total)


@admin_bp.route("/examinations/<int:exam_id>/rubrics/new", methods=["GET", "POST"])
@admin_required
def rubric_new(exam_id):
    exam = Examination.query.get_or_404(exam_id)
    if request.method == "POST":
        data, error = _read_rubric_form(request.form, exam)
        if error:
            flash(error, "danger")
            return redirect(url_for("admin.rubric_new", exam_id=exam_id))
        db.session.add(ExaminationRubric(exam_id=exam.id, **data))
        db.session.commit()
        flash("Criterion added.", "success")
        return redirect(url_for("admin.rubrics", exam_id=exam_id))
    return render_template("admin/rubric_form.html", exam=exam, rubric=None)


@admin_bp.route("/rubrics/<int:rubric_id>/edit", methods=["GET", "POST"])
@admin_required
def rubric_edit(rubric_id):
    rubric = ExaminationRubric.query.get_or_404(rubric_id)
    exam = rubric.examination
    if request.method == "POST":
        data, error = _read_rubric_form(request.form, exam, rubric_id=rubric.id)
        if error:
            flash(error, "danger")
            return redirect(url_for("admin.rubric_edit", rubric_id=rubric_id))
        for key, value in data.items():
            setattr(rubric, key, value)
        db.session.commit()
        flash("Criterion updated.", "success")
        return redirect(url_for("admin.rubrics", exam_id=exam.id))
    return render_template("admin/rubric_form.html", exam=exam, rubric=rubric)


@admin_bp.route("/rubrics/<int:rubric_id>/delete", methods=["POST"])
@admin_required
def rubric_delete(rubric_id):
    rubric = ExaminationRubric.query.get_or_404(rubric_id)
    exam_id = rubric.exam_id
    if EvaluationScore.query.filter_by(rubric_id=rubric.id).first():
        flash("Marks have already been awarded on this criterion, "
              "so it can't be deleted.", "warning")
        return redirect(url_for("admin.rubrics", exam_id=exam_id))
    db.session.delete(rubric)
    db.session.commit()
    flash("Criterion deleted.", "success")
    return redirect(url_for("admin.rubrics", exam_id=exam_id))


# ---------- Students ----------

@admin_bp.route("/students")
@admin_required
def students():
    q = request.args.get("q", "").strip()
    query = User.query.filter_by(role="Student")
    if q:
        conds = [User.full_name.ilike(_like(q)), User.email.ilike(_like(q))]
        if q.isdigit():
            conds.append(User.id == int(q))
        query = query.filter(or_(*conds))
    return render_template("admin/students.html",
                           students=query.order_by(User.id).all(), q=q)


# ---------- Slots ----------

@admin_bp.route("/slots")
@admin_required
def slots():
    all_slots = ExaminationSlot.query.order_by(
        ExaminationSlot.slot_date, ExaminationSlot.start_time).all()
    return render_template("admin/slots.html", slots=all_slots)


@admin_bp.route("/slots/<int:slot_id>/examiner", methods=["GET", "POST"])
@admin_required
def slot_change_examiner(slot_id):
    slot = ExaminationSlot.query.get_or_404(slot_id)
    candidates = [p for p in slot.examination.examiners if p.status == "Approved"]
    if request.method == "POST":
        try:
            new_id = int(request.form["examiner_id"])
        except (ValueError, KeyError):
            flash("Choose an examiner.", "danger")
            return redirect(url_for("admin.slot_change_examiner", slot_id=slot_id))
        if new_id not in [p.id for p in candidates]:
            flash("That examiner is not approved or not assigned to this examination.", "danger")
            return redirect(url_for("admin.slot_change_examiner", slot_id=slot_id))
        slot.examiner_id = new_id
        db.session.commit()
        flash("Examiner changed for this slot.", "success")
        return redirect(url_for("admin.slots"))
    return render_template("admin/slot_examiner.html", slot=slot, candidates=candidates)


# ---------- Bookings (also serves as full history) ----------

@admin_bp.route("/bookings")
@admin_required
def bookings():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    query = Booking.query.join(User, Booking.student_id == User.id)
    if q:
        conds = [User.full_name.ilike(_like(q)), User.email.ilike(_like(q))]
        if q.isdigit():
            conds += [Booking.id == int(q), User.id == int(q)]
        query = query.filter(or_(*conds))
    if status in ("Booked", "Cancelled", "Completed"):
        query = query.filter(Booking.status == status)
    return render_template("admin/bookings.html",
                           bookings=query.order_by(Booking.id.desc()).all(),
                           q=q, status=status)


@admin_bp.route("/bookings/<int:booking_id>/reschedule", methods=["GET", "POST"])
@admin_required
def booking_reschedule(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.status != "Booked":
        flash("Only bookings with status Booked can be rescheduled.", "warning")
        return redirect(url_for("admin.bookings"))

    options = ExaminationSlot.query.filter(
        ExaminationSlot.exam_id == booking.exam_id,
        ExaminationSlot.id != booking.slot_id,
        ExaminationSlot.status == "Available",
        ExaminationSlot.available_seats > 0).order_by(
        ExaminationSlot.slot_date, ExaminationSlot.start_time).all()

    if request.method == "POST":
        try:
            new_slot = ExaminationSlot.query.get(int(request.form["slot_id"]))
        except (ValueError, KeyError):
            new_slot = None
        if not new_slot or new_slot not in options:
            flash("Choose a valid slot with free seats.", "danger")
            return redirect(url_for("admin.booking_reschedule", booking_id=booking_id))

        clash = (Booking.query.join(ExaminationSlot, Booking.slot_id == ExaminationSlot.id)
                 .filter(Booking.student_id == booking.student_id,
                         Booking.status == "Booked",
                         Booking.id != booking.id,
                         ExaminationSlot.slot_date == new_slot.slot_date).all())
        for other in clash:
            if (new_slot.start_time < other.slot.end_time
                    and other.slot.start_time < new_slot.end_time):
                flash("The student already has another booking that overlaps that slot.", "danger")
                return redirect(url_for("admin.booking_reschedule", booking_id=booking_id))

        old_slot = booking.slot
        old_slot.available_seats += 1
        if old_slot.status == "Full":
            old_slot.status = "Available"
        new_slot.available_seats -= 1
        if new_slot.available_seats == 0:
            new_slot.status = "Full"
        booking.slot_id = new_slot.id
        db.session.commit()
        flash("Booking rescheduled.", "success")
        return redirect(url_for("admin.bookings"))
    return render_template("admin/booking_reschedule.html",
                           booking=booking, options=options)
@admin_bp.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@admin_required
def booking_cancel(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.status != "Booked":
        flash("Only bookings with status Booked can be cancelled.", "warning")
        return redirect(url_for("admin.bookings"))
    slot = booking.slot
    booking.status = "Cancelled"
    booking.cancelled_at = datetime.utcnow()
    slot.available_seats += 1
    if slot.status == "Full":
        slot.status = "Available"
    db.session.commit()
    flash("Booking cancelled.", "success")
    return redirect(url_for("admin.bookings"))


@admin_bp.route("/students/<int:student_id>")
@admin_required
def student_history(student_id):
    student = User.query.filter_by(id=student_id, role="Student").first_or_404()
    rows = (Booking.query.filter_by(student_id=student.id)
            .order_by(Booking.id.desc()).all())
    return render_template("admin/student_history.html", student=student, bookings=rows)