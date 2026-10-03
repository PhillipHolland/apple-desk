# Product rule — generalize (Phillip, 2026-10-03)

**This is NOT a one-off for office-mini-3.**

Every improvement that ships must work for **any user on any Mac** in our Apple ecosystem (fresh install, `grok-desk onboard`).

## Do not
- Hardcode this machine’s name, Phillip-only accounts/paths, or local quirks as product behavior
- Leave mini-only workarounds as the shipped path

## Do
- Portable caches (`~/.cache/grok-*`), config/env, doctor hints, dry-runs, timeouts that work on a fresh Mac
- Treat office-mini-3 as build/verify host only
- Mark host-only verification separately from product code

If in-flight work is mini-specific, course-correct before committing.
