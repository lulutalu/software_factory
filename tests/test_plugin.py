"""Consistency checks on the plugin files (manifests, agent frontmatter, skill).

These catch the mistakes `claude plugin validate` does not: wrong model/effort
values, a read-only role that got Edit, or an agent the orchestrator doesn't know.

Run: python3 -m unittest discover -s tests -v
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "agents"
SKILL = ROOT / "skills" / "factory" / "SKILL.md"

MODELS = {"opus", "sonnet", "haiku", "inherit"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
READ_ONLY = {"spec-writer", "builder", "code-reviewer", "security-reviewer"}
SPECIALISTS = {"frontend", "backend", "data", "tests"}


def frontmatter(path: Path) -> dict:
    """Simple `key: value` frontmatter parser (enough for these files)."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        raise AssertionError(f"{path.name}: no frontmatter")
    out = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


class ManifestTest(unittest.TestCase):
    def test_manifests_are_valid_json(self):
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "software-factory")
        self.assertIn("software-factory", [p["name"] for p in market["plugins"]])


class AgentTest(unittest.TestCase):
    def test_agent_frontmatter(self):
        for path in sorted(AGENTS.glob("*.md")):
            with self.subTest(agent=path.name):
                fm = frontmatter(path)
                self.assertEqual(fm.get("name"), path.stem)
                self.assertTrue(fm.get("description"))
                model = fm.get("model", "")
                self.assertTrue(model in MODELS or model.startswith("claude-"), f"unknown model {model!r}")
                self.assertIn(fm.get("effort"), EFFORTS)
                tools = {t.strip() for t in fm.get("tools", "").split(",")}
                if path.stem in READ_ONLY:
                    self.assertNotIn("Edit", tools, "read-only roles must not get Edit")

    def test_skill_references_every_agent(self):
        skill = SKILL.read_text(encoding="utf-8")
        agents = {p.stem for p in AGENTS.glob("*.md")}
        referenced = set(re.findall(r"software-factory:([a-z-]+)", skill))
        self.assertEqual(referenced, agents)

    def test_builder_knows_every_specialist(self):
        builder = (AGENTS / "builder.md").read_text(encoding="utf-8")
        for name in SPECIALISTS:
            self.assertIn(f"`{name}`", builder)


if __name__ == "__main__":
    unittest.main()
