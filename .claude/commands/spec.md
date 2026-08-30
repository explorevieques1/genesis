---
description: Load the full design context for one Genesis component — its note plus every note it links to
argument-hint: <note name, e.g. "Screener" or "Pre-Trade Risk Engine">
allowed-tools: Read, Grep, Glob
---

Load the complete design context for: **$ARGUMENTS**

Do this:

1. **Find the note.** Try `Glob **/*$ARGUMENTS*.md` inside `Genesis Markdown/`.
   For an agent the file is `Agent — <Name>.md`. If nothing matches, check
   `Genesis Markdown/00-Meta/Vault Map.md` for the closest name and ask me which
   one I meant rather than guessing.

2. **Read it in full.**

3. **Resolve its one-hop links.** Collect every `[[wikilink]]` in the note —
   especially the **Related** line at the bottom — and read those notes too.
   Strip `\|` escapes and take the part before any `|`. Go one hop only; do not
   recurse.

4. **If it is an agent note**, also read `10-Architecture/Agent Contract.md`.
   **If it touches orders**, also read `50-Risk/Pre-Trade Risk Engine.md` and
   `50-Risk/Safety Invariants.md`.

Then give me, in under 400 words:

- **What this is** — one paragraph.
- **Interfaces** — inputs and outputs, with the exact schema names from
  `70-Schemas/`.
- **Constraints** — model tier, cadence, and any safety invariant that binds it.
- **Acceptance criteria** — verbatim from the note. These are the tests.
- **Depends on** — which other components must exist first, and their `status:`
  from frontmatter.
- **Open questions** — anything the vault leaves undecided, with the
  `00-Meta/Open Questions.md` section number if it is listed there.

Do not write any code yet. Wait for me.
