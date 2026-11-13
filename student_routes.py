from datetime import date, datetime
from functools import wraps
from flask import (Blueprint, render_template, session, redirect, url_for,
                   flash, request, g, abort)
from sqlalchemy import or_
from models import (db, User, Course, Examination, ExaminationSlot,
                    Booking, Evaluation)

student_bp = Blueprint("student", __name__, url_prefix="/student")


def student_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        if session.get("role") != "Student":
            flash("You are not allowed to access that page.", "danger")
            return redirect(url_for("index"))
        user = User.query.get(session["user_id"])
        if not user or not user.is_active:
            session.clear()
            flash("Your account is not active.", "danger")
            return redirect(url_for("login"))
        g.user = user
        return f(*args, **kwargs)
    return wrapper


def booking_window_open(exam):
    """Return (ok, message). Used by the dashboard now and by booking in 5B."""
    if exam.status != "Booking Open":
        return False, "Booking is not open for this examination."
    today = date.today()
    if exam.booking_start and today < exam.booking_start:
        return False, "Booking has not started yet."
    if exam.booking_end and today > exam.booking_end:
        return False, "The booking period has ended."
    return True, ""


@student_bp.route("/dashboard")
@student_required
def dashboard():
    uid = g.user.id
    today = date.today()

    open_exams = [e for e in Examination.query.filter_by(status="Booking Open").all()
                  if booking_window_open(e)[0]]
    open_ids = [e.id for e in open_exams]

    available_slots = 0
    if open_ids:
        available_slots = ExaminationSlot.query.filter(
            ExaminationSlot.exam_id.in_(open_ids),
            ExaminationSlot.status == "Available",
            ExaminationSlot.available_seats > 0,
            ExaminationSlot.slot_date >= today).count()

    my_booked = Booking.query.filter_by(student_id=uid, status="Booked")
    upcoming = (my_booked.join(ExaminationSlot, Booking.slot_id == ExaminationSlot.id)
                .filter(ExaminationSlot.slot_date >= today)
                .order_by(ExaminationSlot.slot_date, ExaminationSlot.start_time).all())

    published = (Booking.query.filter_by(student_id=uid)
                 .join(Evaluation, Evaluation.booking_id == Booking.id)
                 .join(Examination, Booking.exam_id == Examination.id)
                 .filter(Examination.results_published.is_(True)).count())

    stats = {
        "exams": len(open_exams),
        "slots": available_slots,
        "upcoming": len(upcoming),
        "booked": my_booked.count(),
        "results": published,
    }
    return render_template("student/dashboard.html", stats=stats,
                           upcoming=upcoming[:5])


@student_bp.route("/examinations")
@student_required
def examinations():
    q = request.args.get("q", "").strip()
    exam_type = request.args.get("exam_type", "").strip()
    course_id = request.args.get("course_id", type=int)
    status = request.args.get("status", "").strip()

    query = (Examination.query.join(Course, Examination.course_id == Course.id)
             .filter(Examination.status != "Draft"))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Examination.name.ilike(like),
                                 Course.code.ilike(like), Course.name.ilike(like)))
    if exam_type:
        query = query.filter(Examination.exam_type == exam_type)
    if course_id:
        query = query.filter(Examination.course_id == course_id)
    if status:
        query = query.filter(Examination.status == status)

    exams = query.order_by(Examination.id).all()
    booked_ids = {b.exam_id for b in Booking.query.filter(
        Booking.student_id == g.user.id,
        Booking.status.in_(["Booked", "Completed"])).all()}
    return render_template(
        "student/examinations.html", exams=exams, booked_ids=booked_ids,
        courses=Course.query.order_by(Course.code).all(),
        types=["Viva", "Practical", "Project Demo", "Assessment"],
        statuses=["Slot Creation", "Booking Open", "Closed", "Completed"],
        q=q, exam_type=exam_type, course_id=course_id, status=status)


@student_bp.route("/profile", methods=["GET", "POST"])
@student_required
def profile():
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        if not full_name:
            flash("Name is required.", "danger")
            return redirect(url_for("student.profile"))
        g.user.full_name = full_name
        g.user.phone = request.form.get("phone", "").strip()
        g.user.department = request.form.get("department", "").strip()
        db.session.commit()
        session["name"] = full_name
        flash("Profile updated.", "success")
        return redirect(url_for("student.profile"))
    return render_template("student/profile.html", user=g.user)

# ---------- Slots and booking ----------

def _active_exam_ids(student_id):
    """Exams the student already holds a Booked or Completed booking for."""
    return {b.exam_id for b in Booking.query.filter(
        Booking.student_id == student_id,
        Booking.status.in_(["Booked", "Completed"])).all()}


@student_bp.route("/slots")
@student_required
def slots():
    today = date.today()
    open_ids = [e.id for e in Examination.query.filter_by(status="Booking Open").all()
                if booking_window_open(e)[0]]
    rows = []
    if open_ids:
        rows = ExaminationSlot.query.filter(
            ExaminationSlot.exam_id.in_(open_ids),
            ExaminationSlot.status == "Available",
            ExaminationSlot.available_seats > 0,
            ExaminationSlot.slot_date >= today).order_by(
            ExaminationSlot.slot_date, ExaminationSlot.start_time).all()
    return render_template("student/slots.html", slots=rows,
                           booked_exam_ids=_active_exam_ids(g.user.id))


@student_bp.route("/slots/<int:slot_id>/book", methods=["POST"])
@student_required
def book_slot(slot_id):
    slot = ExaminationSlot.query.get_or_404(slot_id)
    exam = slot.examination

    ok, msg = booking_window_open(exam)
    if not ok:
        flash(msg, "danger")
        return redirect(url_for("student.slots"))
    if slot.status != "Available" or slot.available_seats <= 0:
        flash("Sorry, this slot is full.", "danger")
        return redirect(url_for("student.slots"))
    if slot.slot_date < date.today():
        flash("This slot is in the past.", "danger")
        return redirect(url_for("student.slots"))
    if exam.id in _active_exam_ids(g.user.id):
        flash("You already have a booking for this examination.", "danger")
        return redirect(url_for("student.slots"))

    # No overlapping slot on the same day
    mine = (Booking.query.join(ExaminationSlot, Booking.slot_id == ExaminationSlot.id)
            .filter(Booking.student_id == g.user.id, Booking.status == "Booked",
                    ExaminationSlot.slot_date == slot.slot_date).all())
    for b in mine:
        if slot.start_time < b.slot.end_time and b.slot.start_time < slot.end_time:
            flash("This slot overlaps another examination you have booked.", "danger")
            return redirect(url_for("student.slots"))

        # Take the seat atomically: succeeds only if a seat is still free
    taken = (ExaminationSlot.query
             .filter(ExaminationSlot.id == slot.id,
                     ExaminationSlot.status == "Available",
                     ExaminationSlot.available_seats > 0)
             .update({"available_seats": ExaminationSlot.available_seats - 1},
                     synchronize_session=False))
    if taken == 0:
        db.session.rollback()
        flash("Sorry, this slot was just filled.", "danger")
        return redirect(url_for("student.slots"))

    db.session.add(Booking(student_id=g.user.id, slot_id=slot.id, exam_id=exam.id))
    db.session.flush()
    db.session.refresh(slot)
    if slot.available_seats == 0:
        slot.status = "Full"
    db.session.commit()
    flash("Slot booked successfully.", "success")
    return redirect(url_for("student.bookings"))


@student_bp.route("/bookings")
@student_required
def bookings():
    rows = (Booking.query.filter_by(student_id=g.user.id)
            .join(ExaminationSlot, Booking.slot_id == ExaminationSlot.id)
            .order_by(ExaminationSlot.slot_date, ExaminationSlot.start_time).all())
    upcoming = [b for b in rows if b.status == "Booked"]
    history = sorted([b for b in rows if b.status != "Booked"],
                     key=lambda b: b.id, reverse=True)
    can_cancel = {b.id: _cancel_allowed(b)[0] for b in upcoming}
    return render_template("student/bookings.html", upcoming=upcoming,
                           history=history, can_cancel=can_cancel)


@student_bp.route("/results")
@student_required
def results():
    rows = (Booking.query.filter_by(student_id=g.user.id)
            .join(Evaluation, Evaluation.booking_id == Booking.id)
            .join(Examination, Booking.exam_id == Examination.id)
            .filter(Examination.results_published.is_(True))
            .order_by(Booking.id.desc()).all())
    return render_template("student/results.html", bookings=rows)


@student_bp.route("/results/<int:booking_id>")
@student_required
def result_detail(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.student_id != g.user.id:
        abort(403)
    if not booking.evaluation or not booking.examination.results_published:
        flash("Results for this examination are not published yet.", "warning")
        return redirect(url_for("student.results"))
    return render_template("student/result_detail.html", booking=booking,
                           evaluation=booking.evaluation)
def _cancel_allowed(booking):
    """Return (ok, message)."""
    if booking.status != "Booked":
        return False, "Only active bookings can be cancelled."
    if booking.evaluation:
        return False, "This examination has already been evaluated."
    exam = booking.examination
    if exam.status != "Booking Open":
        return False, "Cancellation is closed because booking is no longer open."
    if exam.booking_end and date.today() > exam.booking_end:
        return False, "The booking deadline has passed."
    if booking.slot.slot_date < date.today():
        return False, "This slot is in the past."
    return True, ""


@student_bp.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@student_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.student_id != g.user.id:
        abort(403)
    ok, msg = _cancel_allowed(booking)
    if not ok:
        flash(msg, "danger")
        return redirect(url_for("student.bookings"))

    slot = booking.slot
    booking.status = "Cancelled"
    booking.cancelled_at = datetime.utcnow()
    slot.available_seats += 1
    if slot.status == "Full":
        slot.status = "Available"
    db.session.commit()
    flash("Booking cancelled.", "success")
    return redirect(url_for("student.bookings"))