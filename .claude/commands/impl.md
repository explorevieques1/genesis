---
description: Mark a component built — update both sides of the spec/code binding and regenerate the vault map
argument-hint: <note name> <source path(s)>
allowed-tools: Read, Edit, Glob, Bash
---

Close the loop on: **$ARGUMENTS**

The first argument is a vault note name; the rest are source file paths.

1. **Find the note** with `Glob **/*<name>*.md` under `Genesis Markdown/`.

2. **Verify before claiming.** Read each source file. Check it actually satisfies
   the note's **Acceptance criteria**. If it does not, stop — tell me which
   criteria are unmet and change nothing. A false `built` is worse than no
   status at all, because it stops anyone looking again.

3. **Update the note frontmatter:**
   ```yaml
   status: built
   implemented_by: [src/genesis/agents/screener.py]
   ```
   Use `building` if partially done, and say which criteria remain.

4. **Update each source file's header** to carry its spec pointer, if missing:
   ```python
   # Spec: Genesis Markdown/20-Agents/Research/Agent — Screener.md
   ```

5. **If the implementation diverged from the spec**, update the note's prose to
   match reality — in this same change. The spec is the source of truth, so a
   spec that describes something we deliberately didn't build is a bug. Tell me
   what you changed and why.

6. **Regenerate the map:** `python3 scripts/build_vault_map.py`

Report: what is now `built`, what remains, and anything the implementation taught
us that the spec should have said.
