"""Grading, ranking, report cards, attendance statistics and promotion."""
from collections import defaultdict
from datetime import date

from flask import current_app

from .. import db
from ..models import Attendance, Exam, GradeBand, Mark, SchoolClass, Student
from ..utils import ApiError, audit


def grade_for(pct, bands=None):
    bands = bands if bands is not None else GradeBand.query.order_by(GradeBand.min_score.desc()).all()
    for band in bands:
        if pct >= band.min_score:
            return band
    return bands[-1] if bands else None


def rank(values):
    """Competition ranking: {key: score} -> {key: position}; ties share a position (1,1,3)."""
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=True)
    positions, prev, pos = {}, None, 0
    for i, (key, score) in enumerate(ordered, start=1):
        if score != prev:
            pos, prev = i, score
        positions[key] = pos
    return positions


def term_results(class_id, term_id):
    """Weighted subject percentages for every active student in a class.

    A subject's term % is the weighted mean of the exams the student sat:
        sum(score/max * weight) / sum(weight)
    so a missed exam does not silently count as zero; it is flagged instead.
    """
    cls = db.session.get(SchoolClass, class_id)
    exams = Exam.query.filter_by(term_id=term_id).order_by(Exam.date, Exam.id).all()
    students = sorted(cls.active_students(), key=lambda s: (s.last_name, s.first_name))
    subjects = [cs.subject for cs in sorted(cls.subjects, key=lambda cs: cs.subject.name)]
    exam_ids = [e.id for e in exams]
    student_ids = [s.id for s in students]
    marks = Mark.query.filter(Mark.exam_id.in_(exam_ids or [-1]),
                              Mark.student_id.in_(student_ids or [-1])).all()
    by_key = {(m.student_id, m.subject_id, m.exam_id): m.score for m in marks}
    # Exams actually administered per subject in this class (anyone has a mark).
    sat = defaultdict(set)
    for m in marks:
        sat[m.subject_id].add(m.exam_id)

    bands = GradeBand.query.order_by(GradeBand.min_score.desc()).all()
    results = {}
    for st in students:
        subj = {}
        for sub in subjects:
            num = den = 0.0
            missing = []
            breakdown = []
            for ex in exams:
                score = by_key.get((st.id, sub.id, ex.id))
                if score is not None:
                    num += score / ex.max_score * ex.weight
                    den += ex.weight
                    breakdown.append({"exam": ex.name, "score": score, "max": ex.max_score})
                elif ex.id in sat[sub.id]:
                    missing.append(ex.name)
            if den:
                pct = round(num / den * 100, 1)
                band = grade_for(pct, bands)
                subj[sub.id] = {"subject": sub.name, "code": sub.code, "percent": pct,
                                "grade": band.letter if band else "", "points": band.points if band else 0,
                                "remark": band.remark if band else "", "missing": missing,
                                "exams": breakdown}
        avg = round(sum(r["percent"] for r in subj.values()) / len(subj), 1) if subj else None
        results[st.id] = {"student": st, "subjects": subj, "average": avg}

    overall = rank({sid: r["average"] for sid, r in results.items() if r["average"] is not None})
    for sub in subjects:
        sub_rank = rank({sid: r["subjects"][sub.id]["percent"]
                         for sid, r in results.items() if sub.id in r["subjects"]})
        for sid, pos in sub_rank.items():
            results[sid]["subjects"][sub.id]["position"] = pos
            results[sid]["subjects"][sub.id]["out_of"] = len(sub_rank)
    for sid, r in results.items():
        r["position"] = overall.get(sid)
        r["out_of"] = len(overall)
        band = grade_for(r["average"], bands) if r["average"] is not None else None
        r["grade"] = band.letter if band else None
    return {"class": cls, "subjects": subjects, "exams": exams, "results": results}


def attendance_stats(student_ids, start, end):
    """{student_id: {present, absent, late, excused, days, rate}}; late counts as attended."""
    rows = Attendance.query.filter(Attendance.student_id.in_(student_ids or [-1]),
                                   Attendance.date >= start, Attendance.date <= end).all()
    stats = defaultdict(lambda: {"present": 0, "absent": 0, "late": 0, "excused": 0})
    for r in rows:
        stats[r.student_id][r.status] += 1
    out = {}
    for sid in student_ids:
        s = stats[sid]
        days = sum(s.values())
        # Excused absences are removed from the denominator rather than penalised.
        counted = days - s["excused"]
        s["days"] = days
        s["rate"] = round((s["present"] + s["late"]) / counted * 100, 1) if counted else None
        out[sid] = s
    return out


def report_card(student, term):
    if not student.class_id:
        raise ApiError("Student is not enrolled in a class")
    data = term_results(student.class_id, term.id)
    r = data["results"].get(student.id)
    if r is None:
        raise ApiError("No results for this student")
    att = attendance_stats([student.id], term.start_date, term.end_date)[student.id]
    from .finance import account_summary
    cls = data["class"]
    pass_mark = current_app.config["PASS_MARK"]
    subjects = list(r["subjects"].values())
    return {
        "student": {"id": student.id, "name": student.name, "admission_no": student.admission_no,
                    "gender": student.gender, "dob": student.dob.isoformat()},
        "class": cls.name,
        "class_teacher": cls.class_teacher.name if cls.class_teacher else None,
        "term": term.label,
        "subjects": subjects,
        "average": r["average"], "grade": r["grade"],
        "position": r["position"], "out_of": r["out_of"],
        "passed": sum(1 for s in subjects if s["percent"] >= pass_mark),
        "failed": sum(1 for s in subjects if s["percent"] < pass_mark),
        "attendance": att,
        "fees": account_summary(student),
        "comment": auto_comment(r["average"], att.get("rate")),
    }


def auto_comment(avg, att_rate):
    if avg is None:
        return "No assessments recorded this term."
    if avg >= 80:
        text = "Excellent performance. Keep it up."
    elif avg >= 65:
        text = "Good work; aim higher next term."
    elif avg >= 50:
        text = "Fair performance. More effort is needed."
    else:
        text = "Below expectations. Requires close support and follow-up."
    threshold = current_app.config["ATTENDANCE_THRESHOLD"]
    if att_rate is not None and att_rate < threshold:
        text += f" Attendance ({att_rate}%) is below the required {threshold:g}%."
    return text


def validate_term_weights(term_id, exclude_id=None, new_weight=0.0):
    total = sum(e.weight for e in Exam.query.filter_by(term_id=term_id) if e.id != exclude_id)
    if total + new_weight > 100.0001:
        raise ApiError(f"Exam weights for this term would total {total + new_weight:g}%; maximum is 100%",
                       fields={"weight": "Exceeds 100% total"})


def promotion_plan():
    """Work out where each active student goes next year.

    Same stream at level+1 if it exists, otherwise the least-full class at level+1.
    Students at the top level graduate. Capacity is respected.
    """
    max_level = current_app.config["MAX_CLASS_LEVEL"]
    classes = SchoolClass.query.all()
    by_level = defaultdict(list)
    for c in classes:
        by_level[c.level].append(c)
    # Incoming headcount per class after promotion (students staying put don't exist:
    # everyone moves, so each class starts empty apart from incoming students).
    incoming = defaultdict(int)
    plan = []
    students = (Student.query.filter_by(status="active").filter(Student.class_id.isnot(None))
                .join(SchoolClass).order_by(SchoolClass.level.desc(), Student.last_name).all())
    for st in students:
        cur = st.school_class
        entry = {"student_id": st.id, "student": st.name, "from": cur.name}
        if cur.level >= max_level:
            entry.update(action="graduate", to=None)
        else:
            candidates = by_level.get(cur.level + 1, [])
            same = [c for c in candidates if c.stream == cur.stream and incoming[c.id] < c.capacity]
            others = sorted((c for c in candidates if incoming[c.id] < c.capacity),
                            key=lambda c: incoming[c.id])
            target = same[0] if same else (others[0] if others else None)
            if target:
                incoming[target.id] += 1
                entry.update(action="promote", to=target.name, to_class_id=target.id)
            else:
                entry.update(action="blocked", to=None,
                             reason=f"No class with free capacity at level {cur.level + 1}")
        plan.append(entry)
    return plan


def apply_promotion(plan, hold_back_ids):
    hold = set(hold_back_ids or [])
    if any(p["action"] == "blocked" and p["student_id"] not in hold for p in plan):
        raise ApiError("Some students cannot be placed; add class capacity or hold them back first")
    moved = graduated = held = 0
    for p in plan:
        st = db.session.get(Student, p["student_id"])
        if p["student_id"] in hold:
            held += 1
        elif p["action"] == "graduate":
            st.status, st.class_id = "graduated", None
            graduated += 1
        else:
            st.class_id = p["to_class_id"]
            moved += 1
    audit("promote", "student", None, f"promoted {moved}, graduated {graduated}, held back {held}")
    return {"promoted": moved, "graduated": graduated, "held_back": held}


def at_risk_students(term):
    """Students below the attendance threshold or failing on average this term."""
    threshold = current_app.config["ATTENDANCE_THRESHOLD"]
    pass_mark = current_app.config["PASS_MARK"]
    end = min(term.end_date, date.today())
    flagged = []
    for cls in SchoolClass.query.all():
        ids = [s.id for s in cls.active_students()]
        if not ids:
            continue
        att = attendance_stats(ids, term.start_date, end)
        res = term_results(cls.id, term.id)["results"]
        for sid in ids:
            reasons = []
            rate = att[sid]["rate"]
            if rate is not None and rate < threshold:
                reasons.append(f"Attendance {rate}%")
            avg = res[sid]["average"]
            if avg is not None and avg < pass_mark:
                reasons.append(f"Average {avg}%")
            if reasons:
                st = res[sid]["student"]
                flagged.append({"student_id": sid, "student": st.name, "class": cls.name, "class_id": cls.id,
                                "reasons": reasons})
    return flagged
