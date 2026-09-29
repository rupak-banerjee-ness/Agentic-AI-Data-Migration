from langgraph.checkpoint.memory import InMemorySaver

from orchestrator.graph import compile_graph

g = compile_graph(InMemorySaver())
print("compiled ok")
