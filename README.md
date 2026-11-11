# EDVANTO
## Learning Management System — Django Project

**Project:** Edvanto  
**Project directory:** `D:\edvanto`  
**Architecture:** Django-based full-stack web application  
**Frontend:** HTML, CSS, JavaScript, Bootstrap 5  
**Backend:** Python and Django  
**Database:** Django-supported relational database (verify active configuration)  

---

# 1. Project Overview

Edvanto is a web-based Learning Management System (LMS) designed to manage online and offline educational programmes.

The platform brings together students, instructors, administrators, courses, curriculum, lessons, learning resources, assessments, payments, attendance, and academic progress.

The application is structured around Django applications, with `core` responsible for the main educational and business domain and `admin_panel` providing administrative workflows.

The project aims to provide a unified platform for:

- Student registration and authentication.
- Email OTP verification.
- Course discovery and management.
- Curriculum and lesson management.
- Online and offline course delivery.
- Student enrollment.
- Payment and installment management.
- Video and learning-resource delivery.
- Assessments and submissions.
- Doubt clearance.
- Batch and attendance management.
- Student learning progress.
- Notifications.
- Certificates and invoices.
- Administrative management.

**Important:** The presence of a model, template, or service file does not automatically mean its feature is fully implemented. Feature completeness must be established through views, URLs, templates, tests, and actual execution.

---

# 2. Technology Stack

| Layer | Technology |
|---|---|
| Programming language | Python |
| Backend framework | Django |
| Frontend | HTML5 |
| Styling | CSS3 |
| JavaScript | JavaScript |
| UI framework | Bootstrap 5 |
| Template engine | Django Templates |
| Database | Verify `config/settings.py` |
| Authentication | Django authentication and project-specific services |
| Static assets | Django static files |
| Media uploads | Django media configuration |
| Testing | Django automated tests |

The project should continue using its existing Django architecture.

React, Vue, or another frontend framework should not be introduced without explicit approval.

---

# 3. Main Project Applications

## 3.1 `config`

Responsible for the main Django project configuration.

Includes:

- Django settings.
- Root URL configuration.
- ASGI application.
- WSGI application.

## 3.2 `core`

The principal application responsible for Edvanto's educational and business functionality.

Includes:

- User management.
- Authentication.
- OTP verification.
- Courses.
- Curriculum.
- Modules.
- Lessons.
- Learning resources.
- Video assets.
- Enrollment.
- Payments.
- Learning progress.
- Assessments.
- Doubts.
- Batches.
- Attendance.
- Notifications.
- Consultations.
- Certificates.
- Invoices.
- Security and audit records.

## 3.3 `admin_panel`

Responsible for administrative interfaces and administrative operations.

Includes:

- Administrator permissions.
- User management.
- Course management.
- Curriculum management.
- Lesson and resource management.
- Assessment management.
- Submission management.
- Enrollment management.
- Payment management.
- Batch management.
- Attendance.
- Doubt management.
- Consultation management.

---

# 4. Core Learning Architecture

The intended educational structure is:

```text
Course
  |
  └── Module
        |
        └── Lesson
              |
              ├── Video
              ├── Resources
              ├── Assessment
              └── Learning Progress
```

A course contains modules.

Each module contains lessons.

Lessons can contain learning materials, videos, and assessments according to the actual implemented relationships.

The project also contains `Syllabus` and `SyllabusTopic` models. These must be audited before any removal or consolidation.

The objective is to avoid competing curriculum structures or duplicate sources of truth.

---

# 5. Learning Modes

Edvanto supports an intended distinction between online and offline learning.

### Online learning

May include:

- Video-based lessons.
- Learning resources.
- Assessments.
- Student progress.
- Doubt clearance.
- Online course access.

### Offline learning

May include:

- Learning centers.
- Instructor allocation.
- Batches.
- Batch sessions.
- Attendance.
- Learning materials.

The actual workflows and access restrictions must be verified against the existing code.

---

# 6. Student Features

The intended student experience includes:

1. Registration.
2. Email OTP verification.
3. Login and logout.
4. Student dashboard.
5. Course enrollment.
6. My Courses.
7. Continue Learning.
8. Current lesson.
9. Lesson completion.
10. Learning progress.
11. Assessments.
12. Doubt clearance.
13. Learning materials.
14. Payments.
15. Installments.
16. Certificates.
17. Profile management.

Student access must be controlled by server-side authentication, enrollment, payment, publication, and lesson-access rules.

---

# 7. Administrative Features

The administrative application is intended to manage:

- Users.
- Courses.
- Curriculum.
- Modules.
- Lessons.
- Resources.
- Videos.
- Assessments.
- Questions.
- Submissions.
- Enrollments.
- Payments.
- Installments.
- Batches.
- Attendance.
- Doubts.
- Consultations.

Administrative permissions must be enforced on the backend. Hiding a button is not sufficient authorization.

---

# 8. Project Directory

The confirmed application-level structure includes:

```text
Edavanto2026/
│
├── manage.py
├── requirements.txt
├── .gitignore
│
├── config/
│
├── core/
│
├── admin_panel/
│
├── templates/
│
├── static/
│
├── media/
│
└── private_media/
```

The detailed directory structure is documented separately in `PROJECT_STRUCTURE.md`.

---

# 9. Installation

## Step 1: Navigate to the project

```powershell
cd D:\edvanto
```

## Step 2: Create a virtual environment

```powershell
python -m venv venv
```

## Step 3: Activate the environment

```powershell
.\venv\Scripts\Activate.ps1
```

## Step 4: Install dependencies

```powershell
pip install -r requirements.txt
```

## Step 5: Configure environment variables

Create a local `.env` file using the environment variables required by the existing settings.

Never copy production credentials into source code or documentation.

## Step 6: Verify Django configuration

```powershell
python manage.py check
```

## Step 7: Inspect migrations

```powershell
python manage.py showmigrations
```

## Step 8: Review migration plan

```powershell
python manage.py migrate --plan
```

## Step 9: Apply migrations

```powershell
python manage.py migrate
```

Only proceed after reviewing the database configuration and migration plan.

## Step 10: Run the development server

```powershell
python manage.py runserver
```

Default local address:

```text
http://127.0.0.1:8000/
```

---

# 10. Testing

Run the complete test suite:

```powershell
python manage.py test
```

Run focused application tests using the actual test module paths:

```powershell
python manage.py test core
python manage.py test admin_panel
```

Run the Django system check:

```powershell
python manage.py check
```

Do not consider a feature complete merely because its template loads.

Test:

- Database operations.
- Form validation.
- Authentication.
- Role permissions.
- Object ownership.
- Course enrollment.
- Payment verification.
- Lesson access.
- Learning progress.
- File access.
- Administrative operations.

---

# 11. Security Requirements

- Keep passwords hashed.
- Never expose OTPs or authentication tokens.
- Validate all user input on the server.
- Enforce permissions in views and services.
- Protect student-owned records.
- Verify payments on the backend.
- Protect private course materials.
- Maintain CSRF protection.
- Avoid exposing sensitive information in logs.
- Keep secrets outside Git.
- Preserve migration history.
- Back up important databases before risky migrations.

---

# 12. Development Rules

Every development task must follow this sequence:

1. Inspect existing implementation.
2. Identify related models, views, URLs, forms, and templates.
3. Trace dependencies.
4. Prepare an implementation plan.
5. Make the smallest complete change.
6. Add or update tests.
7. Review migrations if applicable.
8. Run relevant tests.
9. Review Git changes.
10. Document the result.

Do not rebuild working components or perform unrelated refactoring.

Preserve the existing Edvanto visual identity and frontend architecture.

---

# 13. Important Project Decisions

### Curriculum

Preferred learning hierarchy:

`Course → Module → Lesson`

Do not remove `Syllabus` or `SyllabusTopic` without a dependency and data review.

### Course duration

Previously discussed requirements:

- Online duration: hours.
- Offline duration: weeks.

Inspect the actual fields and validation before modifying them.

### Frontend

Use:

- Django Templates.
- Bootstrap 5.
- Existing CSS.
- Existing JavaScript.

Preserve template inheritance, URL names, context variables, and working frontend behaviour.

### Database

Never delete the existing database or migration history as a troubleshooting shortcut.

---

# 14. Git Management

Before making changes:

```powershell
git status
git branch --show-current
git diff --stat
```

After implementation:

```powershell
git diff --check
git diff --stat
git status
```

Never commit:

- `.env`
- Virtual environments.
- Local databases.
- Private uploads.
- Credentials.
- Cache files.

---

# 15. Documentation

Maintain these project documents:

| Document | Purpose |
|---|---|
| `README.md` | Project introduction and setup |
| `PROJECT_STRUCTURE.md` | Complete file and application architecture |
| `DEVELOPMENT_RULES.md` | Rules for future development |
| `DATABASE_ARCHITECTURE.md` | Models and database relationships |
| `FEATURE_STATUS.md` | Implementation status |
| `DEPLOYMENT.md` | Production setup and deployment |

---

# 16. Definition of Done

A feature is complete only when:

- Its backend functionality works.
- Its database operations are correct.
- Its forms validate correctly.
- Its permissions are enforced.
- Its frontend displays real backend data.
- Its relevant tests pass.
- Existing functionality is preserved.
- Its changes are documented.

---

**Project:** EDVANTO  
**Purpose:** Educational management and learning platform  
**Architecture:** Django full-stack application  
**Development principle:** Preserve existing architecture, implement incrementally, and verify every feature.
