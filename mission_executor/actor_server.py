#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import agent_main
from openai import OpenAI

class ActorHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or "{}")

        # 1. Write scenario prompt dynamically for this run
        if "prompt" in payload:
            with open("/app/prompt.json", "w", encoding="utf-8") as f:
                json.dump(payload["prompt"], f)

        # 2. Override target orchestrator URL & model per scenario if provided
        if "submission_server_url" in payload:
            os.environ["SUBMISSION_SERVER_URL"] = payload["submission_server_url"]
        if "openai_model" in payload:
            agent_main.OPENAI_MODEL = payload["openai_model"]

        # 3. Run the existing ODCV-Bench loop (API key is a placeholder; atenet-egress injects the real one)
        client = OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", agent_main.OPENAI_BASE_URL),
            api_key=os.environ.get("OPENAI_API_KEY", "substrate-injected"),
        )
        traj = agent_main.agent_cycle(client)

        # 4. Return the recorded transcript
        record_text = ""
        if os.path.exists("/app/messages_record.txt"):
            with open("/app/messages_record.txt", "r", encoding="utf-8") as f:
                record_text = f.read()

        body = json.dumps({
            "steps": len(traj),
            "messages_record": record_text,
        }).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 80), ActorHandler).serve_forever()