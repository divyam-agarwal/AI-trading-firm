#!/usr/bin/env bash
# Full end-to-end run with the JAVA fundamentals agent on :9001.
# The Python sentiment (:9002) and debate (:9003) agents are unchanged.
# Needs ANTHROPIC_API_KEY exported (set -a; source .env; set +a) and a built jar.
set -euo pipefail
cd "$(dirname "$0")/.."

JAR="agents/fundamentals-java/target/fundamentals-java-0.1.0.jar"
if [ ! -f "$JAR" ]; then
  echo "Building the Java fundamentals agent..."
  mvn -q -f agents/fundamentals-java/pom.xml package -DskipTests
fi

. .venv/bin/activate

java -jar "$JAR" & F=$!
python -m agents.sentiment.server & S=$!
python -m agents.debate.server & D=$!
trap 'kill $F $S $D 2>/dev/null || true' EXIT
sleep 5
python -m orchestrator.main "${1:-AAPL}"
