"""Skill packs — user-authored capabilities (knowledge + executable tools).

A pack is a folder (or zip) the user writes themselves:

    my-skill/
      SKILL.md          # frontmatter (identity + when_to_use) + prose knowledge
      skill.yaml        # optional: tool declarations (can also live in frontmatter)
      tools/            # python modules implementing the tools
      lib/              # any private modules the tools import
      references/       # extra markdown the agent reads on demand
      assets/           # data files the tools open

Three-layer disclosure, mirroring how the rest of the app treats tools:
  1. always in the prompt — name / description / when_to_use / tool one-liners
  2. `read_skill`        — the SKILL.md body, only when the agent decides it's relevant
  3. `read_skill(file=)` — a reference doc, only when the body points at it
"""

from .manifest import SkillManifest, ToolSpec, load_manifest, ManifestError  # noqa: F401
