"""A module-level WorkflowServer for the library's launcher (it imports a file and looks for one):

    python -m llama_agents.server src/litreview/server_app.py

Host and port come from WORKFLOWS_PY_SERVER_HOST / WORKFLOWS_PY_SERVER_PORT; P2_RUNTIME=dbos selects
the DBOS runtime. Kept apart from server.py so that importing server.py stays cheap (this module loads
the index, embedding model and reranker on import). `litreview serve` does the same thing.
"""

import asyncio
import os

from litreview.server import production_server

server = asyncio.run(production_server(os.environ.get("P2_RUNTIME", "default")))
