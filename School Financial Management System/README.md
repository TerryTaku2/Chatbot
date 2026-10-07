# School Management System

A school management system that runs in the browser. The backend uses Python (Flask, SQLAlchemy) and the frontend uses plain HTML5, CSS and JavaScript (ES modules, no build step). It covers student records, academics, attendance and finance, and enforces the school's business rules on the server.

## Quick start

```bash
pip install -r requirements.txt
python run.py            # first run loads demo data, then serves http://127.0.0.1:5000
python run.py --reset    # wipe and reload demo data
python -m pytest -q      # run the business-rule tests
```

| Role          | Username  | Password       |
|---------------|-----------|----------------|
| Administrator | `admin`   | `Admin@2026`   |
| Bursar        | `bursar`  | `Bursar@2026`  |
| Teacher       | `teacher` | `Teacher@2026` |
| Parent        | `parent`  | `Parent@2026`  |

For production, set `SECRET_KEY` and `DATABASE_URL`, run the app behind a WSGI server (e.g. `waitress-serve --call app:create_app`), then run `flask --app run create-admin` to create the first administrator. `SCHOOL_NAME`, `CURRENCY` and `MAX_CLASS_LEVEL` are also configurable through environment variables.

## WhatsApp chatbot integration

The T-Tech Connect WhatsApp chatbot (the parent repository) gives parents a **🎓 School Fees** menu (option 7). From it they can:

- check each child's balance, overdue amount and unpaid invoices
- see recent payments and receipts
- pay fees with EcoCash or OneMoney through Paynow, which records a receipt here automatically
- read announcements addressed to parents

Parents are identified only by their WhatsApp number. It must match the **guardian phone** recorded on the student. Any format works (`+263 77 123 4567`, `0771234567`), because numbers are compared after normalising.

### Where it runs

The chatbot website serves this app at **`/school`** (for example `https://<chatbot-domain>/school/`). It ships with every chatbot deploy and needs no separate service. See `school_mount.py` in the chatbot repository.

- **Database:** its tables are kept in the `school` schema of the chatbot's `DATABASE_URL`. Set `SCHOOL_DATABASE_URL` to use a different database.
- **First login:** on start-up, if there is no administrator, one is created from `SCHOOL_ADMIN_USERNAME` (default `admin`) and `SCHOOL_ADMIN_PASSWORD`. Without that password nobody can log in.
- **Settings:** `SCHOOL_NAME`, `CURRENCY` and `MAX_CLASS_LEVEL` are read from the same environment as the chatbot.
- **No domain needed:** the chatbot and this app call each other directly inside the process, not over the internet. WhatsApp option 7 and the receipts work the same on `localhost`, ngrok or a hosting provider's default address, whatever `BASE_URL` is set to. The integration key and session secret are derived from the chatbot's `FLASK_SECRET_KEY`, so there is nothing else to configure.

### Running it on its own

`python run.py` still works and serves the app at `/`. To connect a separately hosted copy to the chatbot, set these:

| School system | Chatbot | Purpose |
|---|---|---|
| `CHATBOT_API_KEY` | `SCHOOL_API_KEY` | The same random value on both sides. |
| `CHATBOT_WEBHOOK_URL` | — | `https://<chatbot>/webhooks/school`, for WhatsApp receipts of payments taken at the school. |
| — | `SCHOOL_API_URL` | Base URL of this app. |
| `PHONE_COUNTRY_CODE` | — | Country code for guardian phones stored in local format (default `263`). |

How payments made through the chatbot are handled:

- They are recorded with method `mobile` and the Paynow reference (`SCH-…`). The receiver is a `whatsapp-bot` service account, which is inactive and can never log in.
- Recording is idempotent per reference, so a retry returns the original receipt instead of creating a second one.
- The chatbot records a payment only after Paynow confirms it. It never accepts more than the outstanding balance.
- If this app is unreachable at that moment, the chatbot admin gets an alert and can re-send the payment with `school retry SCH-XXXXXXXX` on WhatsApp.

Endpoints (all require `Authorization: Bearer <CHATBOT_API_KEY>`). Each one only returns students whose guardian phone matches `phone`:

```
GET  /api/integration/guardian?phone=2637...
GET  /api/integration/students/<id>/account?phone=2637...
POST /api/integration/payments        {student_id, phone, amount, reference}
GET  /api/integration/announcements
```

WhatsApp only delivers free-form messages within 24 hours of the parent's last message. A receipt for a payment taken at the school can therefore fail for a parent who hasn't messaged recently, unless an approved message template is set up in Meta.

## Modules

- **Students and guardians:** auto-numbered admissions, siblings matched by guardian phone, status lifecycle (active → graduated/transferred/withdrawn), parent portal accounts
- **Staff:** duties, salaries, linked login accounts
- **Classes and subjects:** streams, capacity, class teachers, subject–teacher allocation
- **Timetable:** weekly grid with clash detection
- **Attendance:** daily register with a term summary
- **Exams and marks:** weighted assessments, mark sheets, broadsheets, printable report cards with positions
- **Finance:** fee structure, invoice generation, payments with receipts, statements, scholarships, expense approval
- **Financial statements:** income statement, balance sheet, cash flow statement and trial balance, with comparative figures, prepared from a double-entry general ledger (see below)
- **General ledger:** chart of accounts, journals, account ledgers with running balances, manual journal entries, period close
- **Reports:** collection by class, debtor aging, cash flow, academic performance, at-risk students, CSV export
- **Announcements, audit log, academic calendar, grading scale, end-of-year promotion**

## Business rules enforced by the server

**Finance**
- Money is stored as integer cents, so there is no floating-point drift.
- Each student gets one invoice per term, so invoice generation is safe to re-run.
- Payments are allocated to the oldest outstanding invoice first. Any surplus is kept as credit and applied automatically to the next invoice.
- Receipts are never edited or deleted. A receipt can only be voided, with a reason, and only by an administrator, not by the bursar who received it.
- Voiding an invoice turns any money already applied to it into credit on the student's account.
- Non-cash payments need a unique transaction reference. Payments cannot be dated in the future.
- Scholarships reduce only fees marked "discountable" (tuition, but not exam fees). A student's scholarships are capped at 100% in total.
- A fee item cannot be edited once it has been invoiced. Changes after that are made as charges on individual invoices.
- Expenses follow pending → approved/rejected → paid. The person who requested an expense can never approve it.

**Accounting (double-entry general ledger)**
- Every financial event posts a balanced journal entry automatically, in the same database transaction as the event:

  | Event | Debit | Credit |
  |---|---|---|
  | Invoice issued | Student fees receivable (per student) | Fee income accounts (tuition, levy, exams…) |
  | Scholarship on an invoice | Scholarships & discounts (reduces income) | (part of the invoice entry) |
  | Extra charge | Student fees receivable | Sundry income |
  | Payment received | Cash / Bank / Mobile money, depending on payment method | Student fees receivable |
  | Expense approved | Expense account for its category | Accounts payable (posted on the expense date) |
  | Expense paid | Accounts payable | The cash/bank account chosen when paying |
  | Any void | Exact reversing entry, dated the day of the void | |

- The statements use the accrual basis: fees count as income when invoiced, and expenses count when they are incurred.
- Posted entries are never edited or deleted. Mistakes are corrected with reversing entries. Automatic entries can only be reversed by voiding their source document (invoice, receipt or expense), which keeps the per-student balances in step with the ledger.
- Manual journals are used for opening balances, depreciation, asset purchases, donations and transfers. They must balance, cannot be future-dated, and cannot use the receivables or payables accounts (those change only through invoices, receipts and expenses). A manual journal or an expense payment cannot spend more than a cash account holds on that date.
- **Period close:** an administrator can set a lock date. After that, nothing dated on or before it can be posted, so statements already issued for that period never change.
- Account codes follow the account type: 1xxx assets, 2xxx liabilities, 3xxx net assets, 4xxx income, 5xxx expenses. System accounts can't be deactivated, and other accounts only when their balance is zero.
- Every statement shows a built-in check:
  - Trial balance: debits = credits.
  - Balance sheet: assets = liabilities + net assets. Students who owe are shown as receivables, and students who have overpaid are shown as "fees received in advance".
  - Cash flow (direct method): opening cash + movement = closing cash. Transfers between cash accounts drop out.
- A database created before the ledger existed is upgraded automatically on first start: new columns are added and the ledger is built from existing invoices, receipts and expenses. You can repeat the rebuild at any time with `flask --app run ledger-rebuild` or from General Ledger → Period close.

**Academics**
- Exam weights in a term cannot exceed 100%. A term result is the weighted mean of the exams the student actually sat; missed exams are flagged on the report, not counted as zero.
- Positions use competition ranking, so tied students share a position (1, 1, 3).
- Only the assigned subject teacher can enter marks for that subject, and only after the exam date. Scores must be between 0 and the exam's maximum. Locked exams are read-only.
- Only the class teacher takes attendance, and only on school days inside a term, never for future dates. Every student must be marked. Records older than 7 days can only be corrected by an administrator. Excused absences don't lower a student's attendance rate.
- Class capacity is enforced when admitting or moving students.
- A teacher can be class teacher of only one class.
- Staff members with assigned duties cannot be marked as having left. Leavers lose system access.
- Students, classes, subjects, exams and terms that have history cannot be deleted. Students are given a leaving status instead.
- Promotion moves each student up one level, keeping the same stream where possible and respecting capacity. Students in the top level graduate, and the administrator can choose students who repeat the year.

**Security**
- Passwords are hashed.
- Repeated failed logins are throttled.
- Session cookies are HttpOnly and SameSite.
- Every state-changing request must carry a custom header, which blocks cross-site request forgery (CSRF).
- Access is checked per role and per record: parents see only their own children, and teachers see only their own classes.
- Every change is written to the audit log.

## Project layout

```
run.py, config.py
app/
  models.py            database schema
  utils.py             validation, money, permissions, numbering, audit
  services/            business logic (finance, ledger & statements, academics, access rules,
                       chatbot notifications)
  api/                 JSON REST endpoints (auth, people, academic, finance, dashboard,
                       chatbot integration)
  seed.py              demo data + CLI commands
  templates/index.html single-page app shell
  static/css/app.css   design system (light/dark, responsive, print)
  static/js/           api client, UI kit, SVG charts, router, views/
tests/                 business-rule and accounting tests
```
