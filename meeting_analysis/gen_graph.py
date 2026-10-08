from src.agentic.graph import build_graph
from src.utils.embedding_backend import build_embedding_adapter
from src.utils.openai_adapters import OpenAIChatJSONAdapter

embedding_adapter = build_embedding_adapter()
llm = OpenAIChatJSONAdapter()
graph = build_graph(llm, llm, llm, llm)

image_bytes = graph.get_graph().draw_mermaid_png()
with open('graph.png', "wb") as f:
    f.write(image_bytes)