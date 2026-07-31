from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    # role: 'superadmin' | 'staff' | 'researcher'
    role = db.Column(db.String(20), nullable=False)
    # school only applies to staff accounts
    school = db.Column(db.String(50), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


from datetime import datetime as _datetime


class SessionLog(db.Model):
    __tablename__ = "session_logs"

    id = db.Column(db.Integer, primary_key=True)
    school = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(10))
    end_time = db.Column(db.String(10))
    headcount = db.Column(db.Integer, nullable=False)
    engagement = db.Column(db.Integer, nullable=False)
    session_type = db.Column(db.String(20), default="normal")
    notes = db.Column(db.Text)

    feedback_sheets_collected = db.Column(db.Boolean, default=False)
    supervisor_present = db.Column(db.Boolean, default=False)

    technical_issue = db.Column(db.Boolean, default=False)
    issue_description = db.Column(db.Text, nullable=True)
    time_lost_minutes = db.Column(db.Integer, nullable=True)
    issue_resolved = db.Column(db.Boolean, default=False)
    called_superadmin = db.Column(db.Boolean, default=False)

    student_feedback_1 = db.Column(db.Text)
    student_feedback_2 = db.Column(db.Text)
    student_feedback_3 = db.Column(db.Text)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=_datetime.utcnow)

    staff = db.relationship("User", backref="session_logs")
    photos = db.relationship("SessionPhoto", backref="session_log", lazy=True)


class SessionPhoto(db.Model):
    __tablename__ = "session_photos"

    id = db.Column(db.Integer, primary_key=True)
    session_log_id = db.Column(db.Integer, db.ForeignKey("session_logs.id"), nullable=False)
    photo_type = db.Column(db.String(30), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=_datetime.utcnow)


class Schedule(db.Model):
    __tablename__ = "schedules"

    id = db.Column(db.Integer, primary_key=True)
    school = db.Column(db.String(50), nullable=False)
    proposed_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(10))
    end_time = db.Column(db.String(10))
    session_type = db.Column(db.String(20), default="normal")
    topic = db.Column(db.String(200), nullable=True)
    proposed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    # status: 'pending' | 'accepted' | 'rejected' | 'cancelled'
    status = db.Column(db.String(20), default="pending")
    resolved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    created_at = db.Column(db.DateTime, default=_datetime.utcnow)

    proposer = db.relationship("User", foreign_keys=[proposed_by], backref="proposed_schedules")
    resolver = db.relationship("User", foreign_keys=[resolved_by])
