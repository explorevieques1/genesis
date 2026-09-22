# Spec: Genesis Markdown/60-UI/Notebook.md · 60-UI/Nodes.md
"""The notebook: a vault of markdown files, and the links between them."""

from genesis.notebook.links import LinkIndex, Ref, parse_links
from genesis.notebook.vault import Vault, VaultRegistry

__all__ = ["LinkIndex", "Ref", "Vault", "VaultRegistry", "parse_links"]
