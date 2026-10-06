"""Database models.

Money is stored as integer cents everywhere to avoid floating point drift;
the API layer converts to and from decimal strings.
"""
from datetime import datetime, date

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint, CheckConstraint
from werkzeug.security import generate_password_hash, check_password_hash

from . import db

ROLES = ("admin", "bursar", "teacher", "parent")


def utcnow():
    return datetime.utcnow()


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


# --------------------------------------------------------------------------- #
# Users & people
# --------------------------------------------------------------------------- #
class User(UserMixin, TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    role = db.Column(db.String(16), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    last_login = db.Column(db.DateTime)

    __table_args__ = (CheckConstraint(f"role IN {ROLES}", name="ck_user_role"),)

    @property
    def is_active(self):
        return self.active

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    def to_dict(self):
        return {
            "id": self.id, "username": self.username, "full_name": self.full_name,
            "email": self.email, "role": self.role, "active": self.active,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "staff_id": self.staff.id if self.staff else None,
            "guardian_id": self.guardian.id if self.guardian else None,
        }


class Staff(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True)
    staff_no = db.Column(db.String(20), unique=True, nullable=False)
    first_name = db.Column(db.String(60), nullable=False)
    last_name = db.Column(db.String(60), nullable=False)
    gender = db.Column(db.String(10))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    position = db.Column(db.String(60), nullable=False, default="Teacher")
    department = db.Column(db.String(60))
    hire_date = db.Column(db.Date, default=date.today)
    salary_cents = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(16), default="active", nullable=False)  # active | on_leave | left

    user = db.relationship("User", backref=db.backref("staff", uselist=False))

    @property
    def name(self):
        return f"{self.first_name} {self.last_name}"


class Guardian(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(120))
    relationship = db.Column(db.String(30), default="Parent")
    address = db.Column(db.String(200))

    user = db.relationship("User", backref=db.backref("guardian", uselist=False))
    students = db.relationship("Student", back_populates="guardian")


class Student(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admission_no = db.Column(db.String(20), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(60), nullable=False)
    last_name = db.Column(db.String(60), nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("school_class.id"))
    guardian_id = db.Column(db.Integer, db.ForeignKey("guardian.id"))
    admission_date = db.Column(db.Date, default=date.today, nullable=False)
    # active | suspended | graduated | transferred | withdrawn
    status = db.Column(db.String(16), default="active", nullable=False)
    address = db.Column(db.String(200))
    medical_notes = db.Column(db.String(300))

    school_class = db.relationship("SchoolClass", back_populates="students")
    guardian = db.relationship("Guardian", back_populates="students")

    @property
    def name(self):
        return f"{self.first_name} {self.last_name}"


# --------------------------------------------------------------------------- #
# Academic structure
# --------------------------------------------------------------------------- #
class AcademicYear(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), unique=True, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_current = db.Column(db.Boolean, default=False, nullable=False)

    terms = db.relationship("Term", back_populates="year", order_by="Term.start_date",
                            cascade="all, delete-orphan")


class Term(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year_id = db.Column(db.Integer, db.ForeignKey("academic_year.id"), nullable=False)
    name = db.Column(db.String(30), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_current = db.Column(db.Boolean, default=False, nullable=False)

    year = db.relationship("AcademicYear", back_populates="terms")

    __table_args__ = (UniqueConstraint("year_id", "name"),)

    @property
    def label(self):
        return f"{self.name} {self.year.name}"


class SchoolClass(db.Model):
    __tablename__ = "school_class"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), unique=True, nullable=False)
    level = db.Column(db.Integer, nullable=False)
    stream = db.Column(db.String(10), nullable=False, default="A")
    capacity = db.Column(db.Integer, nullable=False, default=40)
    room = db.Column(db.String(30))
    class_teacher_id = db.Column(db.Integer, db.ForeignKey("staff.id"))

    class_teacher = db.relationship("Staff")
    students = db.relationship("Student", back_populates="school_class")
    subjects = db.relationship("ClassSubject", back_populates="school_class",
                               cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("level", "stream"),)

    def active_students(self):
        return [s for s in self.students if s.status == "active"]


class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(12), unique=True, nullable=False)
    name = db.Column(db.String(60), nullable=False)


class ClassSubject(db.Model):
    """Which subjects a class takes, and who teaches each."""
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("school_class.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("staff.id"))

    school_class = db.relationship("SchoolClass", back_populates="subjects")
    subject = db.relationship("Subject")
    teacher = db.relationship("Staff")

    __table_args__ = (UniqueConstraint("class_id", "subject_id"),)


class TimetableSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    class_subject_id = db.Column(db.Integer, db.ForeignKey("class_subject.id"), nullable=False)
    day = db.Column(db.Integer, nullable=False)  # 0 = Monday … 4 = Friday
    start_time = db.Column(db.String(5), nullable=False)  # "HH:MM"
    end_time = db.Column(db.String(5), nullable=False)
    room = db.Column(db.String(30))

    class_subject = db.relationship("ClassSubject",
                                    backref=db.backref("slots", cascade="all, delete-orphan"))

    __table_args__ = (CheckConstraint("day BETWEEN 0 AND 4", name="ck_slot_day"),)


# --------------------------------------------------------------------------- #
# Attendance & assessment
# --------------------------------------------------------------------------- #
ATTENDANCE_STATUSES = ("present", "absent", "late", "excused")


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("school_class.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False)
    remark = db.Column(db.String(120))
    recorded_by = db.Column(db.Integer, db.ForeignKey("user.id"))

    student = db.relationship("Student")

    __table_args__ = (
        UniqueConstraint("student_id", "date"),
        CheckConstraint(f"status IN {ATTENDANCE_STATUSES}", name="ck_att_status"),
    )


class Exam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    term_id = db.Column(db.Integer, db.ForeignKey("term.id"), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    weight = db.Column(db.Float, nullable=False)  # % contribution to the term result
    max_score = db.Column(db.Float, nullable=False, default=100)
    date = db.Column(db.Date)
    locked = db.Column(db.Boolean, default=False, nullable=False)

    term = db.relationship("Term")

    __table_args__ = (
        UniqueConstraint("term_id", "name"),
        CheckConstraint("weight > 0 AND weight <= 100", name="ck_exam_weight"),
        CheckConstraint("max_score > 0", name="ck_exam_max"),
    )


class Mark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exam.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False)
    score = db.Column(db.Float, nullable=False)
    entered_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    exam = db.relationship("Exam")
    student = db.relationship("Student")
    subject = db.relationship("Subject")

    __table_args__ = (UniqueConstraint("exam_id", "student_id", "subject_id"),)


class GradeBand(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    letter = db.Column(db.String(3), unique=True, nullable=False)
    min_score = db.Column(db.Float, nullable=False)
    points = db.Column(db.Float, nullable=False, default=0)
    remark = db.Column(db.String(30))


# --------------------------------------------------------------------------- #
# Finance
# --------------------------------------------------------------------------- #
class FeeItem(db.Model):
    """A charge for a term; class_id NULL means it applies to every class."""
    id = db.Column(db.Integer, primary_key=True)
    term_id = db.Column(db.Integer, db.ForeignKey("term.id"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("school_class.id"))
    name = db.Column(db.String(60), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    # Whether scholarships reduce this item (tuition yes, exam fees usually no).
    discountable = db.Column(db.Boolean, default=True, nullable=False)
    # Income account credited when this fee is invoiced.
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"))

    term = db.relationship("Term")
    school_class = db.relationship("SchoolClass")
    account = db.relationship("Account")

    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_fee_positive"),)


class Scholarship(TimestampMixin, db.Model):
    """Percentage discount applied to tuition-type fees when invoices are generated."""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    percent = db.Column(db.Float, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    student = db.relationship("Student", backref="scholarships")

    __table_args__ = (CheckConstraint("percent > 0 AND percent <= 100", name="ck_sch_pct"),)


class Invoice(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_no = db.Column(db.String(20), unique=True, nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey("term.id"), nullable=False)
    issue_date = db.Column(db.Date, default=date.today, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    void = db.Column(db.Boolean, default=False, nullable=False)
    void_reason = db.Column(db.String(200))
    voided_at = db.Column(db.Date)

    student = db.relationship("Student", backref="invoices")
    term = db.relationship("Term")
    lines = db.relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan")
    allocations = db.relationship("PaymentAllocation", back_populates="invoice")

    # One invoice per student per term keeps billing idempotent.
    __table_args__ = (UniqueConstraint("student_id", "term_id"),)

    @property
    def total_cents(self):
        return sum(line.amount_cents for line in self.lines)

    @property
    def paid_cents(self):
        return sum(a.amount_cents for a in self.allocations if not a.payment.void)

    @property
    def balance_cents(self):
        return 0 if self.void else self.total_cents - self.paid_cents

    @property
    def status(self):
        if self.void:
            return "void"
        if self.balance_cents <= 0:
            return "paid"
        if self.paid_cents > 0:
            return "partial" if self.due_date >= date.today() else "overdue"
        return "unpaid" if self.due_date >= date.today() else "overdue"


class InvoiceLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False)
    fee_item_id = db.Column(db.Integer, db.ForeignKey("fee_item.id"))
    description = db.Column(db.String(120), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)  # negative for discounts
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"))

    invoice = db.relationship("Invoice", back_populates="lines")


PAYMENT_METHODS = ("cash", "bank", "mobile", "card", "cheque")


class Payment(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    receipt_no = db.Column(db.String(20), unique=True, nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    method = db.Column(db.String(10), nullable=False)
    reference = db.Column(db.String(60))
    paid_on = db.Column(db.Date, nullable=False, default=date.today)
    received_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    void = db.Column(db.Boolean, default=False, nullable=False)
    void_reason = db.Column(db.String(200))
    voided_at = db.Column(db.Date)

    student = db.relationship("Student", backref="payments")
    receiver = db.relationship("User")
    allocations = db.relationship("PaymentAllocation", back_populates="payment",
                                  cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_payment_positive"),
        CheckConstraint(f"method IN {PAYMENT_METHODS}", name="ck_payment_method"),
    )

    @property
    def allocated_cents(self):
        return sum(a.amount_cents for a in self.allocations)

    @property
    def unallocated_cents(self):
        return 0 if self.void else self.amount_cents - self.allocated_cents


class PaymentAllocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)

    payment = db.relationship("Payment", back_populates="allocations")
    invoice = db.relationship("Invoice", back_populates="allocations")

    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_alloc_positive"),)


EXPENSE_STATUSES = ("pending", "approved", "rejected", "paid")


class Expense(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(40), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    vendor = db.Column(db.String(100))
    amount_cents = db.Column(db.Integer, nullable=False)
    expense_date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(10), nullable=False, default="pending")
    requested_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    approved_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    decision_note = db.Column(db.String(200))
    approved_at = db.Column(db.Date)
    paid_at = db.Column(db.Date)
    paid_from_account_id = db.Column(db.Integer, db.ForeignKey("account.id"))

    requester = db.relationship("User", foreign_keys=[requested_by])
    approver = db.relationship("User", foreign_keys=[approved_by])

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_expense_positive"),
        CheckConstraint(f"status IN {EXPENSE_STATUSES}", name="ck_expense_status"),
    )


# --------------------------------------------------------------------------- #
# Communication & audit
# --------------------------------------------------------------------------- #
class Announcement(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    audience = db.Column(db.String(10), nullable=False, default="all")  # all | staff | parents
    pinned = db.Column(db.Boolean, default=False, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))

    author = db.relationship("User")


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(40), nullable=False)
    entity = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.Integer)
    details = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    user = db.relationship("User")


class Counter(db.Model):
    """Sequential document numbers (admission, invoice, receipt) per prefix."""
    key = db.Column(db.String(20), primary_key=True)
    value = db.Column(db.Integer, nullable=False, default=0)


# --------------------------------------------------------------------------- #
# General ledger (double entry)
# --------------------------------------------------------------------------- #
ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")
CASH_FLOW_CLASSES = ("operating", "investing", "financing")


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    type = db.Column(db.String(10), nullable=False)
    # cash | receivable | payable | fixed_asset | contra_asset | contra_income | None
    subtype = db.Column(db.String(20))
    # Where movements against this account appear in the cash flow statement.
    cash_flow = db.Column(db.String(10), nullable=False, default="operating")
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    description = db.Column(db.String(200))

    __table_args__ = (
        CheckConstraint(f"type IN {ACCOUNT_TYPES}", name="ck_account_type"),
        CheckConstraint(f"cash_flow IN {CASH_FLOW_CLASSES}", name="ck_account_cf"),
    )

    @property
    def normal_debit(self):
        """Assets and expenses grow with debits; contra accounts flip their parent's side."""
        debit = self.type in ("asset", "expense")
        return not debit if self.subtype in ("contra_asset", "contra_income") else debit


class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_no = db.Column(db.String(20), unique=True, nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.String(200), nullable=False)
    reference = db.Column(db.String(60))
    # manual | invoice | charge | payment | expense_accrual | expense_payment | reversal
    source_type = db.Column(db.String(20), nullable=False, default="manual")
    source_id = db.Column(db.Integer)
    reversal_of_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"))
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    lines = db.relationship("JournalLine", back_populates="entry", cascade="all, delete-orphan")
    reversal_of = db.relationship("JournalEntry", remote_side=[id], backref="reversals")
    author = db.relationship("User")

    __table_args__ = (db.Index("ix_journal_source", "source_type", "source_id"),)

    @property
    def total_cents(self):
        return sum(l.debit_cents for l in self.lines)


class JournalLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False, index=True)
    debit_cents = db.Column(db.Integer, nullable=False, default=0)
    credit_cents = db.Column(db.Integer, nullable=False, default=0)
    memo = db.Column(db.String(120))
    # Receivable sub-ledger: which student a receivables line belongs to.
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), index=True)

    entry = db.relationship("JournalEntry", back_populates="lines")
    account = db.relationship("Account")

    __table_args__ = (
        CheckConstraint("debit_cents >= 0 AND credit_cents >= 0", name="ck_jl_nonneg"),
        CheckConstraint("(debit_cents = 0) <> (credit_cents = 0)", name="ck_jl_one_side"),
    )


class Setting(db.Model):
    key = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.String(200))
