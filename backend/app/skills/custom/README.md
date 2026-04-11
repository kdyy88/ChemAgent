# Custom skills directory
# Place user-defined or organization-specific skill manifests here.
#
# Each skill should be a Python package containing a manifest.py that:
#   1. Creates a SkillManifest instance
#   2. Calls register_skill(manifest) from app.skills.loader
#
# The skills/loader.py will auto-discover and load these on startup.
