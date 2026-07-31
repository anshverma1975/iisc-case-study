import os
import io
import csv
import uuid
import secrets
from datetime import date, datetime, timedelta
from functools import wraps
import base64

from flask import (
    Flask, render_template, redirect, url_for, request, flash, session, Response
)
from flask_migrate import Migrate
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.utils import secure_filename

from config import Config
from models import db, User, SessionLog, SessionPhoto, Schedule

migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "login"

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[-1].lower() in ALLOWED_IMAGE_EXT


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    def generate_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
        return session["csrf_token"]

    app.jinja_env.globals["csrf_token"] = generate_csrf_token

    register_routes(app)

    with app.app_context():
        db.create_all()
        seed_superadmin()

    return app


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def seed_superadmin():
    """Create a default superadmin account if one doesn't already exist."""
    existing = User.query.filter_by(role="superadmin").first()
    if existing:
        return
    admin = User(
        username="ansh",
        email="ansh@edutracker.com",
        name="Ansh",
        role="superadmin",
    )
    admin.set_password("admin123")
    db.session.add(admin)
    db.session.commit()


def role_required(*roles):
    """Restrict a route to one or more roles. Redirects unauthorized users."""

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login"))
            if current_user.role not in roles:
                flash("You are not authorized to view that page.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)

        return wrapped

    return decorator


def check_csrf():
    token = request.form.get("csrf_token")
    return token and token == session.get("csrf_token")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def school_summaries(app):
    """Return per-school summary: coordinator, sessions this week, avg engagement."""
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)

    summaries = []
    for school in app.config["SCHOOLS"]:
        coordinator = User.query.filter_by(role="staff", school=school).first()
        week_logs = SessionLog.query.filter(
            SessionLog.school == school,
            SessionLog.date >= start_of_week,
            SessionLog.date <= end_of_week,
        ).all()
        avg_engagement = (
            round(sum(l.engagement for l in week_logs) / len(week_logs))
            if week_logs
            else 0
        )
        summaries.append(
            {
                "school": school,
                "coordinator": coordinator.name if coordinator else "Unassigned",
                "sessions_this_week": len(week_logs),
                "avg_engagement": avg_engagement,
            }
        )
    return summaries


def save_session_photo(app, photo, school, day, upload_subdir="session_start"):
    """Validate + save an uploaded photo file. Returns the relative static path."""
    if not photo or photo.filename == "":
        return None, "Session start photo is required."
    if not allowed_image(photo.filename):
        return None, "Please upload a valid image file."

    upload_dir = os.path.join(app.config["UPLOAD_FOLDER"], upload_subdir)
    os.makedirs(upload_dir, exist_ok=True)

    ext = secure_filename(photo.filename).rsplit(".", 1)[-1].lower()
    filename = f"{school}_{day.isoformat()}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(upload_dir, filename)
    photo.save(filepath)
    return f"uploads/{upload_subdir}/{filename}", None


def safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_log_from_form(app, form, files, school, created_by, log=None, require_photo=True):
    """Create or update a SessionLog from posted form data. Returns (log, error)."""
    raw_date = form.get("date", "").strip()
    if raw_date:
        try:
            log_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            return None, "Please provide a valid date."
    else:
        log_date = log.date if log else date.today()

    start_time = form.get("start_time", "").strip()
    end_time = form.get("end_time", "").strip()
    if not start_time or not end_time:
        return None, "Start time and end time are required."

    headcount = safe_int(form.get("headcount"))
    engagement = safe_int(form.get("engagement"))
    if headcount is None or engagement is None:
        return None, "Headcount and engagement must be numbers."
    if headcount < 0:
        return None, "Headcount cannot be negative."
    if not (0 <= engagement <= 100):
        return None, "Engagement must be between 0 and 100."

    technical_issue = form.get("technical_issue") == "on"
    feedback_sheets_collected = form.get("feedback_sheets_collected") == "on"
    supervisor_present = form.get("supervisor_present") == "on"

    issue_description = None
    time_lost_minutes = None
    issue_resolved = False
    called_superadmin = False
    if technical_issue:
        issue_description = form.get("issue_description", "")
        issue_resolved = form.get("issue_resolved") == "on"
        called_superadmin = form.get("called_superadmin") == "on"
        time_lost_minutes = safe_int(form.get("time_lost_minutes"))

    if log is None:
        log = SessionLog(school=school, created_by=created_by)
        db.session.add(log)

    log.date = log_date
    log.start_time = start_time
    log.end_time = end_time
    log.headcount = headcount
    log.engagement = engagement
    log.session_type = form.get("session_type", "normal")
    log.notes = form.get("notes", "")
    log.feedback_sheets_collected = feedback_sheets_collected
    log.supervisor_present = supervisor_present
    log.technical_issue = technical_issue
    log.issue_description = issue_description
    log.time_lost_minutes = time_lost_minutes
    log.issue_resolved = issue_resolved
    log.called_superadmin = called_superadmin
    log.student_feedback_1 = form.get("student_feedback_1", "")
    log.student_feedback_2 = form.get("student_feedback_2", "")
    log.student_feedback_3 = form.get("student_feedback_3", "")

    db.session.flush()

    photo = files.get("session_start_photo")
    if photo and photo.filename:
        rel_path, err = save_session_photo(app, photo, school, log_date)
        if err:
            return None, err
        db.session.add(
            SessionPhoto(session_log_id=log.id, photo_type="session_start", file_path=rel_path)
        )
    elif require_photo and not SessionPhoto.query.filter_by(session_log_id=log.id).first():
        return None, "Session start photo is required."

    return log, None


def auto_reject_expired_proposals():
    """Mark pending proposals whose start time has already passed as rejected."""
    now = datetime.now()
    pending = Schedule.query.filter_by(status="pending").all()
    for p in pending:
        try:
            start_dt = datetime.combine(
                p.proposed_date, datetime.strptime(p.start_time, "%H:%M").time()
            )
        except (TypeError, ValueError):
            continue
        if start_dt < now:
            p.status = "rejected"
    db.session.commit()


def register_routes(app):
    @app.route("/")
    def landing():
        return render_template("landing.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            user = User.query.filter_by(username=username).first()
            if user is None or not user.check_password(password):
                flash("Invalid username or password.", "danger")
                return redirect(url_for("login"))

            login_user(user)
            return redirect(url_for("dashboard"))

        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("landing"))

    @app.route("/register/researcher", methods=["GET", "POST"])
    def register_researcher():
        if request.method == "POST":
            error = validate_registration(request.form, staff=False)
            if error:
                flash(error, "danger")
                return redirect(url_for("register_researcher"))

            user = User(
                username=request.form["username"].strip(),
                email=request.form["email"].strip(),
                name=request.form["name"].strip(),
                role="researcher",
            )
            user.set_password(request.form["password"])
            db.session.add(user)
            db.session.commit()
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))

        return render_template("register_researcher.html")

    @app.route("/register/staff", methods=["GET", "POST"])
    def register_staff():
        if request.method == "POST":
            error = validate_registration(request.form, staff=True)
            if error:
                flash(error, "danger")
                return redirect(url_for("register_staff"))

            user = User(
                username=request.form["username"].strip(),
                email=request.form["email"].strip(),
                name=request.form["name"].strip(),
                role="staff",
                school=request.form["school"],
            )
            user.set_password(request.form["password"])
            db.session.add(user)
            db.session.commit()
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))

        return render_template("register_staff.html", schools=app.config["SCHOOLS"])

    @app.route("/dashboard")
    @login_required
    def dashboard():
        if current_user.role == "staff":
            return redirect(url_for("dashboard_staff"))
        elif current_user.role == "researcher":
            return redirect(url_for("dashboard_researcher"))
        elif current_user.role == "superadmin":
            return redirect(url_for("dashboard_superadmin"))
        flash("Unknown role.", "danger")
        return redirect(url_for("landing"))

    # -----------------------------------------------------------------
    # Staff routes
    # -----------------------------------------------------------------

    @app.route("/staff/dashboard")
    @role_required("staff")
    def dashboard_staff():
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)

        upcoming = (
            Schedule.query.filter(
                Schedule.school == current_user.school,
                Schedule.status == "accepted",
                Schedule.proposed_date >= today,
            )
            .order_by(Schedule.proposed_date.asc())
            .first()
        )

        schedule_today = Schedule.query.filter_by(
            school=current_user.school, status="accepted", proposed_date=today
        ).first()
        if upcoming:
            upcoming_session = {
                "date": upcoming.proposed_date.strftime("%a, %d %b"),
                "time": f"{upcoming.start_time}-{upcoming.end_time}",
                "topic": upcoming.topic or "No topic specified",
                "experiment": upcoming.session_type == "experiment",
            }
        else:
            upcoming_session = None

        week_logs = SessionLog.query.filter(
            SessionLog.school == current_user.school,
            SessionLog.date >= start_of_week,
            SessionLog.date <= end_of_week,
        ).all()

        sessions_this_week = len(week_logs)
        avg_engagement = (
            round(sum(l.engagement for l in week_logs) / len(week_logs))
            if week_logs
            else 0
        )
        tech_issues = sum(1 for l in week_logs if l.technical_issue)

        sent_pending = Schedule.query.filter_by(
            proposed_by=current_user.id, status="pending"
        ).count()

        incoming_pending = (
            Schedule.query.join(User, Schedule.proposed_by == User.id)
            .filter(
                Schedule.school == current_user.school,
                Schedule.status == "pending",
                User.role == "superadmin",
            )
            .count()
        )

        pending_proposals = sent_pending + incoming_pending

        stats = {
            "sessions_this_week": sessions_this_week,
            "avg_engagement": avg_engagement,
            "tech_issues": tech_issues,
            "pending_proposals": pending_proposals,
        }

        recent_logs = (
            SessionLog.query.filter_by(school=current_user.school)
            .order_by(SessionLog.date.desc())
            .limit(5)
            .all()
        )

        already_logged_today = (
            SessionLog.query.filter_by(created_by=current_user.id, date=today).first()
            is not None
        )

        return render_template(
            "staff_dashboard.html",
            name=current_user.name,
            upcoming_session=upcoming_session,
            stats=stats,
            recent_logs=recent_logs,
            already_logged_today=already_logged_today,
            schedule_today=schedule_today is not None,
        )

    @app.route("/staff/sessions")
    @role_required("staff")
    def staff_sessions():
        """Manage Sessions: everything upcoming (accepted schedules) and
        everything already logged, for the staff member's school."""
        today = date.today()
        auto_reject_expired_proposals()

        upcoming = (
            Schedule.query.filter(
                Schedule.school == current_user.school,
                Schedule.status == "accepted",
                Schedule.proposed_date >= today,
            )
            .order_by(Schedule.proposed_date.asc())
            .all()
        )

        # Which upcoming sessions already have a log (in case a schedule was
        # accepted for today or a past-dated edge case and already logged).
        logged_dates = {
            l.date
            for l in SessionLog.query.filter_by(school=current_user.school).all()
        }

        upcoming_sessions = []
        for s in upcoming:
            upcoming_sessions.append(
                {
                    "id": s.id,
                    "date": s.proposed_date,
                    "date_display": s.proposed_date.strftime("%a, %d %b %Y"),
                    "time": f"{s.start_time} - {s.end_time}",
                    "topic": s.topic,
                    "experiment": s.session_type == "experiment",
                    "is_today": s.proposed_date == today,
                    "already_logged": s.proposed_date in logged_dates,
                }
            )

        completed_logs = (
            SessionLog.query.filter_by(school=current_user.school)
            .order_by(SessionLog.date.desc())
            .all()
        )

        return render_template(
            "staff_sessions.html",
            upcoming_sessions=upcoming_sessions,
            completed_logs=completed_logs,
        )

    @app.route("/staff/session/today")
    @role_required("staff")
    def staff_session_today():
        today = date.today()
        schedule_today = Schedule.query.filter_by(
            school=current_user.school, status="accepted", proposed_date=today
        ).first()
        return render_template("staff_session_today.html", schedule_today=schedule_today)

    @app.route("/staff/session/create", methods=["POST"])
    @role_required("staff")
    def staff_session_create():
        if not check_csrf():
            flash("Invalid or expired form submission. Please try again.", "danger")
            return redirect(url_for("staff_session_today"))

        today = date.today()

        existing = SessionLog.query.filter_by(
            created_by=current_user.id, date=today
        ).first()
        if existing:
            flash("You have already logged a session for today.", "warning")
            return redirect(url_for("staff_logs"))

        photo = request.files.get("session_start_photo")
        if not photo or photo.filename == "":
            flash("Session start photo is required.", "danger")
            return redirect(url_for("staff_session_today"))

        if not allowed_image(photo.filename):
            flash("Please upload a valid image file.", "danger")
            return redirect(url_for("staff_session_today"))

        start_time = request.form.get("start_time", "").strip()
        end_time = request.form.get("end_time", "").strip()
        if not start_time or not end_time:
            flash("Start time and end time are required.", "danger")
            return redirect(url_for("staff_session_today"))

        # A session already in progress (resumed after reload) is allowed to
        # complete even if today's schedule was later removed/changed.
        is_resuming = request.form.get("resuming") == "1"
        if not is_resuming and current_user.role != "superadmin":
            schedule_today = Schedule.query.filter_by(
                school=current_user.school, status="accepted", proposed_date=today
            ).first()
            if not schedule_today:
                flash("No session scheduled for today.", "danger")
                return redirect(url_for("staff_session_today"))

        try:
            headcount = int(request.form.get("headcount", 0))
            engagement = int(request.form.get("engagement", 0))
        except ValueError:
            flash("Headcount and engagement must be numbers.", "danger")
            return redirect(url_for("staff_session_today"))

        if headcount < 0:
            flash("Headcount cannot be negative.", "danger")
            return redirect(url_for("staff_session_today"))

        if not (0 <= engagement <= 100):
            flash("Engagement must be between 0 and 100.", "danger")
            return redirect(url_for("staff_session_today"))

        technical_issue = request.form.get("technical_issue") == "on"
        feedback_sheets_collected = request.form.get("feedback_sheets_collected") == "on"
        supervisor_present = request.form.get("supervisor_present") == "on"

        time_lost_minutes = None
        issue_resolved = False
        called_superadmin = False
        issue_description = None

        if technical_issue:
            issue_description = request.form.get("issue_description", "")
            issue_resolved = request.form.get("issue_resolved") == "on"
            called_superadmin = request.form.get("called_superadmin") == "on"
            raw_minutes = request.form.get("time_lost_minutes")
            if raw_minutes:
                try:
                    time_lost_minutes = int(raw_minutes)
                except ValueError:
                    time_lost_minutes = None

        log = SessionLog(
            school=current_user.school,
            date=today,
            start_time=start_time,
            end_time=end_time,
            headcount=headcount,
            engagement=engagement,
            session_type=request.form.get("session_type", "normal"),
            notes=request.form.get("notes", ""),
            feedback_sheets_collected=feedback_sheets_collected,
            supervisor_present=supervisor_present,
            technical_issue=technical_issue,
            issue_description=issue_description,
            time_lost_minutes=time_lost_minutes,
            issue_resolved=issue_resolved,
            called_superadmin=called_superadmin,
            student_feedback_1=request.form.get("student_feedback_1", ""),
            student_feedback_2=request.form.get("student_feedback_2", ""),
            student_feedback_3=request.form.get("student_feedback_3", ""),
            created_by=current_user.id,
        )
        db.session.add(log)

        # Convert photo to base64 and store it directly on the log
        import base64
        photo_data = photo.read()
        base64_image = base64.b64encode(photo_data).decode('utf-8')
        mime_type = photo.content_type or 'image/jpeg'
        data_url = f"data:{mime_type};base64,{base64_image}"
        log.session_start_photo_data = data_url

        db.session.commit()

        flash("Session log submitted successfully.", "success")
        return redirect(url_for("staff_logs"))

    @app.route("/staff/session/<int:session_id>")
    @role_required("staff")
    def staff_session_detail(session_id):
        log = SessionLog.query.get_or_404(session_id)
        return render_template("staff_session_detail.html", session=log)

    @app.route("/staff/logs")
    @role_required("staff")
    def staff_logs():
        logs = (
            SessionLog.query.filter_by(school=current_user.school)
            .order_by(SessionLog.date.desc())
            .all()
        )
        return render_template("staff_logs.html", logs=logs)

    @app.route("/staff/schedule")
    @role_required("staff")
    def staff_schedule():
        auto_reject_expired_proposals()

        proposals = (
            Schedule.query.filter_by(proposed_by=current_user.id)
            .order_by(Schedule.proposed_date.desc())
            .all()
        )
        now = datetime.now()
        sent_proposals = []
        for p in proposals:
            start_dt = datetime.combine(
                p.proposed_date, datetime.strptime(p.start_time, "%H:%M").time()
            )
            can_cancel = p.status == "pending" and (start_dt - now) > timedelta(hours=3)
            sent_proposals.append(
                {
                    "id": p.id,
                    "date": p.proposed_date.strftime("%a, %d %b"),
                    "time": f"{p.start_time}-{p.end_time}",
                    "status": p.status,
                    "experiment": p.session_type == "experiment",
                    "can_cancel": can_cancel,
                }
            )

        # Requests initiated by a supervisor (superadmin) for this staff's school,
        # awaiting the staff's response.
        incoming = (
            Schedule.query.join(User, Schedule.proposed_by == User.id)
            .filter(
                Schedule.school == current_user.school,
                Schedule.status == "pending",
                User.role == "superadmin",
            )
            .order_by(Schedule.proposed_date.asc())
            .all()
        )
        incoming_requests = []
        for p in incoming:
            incoming_requests.append(
                {
                    "id": p.id,
                    "date": p.proposed_date.strftime("%a, %d %b"),
                    "time": f"{p.start_time}-{p.end_time}",
                    "topic": p.topic,
                    "experiment": p.session_type == "experiment",
                    "proposer": p.proposer.name,
                }
            )

        # History of supervisor requests this staff member has already
        # accepted or rejected, so they don't just disappear.
        incoming_history = (
            Schedule.query.join(User, Schedule.proposed_by == User.id)
            .filter(
                Schedule.school == current_user.school,
                Schedule.status.in_(["accepted", "rejected"]),
                User.role == "superadmin",
            )
            .order_by(Schedule.proposed_date.desc())
            .limit(25)
            .all()
        )
        incoming_history_list = []
        for p in incoming_history:
            incoming_history_list.append(
                {
                    "id": p.id,
                    "date": p.proposed_date.strftime("%a, %d %b"),
                    "time": f"{p.start_time}-{p.end_time}",
                    "topic": p.topic,
                    "experiment": p.session_type == "experiment",
                    "proposer": p.proposer.name,
                    "status": p.status,
                }
            )

        return render_template(
            "staff_schedule.html",
            sent_proposals=sent_proposals,
            incoming_requests=incoming_requests,
            incoming_history=incoming_history_list,
        )

    @app.route("/staff/schedule/propose", methods=["POST"])
    @role_required("staff")
    def staff_schedule_propose():
        raw_date = request.form.get("date", "")
        start_time = request.form.get("start_time", "").strip()
        end_time = request.form.get("end_time", "").strip()
        is_experiment = request.form.get("is_experiment") == "on"
        topic = request.form.get("topic", "").strip() or None

        try:
            proposed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            flash("Please provide a valid date.", "danger")
            return redirect(url_for("staff_schedule"))

        if not start_time or not end_time:
            flash("Start time and end time are required.", "danger")
            return redirect(url_for("staff_schedule"))

        today = date.today()
        if not (today + timedelta(days=1) <= proposed_date <= today + timedelta(days=7)):
            flash("Session date must be between 1 and 7 days from today.", "danger")
            return redirect(url_for("staff_schedule"))

        if end_time <= start_time:
            flash("End time must be after start time.", "danger")
            return redirect(url_for("staff_schedule"))

        overlapping = Schedule.query.filter(
            Schedule.school == current_user.school,
            Schedule.proposed_date == proposed_date,
            Schedule.status.in_(["pending", "accepted"]),
            Schedule.start_time < end_time,
            Schedule.end_time > start_time,
        ).first()
        if overlapping:
            flash("A proposal already exists for an overlapping time on that date.", "danger")
            return redirect(url_for("staff_schedule"))

        proposal = Schedule(
            school=current_user.school,
            proposed_date=proposed_date,
            start_time=start_time,
            end_time=end_time,
            session_type="experiment" if is_experiment else "normal",
            topic=topic,
            proposed_by=current_user.id,
            status="pending",
        )
        db.session.add(proposal)
        db.session.commit()
        flash("Session proposal sent for approval.", "success")
        return redirect(url_for("staff_schedule"))

    @app.route("/staff/schedule/<int:schedule_id>/cancel", methods=["POST"])
    @role_required("staff")
    def staff_schedule_cancel(schedule_id):
        proposal = Schedule.query.get_or_404(schedule_id)
        if proposal.proposed_by != current_user.id:
            flash("You are not authorized to cancel that proposal.", "danger")
            return redirect(url_for("staff_schedule"))

        if proposal.status != "pending":
            flash("Only pending proposals can be cancelled.", "danger")
            return redirect(url_for("staff_schedule"))

        start_dt = datetime.combine(
            proposal.proposed_date, datetime.strptime(proposal.start_time, "%H:%M").time()
        )
        if (start_dt - datetime.now()) <= timedelta(hours=3):
            flash("Proposals can only be cancelled more than 3 hours before the start time.", "danger")
            return redirect(url_for("staff_schedule"))

        proposal.status = "cancelled"
        db.session.commit()
        flash("Proposal cancelled. You can now propose a new time.", "success")
        return redirect(url_for("staff_schedule"))

    @app.route("/staff/schedule/<int:schedule_id>/accept", methods=["POST"])
    @role_required("staff")
    def staff_schedule_accept(schedule_id):
        if not check_csrf():
            flash("Invalid or expired form submission. Please try again.", "danger")
            return redirect(url_for("staff_schedule"))

        proposal = Schedule.query.get_or_404(schedule_id)
        if proposal.school != current_user.school or proposal.proposed_by == current_user.id:
            flash("You are not authorized to respond to that proposal.", "danger")
            return redirect(url_for("staff_schedule"))

        if proposal.status != "pending":
            flash("This proposal has already been resolved.", "warning")
            return redirect(url_for("staff_schedule"))

        proposal.status = "accepted"
        proposal.resolved_by = current_user.id
        db.session.commit()
        flash("Session request accepted.", "success")
        return redirect(url_for("staff_schedule"))

    @app.route("/staff/schedule/<int:schedule_id>/reject", methods=["POST"])
    @role_required("staff")
    def staff_schedule_reject(schedule_id):
        if not check_csrf():
            flash("Invalid or expired form submission. Please try again.", "danger")
            return redirect(url_for("staff_schedule"))

        proposal = Schedule.query.get_or_404(schedule_id)
        if proposal.school != current_user.school or proposal.proposed_by == current_user.id:
            flash("You are not authorized to respond to that proposal.", "danger")
            return redirect(url_for("staff_schedule"))

        if proposal.status != "pending":
            flash("This proposal has already been resolved.", "warning")
            return redirect(url_for("staff_schedule"))

        proposal.status = "rejected"
        proposal.resolved_by = current_user.id
        db.session.commit()
        flash("Session request rejected.", "success")
        return redirect(url_for("staff_schedule"))

    @app.route("/staff/profile")
    @role_required("staff")
    def staff_profile():
        profile = {
            "name": current_user.name,
            "school": current_user.school,
            "email": current_user.email,
            "contact": "+91 90000 00000",
            "total_sessions": 24,
            "avg_engagement": 76,
            "last_session": "28 Jul 2026",
        }
        return render_template("staff_profile.html", profile=profile)

    # -----------------------------------------------------------------
    # Researcher routes (read-only across all schools)
    # -----------------------------------------------------------------

    @app.route("/researcher/dashboard")
    @role_required("researcher")
    def dashboard_researcher():
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)

        week_logs = SessionLog.query.filter(
            SessionLog.date >= start_of_week, SessionLog.date <= end_of_week
        ).all()

        stats = {
            "sessions_this_week": len(week_logs),
            "avg_engagement": (
                round(sum(l.engagement for l in week_logs) / len(week_logs))
                if week_logs
                else 0
            ),
            "tech_issues": sum(1 for l in week_logs if l.technical_issue),
            "pending_proposals": Schedule.query.filter_by(status="pending").count(),
        }

        recent_logs = SessionLog.query.order_by(SessionLog.date.desc()).limit(10).all()

        return render_template("researcher_dashboard.html", stats=stats, recent_logs=recent_logs)

    @app.route("/researcher/sessions")
    @role_required("researcher")
    def researcher_sessions():
        query = SessionLog.query

        school = request.args.get("school", "").strip()
        start_date = request.args.get("start_date", "").strip()
        end_date = request.args.get("end_date", "").strip()

        if school:
            query = query.filter(SessionLog.school == school)
        if start_date:
            try:
                query = query.filter(SessionLog.date >= datetime.strptime(start_date, "%Y-%m-%d").date())
            except ValueError:
                pass
        if end_date:
            try:
                query = query.filter(SessionLog.date <= datetime.strptime(end_date, "%Y-%m-%d").date())
            except ValueError:
                pass

        logs = query.order_by(SessionLog.date.desc()).all()
        return render_template(
            "researcher_sessions.html",
            logs=logs,
            schools=app.config["SCHOOLS"],
            selected_school=school,
            start_date=start_date,
            end_date=end_date,
        )

    @app.route("/researcher/session/<int:session_id>")
    @role_required("researcher")
    def researcher_session_detail(session_id):
        log = SessionLog.query.get_or_404(session_id)
        return render_template("researcher_session_detail.html", session=log)

    @app.route("/researcher/schedule")
    @role_required("researcher")
    def researcher_schedule():
        auto_reject_expired_proposals()
        proposals = (
            Schedule.query.filter_by(status="pending")
            .order_by(Schedule.proposed_date.asc())
            .all()
        )
        return render_template("researcher_schedule.html", proposals=proposals)

    @app.route("/researcher/staff")
    @role_required("researcher")
    def researcher_staff():
        cutoff = date.today() - timedelta(days=30)
        staff_users = User.query.filter_by(role="staff").order_by(User.school.asc()).all()
        rows = []
        for u in staff_users:
            active = SessionLog.query.filter(
                SessionLog.created_by == u.id, SessionLog.date >= cutoff
            ).first() is not None
            rows.append({"user": u, "active": active})
        return render_template("researcher_staff.html", rows=rows)

    @app.route("/researcher/schools")
    @role_required("researcher")
    def researcher_schools():
        return render_template("researcher_schools.html", summaries=school_summaries(app))

    @app.route("/researcher/export")
    @role_required("researcher")
    def researcher_export():
        return render_template("researcher_export.html", schools=app.config["SCHOOLS"])

    @app.route("/researcher/profile")
    @role_required("researcher")
    def researcher_profile():
        return render_template("researcher_profile.html")

    # -----------------------------------------------------------------
    # Superadmin routes
    # -----------------------------------------------------------------

    @app.route("/superadmin/dashboard")
    @role_required("superadmin")
    def dashboard_superadmin():
        auto_reject_expired_proposals()
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)

        week_logs = SessionLog.query.filter(
            SessionLog.date >= start_of_week, SessionLog.date <= end_of_week
        ).all()

        stats = {
            "sessions_this_week": len(week_logs),
            "avg_engagement": (
                round(sum(l.engagement for l in week_logs) / len(week_logs))
                if week_logs
                else 0
            ),
            "tech_issues": sum(1 for l in week_logs if l.technical_issue),
            "pending_proposals": Schedule.query.filter_by(status="pending").count(),
        }

        recent_logs = SessionLog.query.order_by(SessionLog.date.desc()).limit(10).all()

        return render_template("dashboard_superadmin.html", stats=stats, recent_logs=recent_logs)

    @app.route("/superadmin/sessions")
    @role_required("superadmin")
    def superadmin_sessions():
        query = SessionLog.query
        school = request.args.get("school", "").strip()
        start_date = request.args.get("start_date", "").strip()
        end_date = request.args.get("end_date", "").strip()

        if school:
            query = query.filter(SessionLog.school == school)
        if start_date:
            try:
                query = query.filter(SessionLog.date >= datetime.strptime(start_date, "%Y-%m-%d").date())
            except ValueError:
                pass
        if end_date:
            try:
                query = query.filter(SessionLog.date <= datetime.strptime(end_date, "%Y-%m-%d").date())
            except ValueError:
                pass

        logs = query.order_by(SessionLog.date.desc()).all()
        return render_template(
            "superadmin_sessions.html",
            logs=logs,
            schools=app.config["SCHOOLS"],
            selected_school=school,
            start_date=start_date,
            end_date=end_date,
        )

    @app.route("/superadmin/sessions/manage")
    @role_required("superadmin")
    def superadmin_manage_sessions():
        """Manage Sessions: upcoming accepted sessions + completed logs across
        all schools, filterable by school."""
        auto_reject_expired_proposals()
        today = date.today()
        school = request.args.get("school", "").strip()

        upcoming_q = Schedule.query.filter(
            Schedule.status == "accepted", Schedule.proposed_date >= today
        )
        if school:
            upcoming_q = upcoming_q.filter(Schedule.school == school)
        upcoming = upcoming_q.order_by(Schedule.proposed_date.asc()).all()

        logged_pairs = {
            (l.school, l.date)
            for l in SessionLog.query.all()
        }

        upcoming_sessions = []
        for s in upcoming:
            upcoming_sessions.append(
                {
                    "id": s.id,
                    "school": s.school,
                    "date": s.proposed_date,
                    "date_display": s.proposed_date.strftime("%a, %d %b %Y"),
                    "time": f"{s.start_time} - {s.end_time}",
                    "topic": s.topic,
                    "experiment": s.session_type == "experiment",
                    "is_today": s.proposed_date == today,
                    "already_logged": (s.school, s.proposed_date) in logged_pairs,
                }
            )

        logs_q = SessionLog.query
        if school:
            logs_q = logs_q.filter(SessionLog.school == school)
        completed_logs = logs_q.order_by(SessionLog.date.desc()).limit(50).all()

        return render_template(
            "superadmin_manage_sessions.html",
            upcoming_sessions=upcoming_sessions,
            completed_logs=completed_logs,
            schools=app.config["SCHOOLS"],
            selected_school=school,
        )

    @app.route("/superadmin/session/<int:session_id>")
    @role_required("superadmin")
    def superadmin_session_detail(session_id):
        log = SessionLog.query.get_or_404(session_id)
        return render_template("staff_session_detail.html", session=log, editable=True)

    @app.route("/superadmin/session/new")
    @role_required("superadmin")
    def superadmin_session_new():
        return render_template(
            "superadmin_session_form.html", schools=app.config["SCHOOLS"], log=None
        )

    @app.route("/superadmin/session/create", methods=["POST"])
    @role_required("superadmin")
    def superadmin_session_create():
        if not check_csrf():
            flash("Invalid or expired form submission. Please try again.", "danger")
            return redirect(url_for("superadmin_session_new"))

        school = request.form.get("school", "").strip()
        if school not in app.config["SCHOOLS"]:
            flash("Please select a valid school.", "danger")
            return redirect(url_for("superadmin_session_new"))

        log, error = build_log_from_form(
            app, request.form, request.files, school, current_user.id
        )
        if error:
            db.session.rollback()
            flash(error, "danger")
            return redirect(url_for("superadmin_session_new"))

        db.session.commit()
        flash("Session log created successfully.", "success")
        return redirect(url_for("superadmin_sessions"))

    @app.route("/superadmin/session/<int:session_id>/edit")
    @role_required("superadmin")
    def superadmin_session_edit(session_id):
        log = SessionLog.query.get_or_404(session_id)
        return render_template(
            "superadmin_session_form.html", schools=app.config["SCHOOLS"], log=log
        )

    @app.route("/superadmin/session/<int:session_id>/update", methods=["POST"])
    @role_required("superadmin")
    def superadmin_session_update(session_id):
        if not check_csrf():
            flash("Invalid or expired form submission. Please try again.", "danger")
            return redirect(url_for("superadmin_session_edit", session_id=session_id))

        log = SessionLog.query.get_or_404(session_id)
        school = request.form.get("school", "").strip() or log.school

        updated_log, error = build_log_from_form(
            app, request.form, request.files, school, log.created_by, log=log,
            require_photo=False,
        )
        if error:
            db.session.rollback()
            flash(error, "danger")
            return redirect(url_for("superadmin_session_edit", session_id=session_id))

        db.session.commit()
        flash("Session log updated successfully.", "success")
        return redirect(url_for("superadmin_sessions"))

    @app.route("/superadmin/schedule")
    @role_required("superadmin")
    def superadmin_schedule():
        auto_reject_expired_proposals()

        school = request.args.get("school", "").strip()

        # Pending proposals sent in by staff, awaiting superadmin response.
        proposals_q = (
            Schedule.query.join(User, Schedule.proposed_by == User.id)
            .filter(Schedule.status == "pending", User.role != "superadmin")
        )
        if school:
            proposals_q = proposals_q.filter(Schedule.school == school)
        proposals = proposals_q.order_by(Schedule.proposed_date.asc()).all()

        # Full history of staff proposals that have already been resolved
        # (accepted/rejected), so they remain visible instead of vanishing.
        history_q = (
            Schedule.query.join(User, Schedule.proposed_by == User.id)
            .filter(
                Schedule.status.in_(["accepted", "rejected", "cancelled"]),
                User.role != "superadmin",
            )
        )
        if school:
            history_q = history_q.filter(Schedule.school == school)
        staff_history = history_q.order_by(Schedule.proposed_date.desc()).limit(50).all()

        # Sessions the superadmin has proposed to a school's staff, with status.
        own_proposals_q = Schedule.query.filter_by(proposed_by=current_user.id)
        if school:
            own_proposals_q = own_proposals_q.filter(Schedule.school == school)
        own_proposals = own_proposals_q.order_by(Schedule.proposed_date.desc()).all()

        return render_template(
            "superadmin_schedule.html",
            proposals=proposals,
            staff_history=staff_history,
            own_proposals=own_proposals,
            schools=app.config["SCHOOLS"],
            selected_school=school,
        )

    @app.route("/superadmin/schedule/propose", methods=["POST"])
    @role_required("superadmin")
    def superadmin_schedule_propose():
        if not check_csrf():
            flash("Invalid or expired form submission. Please try again.", "danger")
            return redirect(url_for("superadmin_schedule"))

        school = request.form.get("school", "").strip()
        if school not in app.config["SCHOOLS"]:
            flash("Please select a valid school.", "danger")
            return redirect(url_for("superadmin_schedule"))

        raw_date = request.form.get("date", "")
        start_time = request.form.get("start_time", "").strip()
        end_time = request.form.get("end_time", "").strip()
        is_experiment = request.form.get("is_experiment") == "on"
        topic = request.form.get("topic", "").strip() or None

        try:
            proposed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            flash("Please provide a valid date.", "danger")
            return redirect(url_for("superadmin_schedule"))

        if not start_time or not end_time:
            flash("Start time and end time are required.", "danger")
            return redirect(url_for("superadmin_schedule"))

        if end_time <= start_time:
            flash("End time must be after start time.", "danger")
            return redirect(url_for("superadmin_schedule"))

        overlapping = Schedule.query.filter(
            Schedule.school == school,
            Schedule.proposed_date == proposed_date,
            Schedule.status.in_(["pending", "accepted"]),
            Schedule.start_time < end_time,
            Schedule.end_time > start_time,
        ).first()
        if overlapping:
            flash("A proposal already exists for an overlapping time on that date.", "danger")
            return redirect(url_for("superadmin_schedule"))

        proposal = Schedule(
            school=school,
            proposed_date=proposed_date,
            start_time=start_time,
            end_time=end_time,
            session_type="experiment" if is_experiment else "normal",
            topic=topic,
            proposed_by=current_user.id,
            status="pending",
        )
        db.session.add(proposal)
        db.session.commit()
        flash("Session proposal sent to school staff.", "success")
        return redirect(url_for("superadmin_schedule"))

    @app.route("/superadmin/schedule/<int:schedule_id>/accept", methods=["POST"])
    @role_required("superadmin")
    def superadmin_schedule_accept(schedule_id):
        proposal = Schedule.query.get_or_404(schedule_id)
        if proposal.proposed_by == current_user.id:
            flash("You cannot accept your own proposal.", "danger")
            return redirect(url_for("superadmin_schedule"))
        if proposal.status != "pending":
            flash("This proposal has already been resolved.", "warning")
            return redirect(url_for("superadmin_schedule"))
        proposal.status = "accepted"
        proposal.resolved_by = current_user.id
        db.session.commit()
        flash("Proposal accepted.", "success")
        return redirect(url_for("superadmin_schedule"))

    @app.route("/superadmin/schedule/<int:schedule_id>/reject", methods=["POST"])
    @role_required("superadmin")
    def superadmin_schedule_reject(schedule_id):
        proposal = Schedule.query.get_or_404(schedule_id)
        if proposal.proposed_by == current_user.id:
            flash("You cannot reject your own proposal.", "danger")
            return redirect(url_for("superadmin_schedule"))
        if proposal.status != "pending":
            flash("This proposal has already been resolved.", "warning")
            return redirect(url_for("superadmin_schedule"))
        proposal.status = "rejected"
        proposal.resolved_by = current_user.id
        db.session.commit()
        flash("Proposal rejected.", "success")
        return redirect(url_for("superadmin_schedule"))

    @app.route("/superadmin/users")
    @role_required("superadmin")
    def superadmin_users():
        users = User.query.order_by(User.role.asc(), User.name.asc()).all()
        return render_template("superadmin_users.html", users=users, schools=app.config["SCHOOLS"])

    @app.route("/superadmin/users/add", methods=["POST"])
    @role_required("superadmin")
    def superadmin_users_add():
        if not check_csrf():
            flash("Invalid or expired form submission. Please try again.", "danger")
            return redirect(url_for("superadmin_users"))

        role = request.form.get("role", "").strip()
        if role not in ("staff", "researcher"):
            flash("Please select a valid role.", "danger")
            return redirect(url_for("superadmin_users"))

        error = validate_registration(request.form, staff=(role == "staff"))
        if error:
            flash(error, "danger")
            return redirect(url_for("superadmin_users"))

        user = User(
            username=request.form["username"].strip(),
            email=request.form["email"].strip(),
            name=request.form["name"].strip(),
            role=role,
            school=request.form.get("school") if role == "staff" else None,
        )
        user.set_password(request.form["password"])
        db.session.add(user)
        db.session.commit()
        flash("User created successfully.", "success")
        return redirect(url_for("superadmin_users"))

    @app.route("/superadmin/users/<int:user_id>/delete", methods=["POST"])
    @role_required("superadmin")
    def superadmin_users_delete(user_id):
        if user_id == current_user.id:
            flash("You cannot delete your own account.", "danger")
            return redirect(url_for("superadmin_users"))

        user = User.query.get_or_404(user_id)
        db.session.delete(user)
        db.session.commit()
        flash("User deleted.", "success")
        return redirect(url_for("superadmin_users"))

    @app.route("/superadmin/export")
    @role_required("superadmin")
    def superadmin_export():
        return render_template("superadmin_export.html", schools=app.config["SCHOOLS"])

    @app.route("/superadmin/export/download")
    @role_required("superadmin")
    def superadmin_export_download():
        query = SessionLog.query
        school = request.args.get("school", "").strip()
        start_date = request.args.get("start_date", "").strip()
        end_date = request.args.get("end_date", "").strip()

        if school:
            query = query.filter(SessionLog.school == school)
        if start_date:
            try:
                query = query.filter(SessionLog.date >= datetime.strptime(start_date, "%Y-%m-%d").date())
            except ValueError:
                pass
        if end_date:
            try:
                query = query.filter(SessionLog.date <= datetime.strptime(end_date, "%Y-%m-%d").date())
            except ValueError:
                pass

        logs = query.order_by(SessionLog.date.desc()).all()

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "Date", "School", "Start Time", "End Time", "Headcount", "Engagement",
            "Session Type", "Supervisor Present", "Technical Issue", "Feedback Collected", "Notes",
        ])
        for log in logs:
            writer.writerow([
                log.date.strftime("%Y-%m-%d"), log.school, log.start_time, log.end_time,
                log.headcount, log.engagement, log.session_type,
                "Yes" if log.supervisor_present else "No",
                "Yes" if log.technical_issue else "No",
                "Yes" if log.feedback_sheets_collected else "No",
                (log.notes or "").replace("\n", " "),
            ])

        response = Response(buffer.getvalue(), mimetype="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=session_logs.csv"
        return response

    @app.route("/superadmin/profile")
    @role_required("superadmin")
    def superadmin_profile():
        return render_template("superadmin_profile.html")


def validate_registration(form, staff):
    """Shared validation for both registration forms. Returns an error
    message string, or None if valid."""
    username = form.get("username", "").strip()
    email = form.get("email", "").strip()
    name = form.get("name", "").strip()
    password = form.get("password", "")
    confirm = form.get("confirm_password", "")

    if not username or not email or not name or not password:
        return "All fields are required."

    if confirm and password != confirm:
        return "Passwords do not match."

    if staff and not form.get("school"):
        return "Please select a school."

    if User.query.filter_by(username=username).first():
        return "That username is already taken."

    if User.query.filter_by(email=email).first():
        return "That email is already registered."

    return None


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
