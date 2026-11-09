from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Extra table: which examiners are assigned to which examination (many-to-many)
exam_examiners = db.Table(
    "exam_examiners",
    db.Column("exam_id", db.Integer, db.ForeignKey("examinations.id"), primary_key=True),
    db.Column("examiner_id", db.Integer, db.ForeignKey("examiner_profiles.id"), primary_key=True),
)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # Admin / Examiner / Student
    phone = db.Column(db.String(20))
    department = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    examiner_profile = db.relationship("ExaminerProfile", back_populates="user",
                                       uselist=False, cascade="all, delete-orphan")
    bookings = db.relationship("Booking", back_populates="student")


class ExaminerProfile(db.Model):
    __tablename__ = "examiner_profiles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    contact_details = db.Column(db.String(200))
    department = db.Column(db.String(100))
    status = db.Column(db.String(20), default="Pending")  # Pending / Approved / Deactivated

    user = db.relationship("User", back_populates="examiner_profile")
    slots = db.relationship("ExaminationSlot", back_populates="examiner")
    exams = db.relationship("Examination", secondary=exam_examiners,
                            back_populates="examiners")


class Course(db.Model):
    __tablename__ = "courses"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="Active")  # Active / Inactive

    examinations = db.relationship("Examination", back_populates="course")


class Examination(db.Model):
    __tablename__ = "examinations"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    exam_type = db.Column(db.String(30), nullable=False)  # Viva / Practical / Project Demo / Assessment
    duration = db.Column(db.Integer, nullable=False)       # minutes
    max_marks = db.Column(db.Integer, nullable=False)
    slot_creation_start = db.Column(db.Date)
    slot_creation_end = db.Column(db.Date)
    booking_start = db.Column(db.Date)
    booking_end = db.Column(db.Date)
    # Draft / Slot Creation / Booking Open / Closed / Completed
    status = db.Column(db.String(20), default="Draft")
    results_published = db.Column(db.Boolean, default=False)

    course = db.relationship("Course", back_populates="examinations")
    rubrics = db.relationship("ExaminationRubric", back_populates="examination",
                              cascade="all, delete-orphan")
    slots = db.relationship("ExaminationSlot", back_populates="examination",
                            cascade="all, delete-orphan")
    examiners = db.relationship("ExaminerProfile", secondary=exam_examiners,
                                back_populates="exams")


class ExaminationRubric(db.Model):
    __tablename__ = "examination_rubrics"
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("examinations.id"), nullable=False)
    criterion_name = db.Column(db.String(100), nullable=False)
    max_marks = db.Column(db.Integer, nullable=False)
    weightage = db.Column(db.Float, default=0)
    description = db.Column(db.Text)

    examination = db.relationship("Examination", back_populates="rubrics")


class ExaminationSlot(db.Model):
    __tablename__ = "examination_slots"
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("examinations.id"), nullable=False)
    examiner_id = db.Column(db.Integer, db.ForeignKey("examiner_profiles.id"), nullable=False)
    slot_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    available_seats = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="Available")  # Available / Full / Cancelled / Completed

    examination = db.relationship("Examination", back_populates="slots")
    examiner = db.relationship("ExaminerProfile", back_populates="slots")
    bookings = db.relationship("Booking", back_populates="slot")


class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey("examination_slots.id"), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey("examinations.id"), nullable=False)
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="Booked")  # Booked / Cancelled / Completed
    cancelled_at = db.Column(db.DateTime)

    student = db.relationship("User", back_populates="bookings")
    slot = db.relationship("ExaminationSlot", back_populates="bookings")
    examination = db.relationship("Examination")
    evaluation = db.relationship("Evaluation", back_populates="booking",
                                 uselist=False, cascade="all, delete-orphan")


# Extra tables for evaluation records (marks + remarks)
class Evaluation(db.Model):
    __tablename__ = "evaluations"
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), unique=True, nullable=False)
    examiner_id = db.Column(db.Integer, db.ForeignKey("examiner_profiles.id"), nullable=False)
    total_marks = db.Column(db.Float, default=0)
    remarks = db.Column(db.Text)
    evaluated_at = db.Column(db.DateTime, default=datetime.utcnow)

    booking = db.relationship("Booking", back_populates="evaluation")
    scores = db.relationship("EvaluationScore", back_populates="evaluation",
                             cascade="all, delete-orphan")


class EvaluationScore(db.Model):
    __tablename__ = "evaluation_scores"
    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey("evaluations.id"), nullable=False)
    rubric_id = db.Column(db.Integer, db.ForeignKey("examination_rubrics.id"), nullable=False)
    awarded_marks = db.Column(db.Float, nullable=False)

    evaluation = db.relationship("Evaluation", back_populates="scores")
    rubric = db.relationship("ExaminationRubric")