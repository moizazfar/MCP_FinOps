#!/bin/bash
# FinOps Optimizer MCP — OpenShift Deploy Script
# Namespace: moizaleem21-dev | No cluster-admin needed
# Run this from the directory containing Dockerfile + server.py

set -e
NAMESPACE="moizaleem21-dev"
APP="finops-optimizer-mcp"
REGISTRY="image-registry.openshift-image-registry.svc:5000"

echo "=== Step 1: Login check ==="
oc whoami
oc project $NAMESPACE

echo ""
echo "=== Step 2: Create Supabase secret (skip if already exists) ==="
# Fill these before running:
SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
SUPABASE_KEY="your-service-role-key-here"

oc create secret generic finops-mcp-secrets \
  --from-literal=supabase-url="$SUPABASE_URL" \
  --from-literal=supabase-key="$SUPABASE_KEY" \
  -n $NAMESPACE \
  --dry-run=client -o yaml | oc apply -f -

echo ""
echo "=== Step 3: Build image using OpenShift BuildConfig ==="
# Uses OpenShift internal registry — no Quay/DockerHub needed
oc new-build \
  --name=$APP \
  --binary=true \
  --strategy=docker \
  -n $NAMESPACE \
  --dry-run || true  # ignore if already exists

# Start build from local directory
oc start-build $APP \
  --from-dir=. \
  --follow \
  -n $NAMESPACE

echo ""
echo "=== Step 4: Deploy ==="
oc apply -f openshift-deploy.yaml -n $NAMESPACE

echo ""
echo "=== Step 5: Wait for rollout ==="
oc rollout status deployment/$APP -n $NAMESPACE --timeout=120s

echo ""
echo "=== Step 6: Get Route URL ==="
ROUTE=$(oc get route $APP -n $NAMESPACE -o jsonpath='{.spec.host}')
echo "✅ MCP Server live at: https://$ROUTE/mcp"
echo ""
echo "=== Test it ==="
curl -s -X POST "https://$ROUTE/mcp" \
  -H "Content-Type: application/json" \
  -d '{"method":"tools/list","params":{}}' | python3 -m json.tool
