---
title: "Adheekshaka — The Supervisory Council for Agentic Scholarship"
date: 2026-03-04
author: Dr. Vamshi Krishna Ghanapāṭhī
uid: VKG-A-163
orcid: 0009-0007-3852-0158
doi: ''
status: published
language: en
category: Digital Humanities
subject: Contemporary Commentary
topic:
  - Agentic AI
  - Digital Scholarship
  - Vedic Publishing
keywords:
  - agentic AI
  - supervisory council
  - digital humanities
  - Vedic scholarship
  - scholarly publishing
  - AI governance
  - quality assurance
abstract: "This article describes the Adheekshaka (Sanskrit: अधीक्षक, Supervisor) council — a seven-stage supervisory framework designed to govern agentic AI workflows in the production of Vedic and Sanskrit scholarship. Each stage corresponds to a named council member with a defined role, from planning through live deployment verification."
preamble: "As artificial intelligence increasingly assists in the production, enrichment, and publication of scholarly works, the question of governance and quality assurance becomes central. The Adheekshaka model draws on the traditional Indian concept of sequential review — where each stage of a work passes through a designated authority before proceeding — and applies it to the modern agentic AI pipeline."
---

## What is Adheekshaka?

*Adheekshaka* (Sanskrit: अधीक्षक) means Supervisor or Overseer. In the context of the vkg.works publishing platform and its associated agentic AI workflows, the Adheekshaka Council is a seven-stage supervisory chain that every feature, fix, and publication must pass through before being reported complete.

The council exists to ensure that automated processes — however capable — remain accountable to scholarly standards, cultural sensitivity, and the integrity of VKG's body of work.

## The Council

**Chairman: Dr. Vamśīkṛṣṇa Ghanapāṭhī (VKG)**
All council members report to VKG for final approval and direction. No work is reported complete without VKG's knowledge.

---

### 1. Chaitra — Planning Head

**Role**: Requirements review and risk assessment before any code is written or any pipeline is run.

Chaitra asks: *What exactly is being built? What could go wrong? Are the requirements clear enough to proceed?* No implementation begins without Chaitra's sign-off on scope and approach.

---

### 2. Vaishakha — Assembly Head

**Role**: Module integration, API contracts, and inter-service dependencies.

Vaishakha ensures that new components fit cleanly into the existing system — that a new enrichment script does not break the build pipeline, that a new metadata field is handled by all templates, and that external services (Claude API, FTP, GitHub Actions) are correctly wired.

---

### 3. Jyeshtha — Coding Head

**Role**: Implementation quality, code review, and pattern adherence.

Jyeshtha reviews the actual code written: does it follow existing conventions? Does it handle edge cases? Does it correctly handle VijayaDV PUA characters, multilingual text, and the range of content formats (DOCX, Markdown, PDF) present in VKG's archive?

---

### 4. Aashadha — Quality Analyst

**Role**: Environment-specific validation — secrets, configuration, platform differences.

Aashadha checks that what works in development will work in production. This includes verifying API keys in GitHub Secrets, FTP credentials, Python version compatibility (the build environment uses Python 3.12), and that Windows-specific path handling does not cause issues in Linux CI runners.

---

### 5. Shraavana — Integration Specialist

**Role**: End-to-end flow across all system boundaries.

Shraavana traces the complete journey of a work: from DOCX upload → batch_import → enrich → build → FTP deploy → live URL. Any break in this chain is Shraavana's responsibility to identify and resolve before sign-off.

---

### 6. Proshthapada — Testing Head

**Role**: Test design, pass/fail criteria, and test sign-off.

Proshthapada ensures the test suite (`scripts/test_build.py`) covers the change, that all tests pass with exit code 0, and that new tests are written for new functionality. No feature is marked complete with failing tests.

---

### 7. Aashwina — Deployment Verification Head

**Role**: Confirms *live* behaviour — not just build success.

Aashwina performs the final check: walk the complete user journey on the production site. Does the URL resolve? Does the content render correctly in Devanagari and Telugu? Do the filter controls work on the catalogue? Does the translation panel expand correctly? Only after Aashwina confirms live behaviour is work reported complete to VKG.

---

## Why This Matters for Agentic AI

Agentic AI systems — systems that plan, execute, and self-correct across multiple steps — are powerful but opaque. A pipeline that ingests a hundred documents, calls Claude for metadata, assigns UIDs, and deploys to a live site can do significant damage if a single stage fails silently.

The Adheekshaka framework enforces a culture of **explicit handoffs**: each stage must produce a verifiable output that the next stage checks before proceeding. This is not bureaucracy — it is the same principle that governs Vedic recitation, where each section of a text must be rendered perfectly before the next begins.

The council names are drawn from the *māsa* (month) names of the traditional Indian calendar, chosen to honour the continuity between ancient disciplinary structures and modern collaborative systems.

---

*The Adheekshaka Council was established for the vkg.works agentic publishing platform in 2026. Its principles apply to all projects under the Veda Vijnaana Vishtara initiative.*
