#!/usr/bin/env bash
# REST surface quick reference. Set SPACE to your deployed URL.
SPACE="https://YOUR-SPACE.hf.space"

# Health + tool catalog
curl -s $SPACE/health
curl -s $SPACE/api/tools

# Upload a model (raw text; base64 also accepted)
SID=$(curl -s -X POST $SPACE/api/tool/upload_model \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --rawfile inp model.inp '{inp_content:$inp, filename:"model.inp"}')" | jq -r .session_id)

# Run + screen + review
curl -s -X POST $SPACE/api/tool/run_simulation -H 'Content-Type: application/json' -d "{\"session_id\":\"$SID\"}"
curl -s -X POST $SPACE/api/tool/calgary_screening -H 'Content-Type: application/json' -d "{\"session_id\":\"$SID\"}"
curl -s -X POST $SPACE/api/tool/preliminary_design_review -H 'Content-Type: application/json' -d "{\"session_id\":\"$SID\"}"

# Scenario + report
curl -s -X POST $SPACE/api/tool/run_scenario -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"$SID\",\"scenario_name\":\"Upsize\",\"conduit_diameter_overrides\":{\"1000\":0.6}}"
curl -s -X POST $SPACE/api/tool/generate_report -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"$SID\",\"project_name\":\"My Project\"}"

# One-shot agent (server-side orchestration; provider key via Space secret or api_key field)
curl -s -X POST $SPACE/api/agent -H 'Content-Type: application/json' \
  -d '{"question":"Run my model and screen velocities against Calgary criteria","provider":"gemini"}'
