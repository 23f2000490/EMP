from datetime import datetime, date
from functools import wraps
from flask import (Blueprint, render_template, session, redirect, url_for,
                   flash, request, g, abort)
from models import (db, User, ExaminerProfile, ExaminationSlot, Booking,
                    Evaluation, EvaluationScore)
examiner_bp = Blueprint("examiner", __name__, url_prefix="/examiner")


def examiner_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        if session.get("role") != "Examiner":
            flash("You are not allowed to access that page.", "danger")
            return redirect(url_for("index"))
        profile = ExaminerProfile.query.filter_by(user_id=session["user_id"]).first()
        if not profile or profile.status != "Approved":
            session.clear()
            flash("Your examiner account is not approved or has been deactivated.", "danger")
            return redirect(url_for("login"))
        g.profile = profile
        return f(*args, **kwargs)
    return wrapper


@examiner_bp.route("/dashboard")
@examiner_required
def dashboard():
    pid = g.profile.id
    my_slots = ExaminationSlot.query.filter_by(examiner_id=pid)

    booked = (Booking.query.join(ExaminationSlot, Booking.slot_id == ExaminationSlot.id)
              .filter(ExaminationSlot.examiner_id == pid, Booking.status == "Booked"))

    pending = (Booking.query.join(ExaminationSlot, Booking.slot_id == ExaminationSlot.id)
               .outerjoin(Evaluation, Evaluation.booking_id == Booking.id)
               .filter(ExaminationSlot.examiner_id == pid,
                       Booking.status == "Booked",
                       Evaluation.id.is_(None)))

    stats = {
        "exams": len(g.profile.exams),
        "slots": my_slots.filter(ExaminationSlot.status != "Cancelled").count(),
        "booked": booked.count(),
        "pending": pending.count(),
    }
    slot_counts = {e.id: my_slots.filter_by(exam_id=e.id).count() for e in g.profile.exams}
    return render_template("examiner/dashboard.html", stats=stats,
                           exams=g.profile.exams, slot_counts=slot_counts)


@examiner_bp.route("/profile", methods=["GET", "POST"])
@examiner_required
def profile():
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        if not full_name:
            flash("Name is required.", "danger")
            return redirect(url_for("examiner.profile"))
        g.profile.user.full_name = full_name
        g.profile.user.phone = request.form.get("phone", "").strip()
        g.profile.contact_details = request.form.get("contact_details", "").strip()
        g.profile.department = request.form.get("department", "").strip()
        g.profile.user.department = g.profile.department
        db.session.commit()
        session["name"] = full_name
        flash("Profile updated.", "success")
        return redirect(url_for("examiner.profile"))
    return render_template("examiner/profile.html", profile=g.profile)


# ---------- Slots ----------

def _active_bookings(slot):
    return [b for b in slot.bookings if b.status != "Cancelled"]


def _slot_creation_open(exam):
    """Return (ok, message)."""
    if exam.status != "Slot Creation":
        return False, "Slot creation is not open for this examination."
    today = date.today()
    if exam.slot_creation_start and today < exam.slot_creation_start:
        return False, "Slot creation has not started yet."
    if exam.slot_creation_end and today > exam.slot_creation_end:
        return False, "The slot creation period has ended."
    return True, ""


def _read_slot_form(form):
    """Return (data, error)."""
    try:
        data = {
            "exam_id": int(form["exam_id"]),
            "slot_date": datetime.strptime(form["slot_date"], "%Y-%m-%d").date(),
            "start_time": datetime.strptime(form["start_time"], "%H:%M").time(),
            "end_time": datetime.strptime(form["end_time"], "%H:%M").time(),
            "capacity": int(form["capacity"]),
        }
    except (ValueError, KeyError):
        return None, "Please fill all fields with valid values."

    if data["end_time"] <= data["start_time"]:
        return None, "End time must be after start time."
    if data["capacity"] < 1:
        return None, "Capacity must be at least 1."
    if data["slot_date"] < date.today():
        return None, "Slot date cannot be in the past."
    return data, None


def _clashes(examiner_id, data, ignore_slot_id=None):
    others = ExaminationSlot.query.filter(
        ExaminationSlot.examiner_id == examiner_id,
        ExaminationSlot.slot_date == data["slot_date"],
        ExaminationSlot.status != "Cancelled")
    if ignore_slot_id:
        others = others.filter(ExaminationSlot.id != ignore_slot_id)
    for s in others.all():
        if data["start_time"] < s.end_time and s.start_time < data["end_time"]:
            return True
    return False


def _my_slot_or_404(slot_id):
    slot = ExaminationSlot.query.get_or_404(slot_id)
    if slot.examiner_id != g.profile.id:
        from flask import abort
        abort(403)
    return slot


@examiner_bp.route("/slots")
@examiner_required
def slots():
    my = (ExaminationSlot.query.filter_by(examiner_id=g.profile.id)
          .order_by(ExaminationSlot.slot_date, ExaminationSlot.start_time).all())
    editable = {s.id: (s.examination.status in ("Draft", "Slot Creation")
                       and not _active_bookings(s) and s.status != "Cancelled")
                for s in my}
    return render_template("examiner/slots.html", slots=my, editable=editable)


@examiner_bp.route("/slots/new", methods=["GET", "POST"])
@examiner_required
def slot_new():
    if request.method == "POST":
        data, error = _read_slot_form(request.form)
        if error:
            flash(error, "danger")
            return redirect(url_for("examiner.slot_new"))

        exam = next((e for e in g.profile.exams if e.id == data["exam_id"]), None)
        if not exam:
            flash("You are not assigned to that examination.", "danger")
            return redirect(url_for("examiner.slot_new"))
        ok, msg = _slot_creation_open(exam)
        if not ok:
            flash(msg, "danger")
            return redirect(url_for("examiner.slot_new"))
        if _clashes(g.profile.id, data):
            flash("You already have a slot that overlaps this time.", "danger")
            return redirect(url_for("examiner.slot_new"))

        db.session.add(ExaminationSlot(
            examiner_id=g.profile.id, available_seats=data["capacity"],
            status="Available", **data))
        db.session.commit()
        flash("Slot created.", "success")
        return redirect(url_for("examiner.slots"))

    open_exams = [e for e in g.profile.exams if _slot_creation_open(e)[0]]
    return render_template("examiner/slot_form.html", slot=None, exams=open_exams)


@examiner_bp.route("/slots/<int:slot_id>/edit", methods=["GET", "POST"])
@examiner_required
def slot_edit(slot_id):
    slot = _my_slot_or_404(slot_id)
    if (slot.examination.status not in ("Draft", "Slot Creation")
            or _active_bookings(slot) or slot.status == "Cancelled"):
        flash("This slot can't be changed because booking has started "
              "or students have booked it.", "warning")
        return redirect(url_for("examiner.slots"))

    if request.method == "POST":
        form = request.form.to_dict()
        form["exam_id"] = str(slot.exam_id)      # exam can't be changed
        data, error = _read_slot_form(form)
        if error:
            flash(error, "danger")
            return redirect(url_for("examiner.slot_edit", slot_id=slot_id))
        if _clashes(g.profile.id, data, ignore_slot_id=slot.id):
            flash("You already have a slot that overlaps this time.", "danger")
            return redirect(url_for("examiner.slot_edit", slot_id=slot_id))

        slot.slot_date = data["slot_date"]
        slot.start_time = data["start_time"]
        slot.end_time = data["end_time"]
        slot.capacity = data["capacity"]
        slot.available_seats = data["capacity"]
        slot.status = "Available"
        db.session.commit()
        flash("Slot updated.", "success")
        return redirect(url_for("examiner.slots"))
    return render_template("examiner/slot_form.html", slot=slot, exams=[slot.examination])


@examiner_bp.route("/slots/<int:slot_id>/delete", methods=["POST"])
@examiner_required
def slot_delete(slot_id):
    slot = _my_slot_or_404(slot_id)
    if (slot.examination.status not in ("Draft", "Slot Creation")
            or _active_bookings(slot)):
        flash("This slot can't be removed because booking has started "
              "or students have booked it.", "warning")
        return redirect(url_for("examiner.slots"))

    if slot.bookings:                 # only cancelled bookings: keep history
        slot.status = "Cancelled"
        flash("Slot cancelled (kept for booking history).", "success")
    else:
        db.session.delete(slot)
        flash("Slot removed.", "success")
    db.session.commit()
    return redirect(url_for("examiner.slots"))


# ---------- Booked students and evaluation ----------

def _my_booking_or_404(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.slot.examiner_id != g.profile.id:
        abort(403)
    return booking


@examiner_bp.route("/students")
@examiner_required
def students():
    exam_id = request.args.get("exam_id", type=int)
    status = request.args.get("status", "").strip()

    query = (Booking.query
             .join(ExaminationSlot, Booking.slot_id == ExaminationSlot.id)
             .filter(ExaminationSlot.examiner_id == g.profile.id))
    if exam_id:
        query = query.filter(Booking.exam_id == exam_id)
    if status in ("Booked", "Cancelled", "Completed"):
        query = query.filter(Booking.status == status)
    rows = query.order_by(ExaminationSlot.slot_date,
                          ExaminationSlot.start_time, Booking.id).all()
    return render_template("examiner/students.html", bookings=rows,
                           exams=g.profile.exams, exam_id=exam_id, status=status)


@examiner_bp.route("/bookings/<int:booking_id>/evaluate", methods=["GET", "POST"])
@examiner_required
def evaluate(booking_id):
    booking = _my_booking_or_404(booking_id)
    exam = booking.examination

    if booking.status == "Cancelled":
        flash("This booking was cancelled and can't be evaluated.", "warning")
        return redirect(url_for("examiner.students"))
    if not exam.rubrics:
        flash("This examination has no rubric criteria yet. Ask the Admin to add them.", "warning")
        return redirect(url_for("examiner.students"))
    if exam.results_published:
        flash("Results are already published, so this evaluation is locked.", "warning")
        return redirect(url_for("examiner.students"))

    evaluation = booking.evaluation

    if request.method == "POST":
        scores = {}
        for r in exam.rubrics:
            raw = request.form.get(f"marks_{r.id}", "").strip()
            try:
                value = float(raw)
            except ValueError:
                flash(f"Enter valid marks for '{r.criterion_name}'.", "danger")
                return redirect(url_for("examiner.evaluate", booking_id=booking_id))
            if not 0 <= value <= r.max_marks:
                flash(f"Marks for '{r.criterion_name}' must be between 0 and {r.max_marks}.", "danger")
                return redirect(url_for("examiner.evaluate", booking_id=booking_id))
            scores[r.id] = value

        if evaluation is None:
            evaluation = Evaluation(booking_id=booking.id, examiner_id=g.profile.id)
            db.session.add(evaluation)
            db.session.flush()
        else:
            evaluation.scores.clear()
            db.session.flush()

        for rubric_id, value in scores.items():
            evaluation.scores.append(EvaluationScore(rubric_id=rubric_id,
                                                     awarded_marks=value))
        evaluation.total_marks = sum(scores.values())
        evaluation.remarks = request.form.get("remarks", "").strip()
        evaluation.examiner_id = g.profile.id
        evaluation.evaluated_at = datetime.utcnow()
        booking.status = "Completed"
        db.session.commit()
        flash("Evaluation saved.", "success")
        return redirect(url_for("examiner.students"))

    existing = {s.rubric_id: s.awarded_marks for s in evaluation.scores} if evaluation else {}
    rubric_total = sum(r.max_marks for r in exam.rubrics)
    return render_template("examiner/evaluate.html", booking=booking, exam=exam,
                           evaluation=evaluation, existing=existing,
                           rubric_total=rubric_total)