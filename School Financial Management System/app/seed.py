"""Demo data and CLI commands.

    flask --app run seed            # wipe & load demo data
    flask --app run create-admin    # create an administrator interactively
"""
import random
from datetime import date, timedelta

import click

from . import db
from .models import (AcademicYear, Announcement, Attendance, ClassSubject, Exam, Expense, FeeItem,
                     GradeBand, Guardian, Mark, SchoolClass, Scholarship, Staff, Student, Subject,
                     Term, TimetableSlot, User)
from .services import finance, ledger
from .utils import next_number

DEMO_ACCOUNTS = {
    "admin": ("Admin@2026", "admin", "Grace Ndlovu"),
    "bursar": ("Bursar@2026", "bursar", "Peter Okafor"),
    "teacher": ("Teacher@2026", "teacher", None),  # linked to the first teacher
    "parent": ("Parent@2026", "parent", None),     # linked to a guardian with 2 children
}

FIRST_M = ["Tendai", "James", "Kwame", "Liam", "Tafadzwa", "Daniel", "Musa", "Ethan", "Farai", "Noah",
           "Kudzai", "Samuel", "Tinashe", "Lucas", "Brian", "Arjun", "Mateo", "Ryan", "Takunda", "Oliver"]
FIRST_F = ["Rudo", "Amara", "Chipo", "Emma", "Nyasha", "Sophia", "Zanele", "Mia", "Tariro", "Grace",
           "Ama", "Olivia", "Ruvimbo", "Isabella", "Fatima", "Priya", "Lerato", "Ava", "Nokuthula", "Chloe"]
LAST = ["Moyo", "Smith", "Dube", "Mensah", "Ncube", "Brown", "Phiri", "Banda", "Okoro", "Sibanda",
        "Johnson", "Mutasa", "Chikwanha", "Patel", "Garcia", "Nkosi", "Mahlangu", "Williams", "Zulu", "Kamau"]
SUBJECTS = [("MATH", "Mathematics"), ("ENG", "English"), ("SCI", "Science"),
            ("SST", "Social Studies"), ("ICT", "Computer Studies"), ("ART", "Creative Arts")]
PERIODS = [("08:00", "08:40"), ("08:40", "09:20"), ("09:20", "10:00"), ("10:20", "11:00"),
           ("11:00", "11:40"), ("11:40", "12:20"), ("13:00", "13:40")]


def _monday(d):
    return d - timedelta(days=d.weekday())


def _school_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def seed_demo(students_per_class=14, rng_seed=42):
    rng = random.Random(rng_seed)
    db.drop_all()
    db.create_all()
    ledger.ensure_chart()
    today = date.today()

    # ---- calendar: three terms with the current one containing today ----------
    t3s = _monday(today - timedelta(days=35))
    t3e = t3s + timedelta(days=88)
    t2s = _monday(t3s - timedelta(days=120))
    t2e = t2s + timedelta(days=88)
    t1s = _monday(t2s - timedelta(days=120))
    t1e = t1s + timedelta(days=88)
    yname = str(t1s.year) if t1s.year == t3e.year else f"{t1s.year}/{t3e.year}"
    year = AcademicYear(name=yname, start_date=t1s, end_date=t3e, is_current=True)
    terms = [Term(year=year, name=f"Term {i + 1}", start_date=s, end_date=e, is_current=(i == 2))
             for i, (s, e) in enumerate([(t1s, t1e), (t2s, t2e), (t3s, t3e)])]
    db.session.add(year)

    for letter, mn, pts, remark in [("A", 80, 4, "Excellent"), ("B", 70, 3, "Very good"), ("C", 60, 2, "Good"),
                                    ("D", 50, 1, "Pass"), ("E", 40, 0.5, "Weak"), ("F", 0, 0, "Fail")]:
        db.session.add(GradeBand(letter=letter, min_score=mn, points=pts, remark=remark))

    # ---- users & staff -------------------------------------------------------
    users = {}
    for uname, (pw, role, full) in DEMO_ACCOUNTS.items():
        if full:
            u = User(username=uname, full_name=full, role=role, email=f"{uname}@school.test")
            u.set_password(pw)
            db.session.add(u)
            users[uname] = u
    db.session.flush()
    for full, pos, dept, uname in [("Grace Ndlovu", "Principal", "Administration", "admin"),
                                   ("Peter Okafor", "Bursar", "Finance", "bursar")]:
        fn, ln = full.split()
        db.session.add(Staff(staff_no=next_number("staff", "STF", 3), first_name=fn, last_name=ln, position=pos,
                             department=dept, user=users[uname], salary_cents=rng.randint(1500, 2500) * 100,
                             hire_date=today - timedelta(days=rng.randint(400, 3000)), gender="Female" if fn == "Grace" else "Male"))

    subjects = [Subject(code=c, name=n) for c, n in SUBJECTS]
    db.session.add_all(subjects)
    teachers = []
    for i in range(12):
        female = i % 2 == 0
        fn = rng.choice(FIRST_F if female else FIRST_M)
        ln = rng.choice(LAST)
        st = Staff(staff_no=next_number("staff", "STF", 3), first_name=fn, last_name=ln,
                   gender="Female" if female else "Male", position="Teacher",
                   department=SUBJECTS[i % 6][1], phone=f"+263 77{rng.randint(1000000, 9999999)}",
                   email=f"{fn.lower()}.{ln.lower()}@school.test", salary_cents=rng.randint(800, 1400) * 100,
                   hire_date=today - timedelta(days=rng.randint(100, 4000)))
        teachers.append(st)
    db.session.add_all(teachers)
    tu = User(username="teacher", full_name=teachers[0].name, role="teacher", email=teachers[0].email)
    tu.set_password(DEMO_ACCOUNTS["teacher"][0])
    teachers[0].user = tu

    # ---- classes & subject allocation ---------------------------------------
    classes = []
    for level in range(1, 7):
        for stream in "AB":
            classes.append(SchoolClass(name=f"Grade {level}{stream}", level=level, stream=stream,
                                       capacity=30, room=f"R{level}{stream}"))
    db.session.add_all(classes)
    db.session.flush()
    for idx, c in enumerate(classes):
        c.class_teacher_id = teachers[idx].id
        for s_idx, subj in enumerate(subjects):
            # Teachers i and i+6 specialise in subject i; split classes between them.
            teacher = teachers[s_idx] if idx < 6 else teachers[s_idx + 6]
            db.session.add(ClassSubject(class_id=c.id, subject_id=subj.id, teacher_id=teacher.id))
    db.session.flush()

    # ---- timetable (greedy, clash-free) -------------------------------------
    busy_teacher, busy_class = set(), set()
    for c in classes:
        lessons = [cs for cs in c.subjects for _ in range(5)]
        rng.shuffle(lessons)
        slots = [(d, p) for d in range(5) for p in range(len(PERIODS))]
        for cs in lessons:
            for d, p in slots:
                if (c.id, d, p) in busy_class or (cs.teacher_id, d, p) in busy_teacher:
                    continue
                # Avoid the same subject twice a day where possible.
                if any(s.day == d for s in cs.slots) and len([x for x in slots if (c.id, x[0], x[1]) not in busy_class]) > 6:
                    continue
                busy_class.add((c.id, d, p))
                busy_teacher.add((cs.teacher_id, d, p))
                db.session.add(TimetableSlot(class_subject=cs, day=d, start_time=PERIODS[p][0], end_time=PERIODS[p][1]))
                break
    db.session.flush()

    # ---- guardians & students -----------------------------------------------
    students = []
    guardians = []
    for c in classes:
        for _ in range(students_per_class):
            female = rng.random() < 0.5
            ln = rng.choice(LAST)
            # ~20% of children share a guardian with an earlier sibling of the same surname.
            sibling_g = next((g for g in guardians if g.name.endswith(ln)), None) if rng.random() < 0.2 else None
            if sibling_g:
                g = sibling_g
            else:
                g = Guardian(name=f"{rng.choice(FIRST_F + FIRST_M)} {ln}", phone=f"+263 71{rng.randint(1000000, 9999999)}",
                             relationship=rng.choice(["Mother", "Father", "Guardian"]),
                             email=None, address=f"{rng.randint(1, 250)} {rng.choice(['Main', 'Park', 'Hill', 'Lake'])} Road")
                guardians.append(g)
                db.session.add(g)
            age = 5 + c.level + rng.choice([0, 0, 1])
            dob = today - timedelta(days=age * 365 + rng.randint(0, 300))
            adm = t1s - timedelta(days=rng.randint(0, 365 * (c.level - 1) + 1))
            st = Student(first_name=rng.choice(FIRST_F if female else FIRST_M), last_name=ln,
                         gender="Female" if female else "Male", dob=dob, school_class=c, guardian=g,
                         admission_date=adm,
                         admission_no=next_number(f"adm-{adm.year}", f"ADM{adm.year}-", 4))
            students.append(st)
            db.session.add(st)
    db.session.flush()

    # Parent demo account: a guardian with two children.
    fam = next(g for g in guardians if len(g.students) >= 2) if any(len(g.students) >= 2 for g in guardians) else guardians[0]
    if len(fam.students) < 2:
        students[-1].guardian = fam
    pu = User(username="parent", full_name=fam.name, role="parent", email="parent@school.test")
    pu.set_password(DEMO_ACCOUNTS["parent"][0])
    fam.user = pu

    for st in rng.sample(students, 8):
        db.session.add(Scholarship(student=st, name=rng.choice(["Academic merit", "Sports", "Staff child", "Bursary"]),
                                   percent=rng.choice([25, 50, 100])))
    db.session.flush()

    # ---- opening balances (statement of financial position brought forward) ----
    a = ledger.acct
    ledger.post(t1s - timedelta(days=1), "Opening balances brought forward", [
        {"account": a("1010"), "debit": 6_000_000}, {"account": a("1000"), "debit": 150_000},
        {"account": a("1500"), "debit": 25_000_000}, {"account": a("1590"), "credit": 4_000_000},
        {"account": a("3000"), "credit": 27_150_000},
    ], reference="OPENING", force=True)

    # ---- fees, invoices & payments -----------------------------------------
    bursar = users["bursar"]
    for term in terms:
        due = term.start_date + timedelta(days=21)
        db.session.add(FeeItem(term=term, name="Development levy", amount_cents=5000, due_date=due, discountable=False))
        db.session.add(FeeItem(term=term, name="Examination fee", amount_cents=2500, due_date=due, discountable=False))
        for c in classes:
            db.session.add(FeeItem(term=term, class_id=c.id, name="Tuition", amount_cents=(400 + c.level * 50) * 100, due_date=due))
            if c.level >= 4:
                db.session.add(FeeItem(term=term, class_id=c.id, name="ICT & Lab", amount_cents=3500, due_date=due))
        db.session.flush()
        for item in FeeItem.query.filter_by(term_id=term.id):
            item.account_id = ledger.fee_account_for(item.name).id
        # Invoices are issued on the first day of each term.
        finance.generate_term_invoices(term, issue_date=term.start_date)

    # Plan every payment first, then post them in date order so receipt numbers are chronological.
    planned = []
    for st in students:
        habit = rng.random()  # payment behaviour per family
        for term in terms:
            inv = next((i for i in st.invoices if i.term_id == term.id), None)
            if not inv or inv.balance_cents <= 0:
                continue
            last_day = min(term.end_date, today)
            if term.is_current:
                share = 1.0 if habit > 0.55 else (0.5 if habit > 0.25 else 0)
            else:
                share = 1.0 if habit > 0.12 else 0.6
            pay = int(inv.balance_cents * share / 100) * 100
            if pay <= 0:
                continue
            instalments = 1 if habit > 0.7 else 2
            span = max((last_day - term.start_date).days, 0)
            days = sorted(rng.randint(0, span) for _ in range(instalments))
            for k in range(instalments):
                amount = pay // instalments if k < instalments - 1 else pay - (pay // instalments) * (instalments - 1)
                method = rng.choice(["cash", "bank", "mobile", "mobile", "card"])
                ref = None if method == "cash" else f"TX{rng.randint(10 ** 8, 10 ** 9 - 1)}"
                planned.append((min(term.start_date + timedelta(days=days[k]), today), st.id, amount, method, ref, st))
    for paid_on, _, amount, method, ref, st in sorted(planned, key=lambda p: (p[0], p[1])):
        finance.record_payment(st, amount, method, ref, paid_on, bursar)

    # ---- attendance (previous + current term) -------------------------------
    rows = []
    for term in terms[1:]:
        # Stop yesterday so today's register is left for the demo teacher to take.
        for d in _school_days(term.start_date, min(term.end_date, today - timedelta(days=1))):
            for st in students:
                r = rng.random()
                weak = (st.id % 17 == 0)  # a few chronically absent pupils for the at-risk report
                status = ("absent" if r < (0.25 if weak else 0.04) else "late" if r < 0.08 else
                          "excused" if r < 0.095 else "present")
                rows.append(Attendance(student_id=st.id, class_id=st.class_id, date=d, status=status))
    db.session.bulk_save_objects(rows)

    # ---- exams & marks ------------------------------------------------------
    ability = {st.id: rng.gauss(64, 13) for st in students}
    for term in terms:
        exams = [Exam(term=term, name="Continuous Assessment", weight=20, max_score=50, date=term.start_date + timedelta(days=24)),
                 Exam(term=term, name="Mid-term Test", weight=30, max_score=100, date=term.start_date + timedelta(days=45)),
                 Exam(term=term, name="End of Term Exam", weight=50, max_score=100, date=term.end_date - timedelta(days=7))]
        db.session.add_all(exams)
        db.session.flush()
        marks = []
        for ex in exams:
            if ex.date > today:
                continue
            ex.locked = not term.is_current
            for st in students:
                for subj in subjects:
                    pct = max(5, min(100, ability[st.id] + rng.gauss(0, 9) + (subj.id % 3 - 1) * 4))
                    marks.append(Mark(exam_id=ex.id, student_id=st.id, subject_id=subj.id,
                                      score=round(pct / 100 * ex.max_score)))
        db.session.bulk_save_objects(marks)

    # ---- expenses (accrued on approval, paid from bank/cash through the ledger) ----
    admin = users["admin"]
    cats = [("Utilities", "Electricity bill", "City Power", 600, 900), ("Utilities", "Water bill", "City Water", 150, 300),
            ("Maintenance", "Classroom repairs", "BuildRight Ltd", 300, 1500), ("Supplies", "Stationery restock", "Office Hub", 200, 700),
            ("Transport", "Bus fuel", "FuelCo", 400, 800), ("Food", "Kitchen provisions", "FreshMart", 500, 1100),
            ("IT", "Internet subscription", "NetConnect", 120, 120), ("Events", "Sports day", "Various", 300, 900)]
    payroll = sum(st.salary_cents for st in Staff.query.filter_by(status="active"))
    bank, cash = a("1010"), a("1000")

    def add_expense(cat, desc, vendor, cents, day, status):
        e = Expense(category=cat, description=desc, vendor=vendor, amount_cents=cents, expense_date=day,
                    status=status, requested_by=bursar.id, approved_by=admin.id if status != "pending" else None)
        db.session.add(e)
        db.session.flush()
        if status in ("approved", "paid"):
            e.approved_at = day
            ledger.post_expense_accrual(e, force=True)
        if status == "paid":
            src = cash if cents <= 30_000 else bank
            e.paid_at = min(day + timedelta(days=rng.randint(0, 10)), today)
            e.paid_from_account_id = src.id
            ledger.post_expense_payment(e, src, e.paid_at, force=True)

    d = t1s
    while d <= today:
        payday = d.replace(day=25) if d.day <= 25 else d
        if payday <= today:
            add_expense("Salaries", f"Staff salaries {payday:%B %Y}", "Payroll", payroll, payday, "paid")
        for cat, desc, vendor, lo, hi in cats:
            if rng.random() < 0.7:
                day = min(d + timedelta(days=rng.randint(0, 27)), today)
                age = (today - day).days
                status = "paid" if age > 20 else rng.choice(["pending", "approved", "paid"])
                add_expense(cat, desc, vendor, rng.randint(lo, hi) * 100, day, status)
        d += timedelta(days=30)

    # ---- monthly banking: cash and mobile money swept to the bank (keeps a cash float) ----
    sweep = t1s + timedelta(days=27)
    while sweep < today:
        for src, keep in ((cash, 200_000), (a("1020"), 0)):
            amt = ledger.balance(src, sweep) - keep
            if amt > 0:
                ledger.post(sweep, f"Banking of {src.name.lower()} collections", [
                    {"account": bank, "debit": amt}, {"account": src, "credit": amt}],
                    reference="DEPOSIT", user_id=bursar.id, force=True)
        sweep += timedelta(days=30)

    # ---- manual journals: capital purchase, donation, depreciation per completed term ----
    ledger.post(t2s + timedelta(days=10), "Purchase of 20 laptops for the computer lab", [
        {"account": a("1500"), "debit": 1_600_000}, {"account": bank, "credit": 1_600_000}],
        reference="PO-0042", user_id=bursar.id, force=True)
    ledger.post(t2s + timedelta(days=40), "Donation from the Parents' Association", [
        {"account": bank, "debit": 500_000}, {"account": a("4950"), "credit": 500_000}],
        reference="DON-007", user_id=bursar.id, force=True)
    for term in terms:
        if term.end_date < today:
            ledger.post(term.end_date, f"Depreciation for {term.label}", [
                {"account": a("5900"), "debit": 850_000}, {"account": a("1590"), "credit": 850_000}],
                reference="DEP", user_id=bursar.id, force=True)

    db.session.add_all([
        Announcement(title="Welcome to the new term", pinned=True, audience="all", created_by=admin.id,
                     body="Classes run 08:00-13:40. Please ensure all fees are settled by the due date to avoid penalties."),
        Announcement(title="Staff meeting on Friday", audience="staff", created_by=admin.id,
                     body="All teaching staff: meeting in the staff room at 14:00 to review mid-term results."),
        Announcement(title="Parents' consultation day", audience="parents", created_by=admin.id,
                     body="Meet your child's teachers next Saturday from 09:00. Report cards will be available on the portal."),
    ])
    db.session.commit()
    return {"students": len(students), "classes": len(classes), "teachers": len(teachers)}


def register_cli(app):
    @app.cli.command("seed")
    @click.option("--yes", is_flag=True, help="Skip confirmation")
    def seed_cmd(yes):
        """Erase the database and load demo data."""
        if not yes:
            click.confirm("This ERASES all data and loads demo data. Continue?", abort=True)
        stats = seed_demo()
        click.echo(f"Seeded {stats}. Logins:")
        for uname, (pw, role, _) in DEMO_ACCOUNTS.items():
            click.echo(f"  {role:8} {uname} / {pw}")

    @app.cli.command("ledger-rebuild")
    def ledger_rebuild_cmd():
        """Regenerate automatic ledger postings from invoices, receipts and expenses."""
        n = ledger.rebuild_ledger()
        db.session.commit()
        click.echo(f"{n} postings regenerated.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--name", prompt="Full name")
    @click.password_option()
    def create_admin(username, name, password):
        """Create an administrator account."""
        from .api.auth import validate_password
        validate_password(password)
        u = User(username=username.lower(), full_name=name, role="admin")
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Administrator {username} created.")
