"""IR package — the Pydantic models are the single source of truth for the
intermediate representations (timings/v2, sceneplan/v1). They also generate the
OpenAPI schema and, transitively, the frontend TypeScript types.

Key principle: timing is a fact of the AUDIO (timings); meaning is a fact of the
PLAN (sceneplan). The plan never carries start/end — those are joined by index at
compose time, so editing the plan can never desync captions from narration.
"""
