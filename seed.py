""" seed_demo.py – populate the database with realistic demo data for video.

    Usage (run from your project root):
        DATABASE_URL=postgresql://... python seed_demo.py

    The script will:
        - create a superadmin if one doesn't exist
        - create a staff user for each school (A, B, C)
        - create accepted/pending schedules (today, tomorrow, etc.)
        - create session logs (past days with varying stats)
"""

import os
from datetime import date, datetime, timedelta
from app import create_app
from models import db, User, Schedule, SessionLog

app = create_app()


def seed():
    with app.app_context():
        db.create_all()

        admin = User.query.filter_by(role="superadmin").first()
        if not admin:
            admin = User(
                username="ansh",
                email="ansh@edutracker.com",
                name="Ansh Verma",
                role="superadmin",
            )
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.flush()
            print("✅ Superadmin created (ansh / admin123)")

        schools = ["A", "B", "C"]
        staff_users = {}
        for school in schools:
            user = User.query.filter_by(username=f"staff_{school}").first()
            if not user:
                user = User(
                    username=f"staff_{school}",
                    email=f"staff{school}@school.edu",
                    name=f"Teacher {school}",
                    role="staff",
                    school=school,
                )
                user.set_password("test123")
                db.session.add(user)
                db.session.flush()
            staff_users[school] = user
        db.session.commit()
        print("✅ Staff users created (staff_A / staff_B / staff_C, password: test123)")

        today = date.today()

        schedule_data = [
            (schools[0], today, "09:00", "10:00", "accepted", "normal", "Visual attention tasks"),
            (schools[0], today + timedelta(days=1), "09:00", "10:00", "accepted", "experiment", "New reading module"),
            (schools[0], today + timedelta(days=3), "10:00", "11:00", "pending", "normal", "Group discussion"),
            (schools[1], today, "10:00", "11:00", "accepted", "normal", "Memory & working memory"),
            (schools[1], today + timedelta(days=1), "10:00", "11:00", "accepted", "experiment", "Auditory processing"),
            (schools[1], today + timedelta(days=2), "11:00", "12:00", "pending", "normal", "Reading fluency test"),
            (schools[2], today + timedelta(days=1), "11:00", "12:00", "accepted", "normal", "Listening comprehension"),
            (schools[2], today + timedelta(days=2), "09:30", "10:30", "accepted", "normal", "Cognitive games"),
            (schools[2], today + timedelta(days=4), "10:00", "11:00", "pending", "experiment", "New tablet feature"),
        ]

        for (sch, s_date, s_start, s_end, status, sess_type, topic) in schedule_data:
            exists = Schedule.query.filter_by(
                school=sch, proposed_date=s_date, start_time=s_start
            ).first()
            if not exists:
                s = Schedule(
                    school=sch,
                    proposed_date=s_date,
                    start_time=s_start,
                    end_time=s_end,
                    status=status,
                    session_type=sess_type,
                    topic=topic,
                    proposed_by=staff_users[sch].id,
                )
                db.session.add(s)
        db.session.commit()
        print("✅ Schedules seeded")

        log_data = [
            (schools[0], today - timedelta(days=1), "09:00", "10:00", 45, 88, "normal", "Great focus today", True, False, True),
            (schools[0], today - timedelta(days=2), "09:00", "10:00", 0, 0, "normal", "No students attended", False, False, False),
            (schools[0], today - timedelta(days=4), "09:30", "10:30", 50, 92, "experiment", "Experiment went well", True, False, True),
            (schools[1], today - timedelta(days=1), "10:00", "11:00", 42, 82, "normal", "Kids really enjoyed the memory game", True, False, False),
            (schools[1], today - timedelta(days=3), "10:15", "11:15", 38, 65, "normal", "Projector issue", False, True, False),
            (schools[1], today - timedelta(days=5), "09:30", "10:30", 40, 78, "experiment", "Smooth session", True, False, True),
            (schools[2], today - timedelta(days=1), "11:00", "12:00", 35, 70, "normal", "Good participation", True, False, False),
            (schools[2], today - timedelta(days=3), "11:00", "12:00", 30, 60, "normal", "Students tired", False, False, False),
            (schools[2], today - timedelta(days=6), "10:00", "11:00", 28, 75, "normal", "Engaging content", True, False, False),
        ]

        for (sch, l_date, start, end, hc, eng, stype, notes, feedback, tech, sup_present) in log_data:
            exists = SessionLog.query.filter_by(
                school=sch, date=l_date, start_time=start
            ).first()
            if not exists:
                log = SessionLog(
                    school=sch,
                    date=l_date,
                    start_time=start,
                    end_time=end,
                    headcount=hc,
                    engagement=eng,
                    session_type=stype,
                    notes=notes,
                    feedback_sheets_collected=feedback,
                    technical_issue=tech,
                    supervisor_present=sup_present,
                    created_by=staff_users[sch].id,
                )
                db.session.add(log)
        db.session.commit()
        print("✅ Session logs seeded")

        print("\n🎬 Demo data ready! Use these logins:")
        print("   Superadmin  →  ansh / admin123")
        for sch in schools:
            print(f"   Staff {sch}     →  staff_{sch} / test123")
        print("\nYou can now record your video.")


if __name__ == "__main__":
    seed()