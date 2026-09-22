# Spec: Genesis Markdown/00-Meta/Conventions.md · 00-Meta/Vault Map.md
"""DNA — the instruction set every organ was built from, and the sense of it.

Biological Design puts DNA on the organ map as *"system prompts **and** this
vault"*. It is the one row that is not a component: you cannot build DNA, you
can only give the organism a way to read its own.

Four properties of the real thing carry weight here, and each one shows up as
code in this package:

**One genome, many cell types.** Every cell holds the same instruction set;
what differs is which genes are expressed. The vault plus the prompts are that
instruction set, and ~30 agents are cell types differentiated by
`Agent Contract`. :mod:`genesis.dna.genome` reads the vault half,
:mod:`genesis.dna.prompts` the other.

**Transcription is recorded, not assumed.** DNA → RNA → protein; here it is
note → code → behaviour, written down in both directions: ``# Spec:`` on line
one of a source file, ``implemented_by:`` in the note's frontmatter. That
two-way pointer is the most DNA-like thing in the repo and the reason drift is
detectable at all.

**Mutation is silent; repair is bounded.** A mis-transcribing cell does not
feel wrong. :mod:`genesis.dna.drift` names six ways the record can be wrong and
repairs only the two the code already proves.

**The genome is read-only at runtime.** Weights are frozen and so is the spec.
Nothing in this package is wired to the daemon, no agent has a capability that
reaches it, and there is no write path to a prompt anywhere in Genesis. An
organism that can edit its own genome can edit `Safety Invariants`, and then
every reflex in the system is a suggestion. The germ line is git; the editor is
a person.
"""

from genesis.dna.drift import KINDS, Finding, check, repair
from genesis.dna.genome import REPO, VAULT, Genome, Note, load, load_cached
from genesis.dna.prompts import Prompt, inventory
from genesis.dna.vault_map import render, write

__all__ = [
    "Finding",
    "Genome",
    "KINDS",
    "Note",
    "Prompt",
    "REPO",
    "VAULT",
    "check",
    "inventory",
    "load",
    "load_cached",
    "render",
    "repair",
    "write",
]
