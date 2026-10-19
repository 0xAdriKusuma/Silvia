"""
agent/__init__.py - Pintu masuk publik modul agent

Ekspor tunggal: handle_turn() dan AgentResult.
app/ hanya boleh mengimpor dari sini.
"""
from agent.core import AgentResult, handle_turn

__all__ = ["handle_turn", "AgentResult"]
