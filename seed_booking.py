from app import app
from models import db, User, ExaminationSlot, Booking

with app.app_context():
    slot = ExaminationSlot.query.filter(
        ExaminationSlot.status == "Available",
        ExaminationSlot.available_seats > 0).first()
    if not slot:
        print("No available slot found. Create one as Examiner first.")
    else:
        for student in User.query.filter_by(role="Student").all():
            already = Booking.query.filter_by(student_id=student.id,
                                              exam_id=slot.exam_id,
                                              status="Booked").first()
            if already or slot.available_seats == 0:
                continue
            db.session.add(Booking(student_id=student.id, slot_id=slot.id,
                                   exam_id=slot.exam_id))
            slot.available_seats -= 1
            if slot.available_seats == 0:
                slot.status = "Full"
            print("Booked:", student.email)
        db.session.commit()
        print("Done.")