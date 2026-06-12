# Product

## Register

product

## Users

- **Teachers**: run attendance during class, often from a laptop at a lectern. Time-pressed; need attendance captured in under a minute and trustworthy records they can export and defend.
- **Students**: enroll in subjects, log in with their face (or password fallback), check their own attendance, mostly from phones.

## Product Purpose

SnapClass is a smart attendance system. Teachers photograph the class (or record voices); AI (DeepFace facial embeddings + SVM, voice embeddings) recognizes enrolled students and marks attendance. Students self-enroll with face photos. Success = attendance taken in seconds with near-zero false marks, and records teachers actually trust.

## Brand Personality

Friendly, quick, trustworthy. Approachable for students, dependable for teachers marking official records. Light playfulness in color and motion; never clutter, never toy-like where accuracy is at stake (attendance review, exports).

## Anti-references

- Institutional ERP grimness (gray tables, cramped forms, SAP-like density).
- Toy/gamified school apps (badges everywhere, confetti, mascots).
- Generic SaaS dashboard template (hero metrics with gradient accents, identical card grids).

## Design Principles

1. **Attendance is the hero task.** Every screen optimizes for "take/check attendance fast"; everything else is secondary.
2. **Show the AI's work.** Recognition results are always reviewable and correctable by a human before they become a record. Never silently trust the model.
3. **Phone-first for students, laptop-first for teachers.** Student views must be thumb-reachable; teacher views can use width.
4. **Trust through legibility.** Records, percentages, and exports read like official documents: high contrast, clear states (present/absent), no ambiguity.

## Accessibility & Inclusion

WCAG AA baseline: ≥4.5:1 body text contrast, full keyboard navigation, visible focus states, `prefers-reduced-motion` alternatives for all animation, labels/alt text for screen readers, camera/mic flows always paired with a non-biometric fallback (password login).
