# 🧠 AIOps Factory — Full Project Context Prompt
### (Paste this as your first message in the AIOps Claude project)

---

## 👤 About Me

My name is Moiz. I'm a developer currently doing an internship where I'm building an **enterprise-grade AIOps platform** called **AIOps Factory** (also referred to as **AIOps Studio**). I communicate in a mix of English and Roman Urdu (Hinglish). I prefer **direct, practical responses** — no unnecessary restructuring of existing setups. I like to **start with the minimal working solution first**, then add complexity iteratively.

---

## 🏗️ Platform Overview: AIOps Factory

AIOps Factory is a full-stack, modular AIOps platform deployed on **OpenShift** (namespace: ``). It covers the full AIOps lifecycle:

| Layer | Components |
|---|---|
| **Auth** | Keycloak (SSO, RBAC) |
| **Observe** | Grafana, MLflow, Metricbeat, Elasticsearch |
| **FinOps** | Multi-cloud cost intelligence (Azure, AWS, GCP, OpenShift/Koku) |
| **AI / Analyze Engine** | RRCF anomaly detection, Claude API enrichment |
| **Auto-Remediation** | ArgoCD, Ansible |
| **ValueOps** | ROI tracking, savings dashboard |

The platform is deployed on a **shared OpenShift cluster** with restricted SCC (`restricted-v2`), meaning no root containers, no hostPath volumes, limited UID ranges.

---

## ✅ Work Done So Far (Internship Progress)

### 1. 🔐 Keycloak Deployment on OpenShift

- Tried Helm charts first — **abandoned** due to SCC UID conflicts under `restricted-v2`
- Final working solution: **plain `oc apply` YAML** using official image `quay.io/keycloak/keycloak:24.0.4`
- Used **Keycloak 26+ bootstrap admin env vars**: `KC_BOOTSTRAP_ADMIN_USERNAME` / `KC_BOOTSTRAP_ADMIN_PASSWORD`
- Deployed via plain Kubernetes manifests (Deployment + Service + Route)
- Keycloak is the **Auth layer** for the entire platform — handles SSO and RBAC for all services

---

### 2. 📦 n8n Deployment on Minikube (Learning Phase)

- Started with full PostgreSQL-backed n8n setup
- **Iteratively simplified** to 3 minimal YAML files: namespace, deployment, service
- Used **SQLite** backend + `kubectl port-forward` for browser access
- This was a foundational learning exercise in OpenShift/Kubernetes concepts before moving to production

---

### 3. 💰 FinOps Module — Multi-Cloud Cost Intelligence Pipeline

**Goal:** Detect cost anomalies across Azure, AWS, GCP, and OpenShift, enrich with AI insights, and store actionable recommendations.

**Architecture:**
- **n8n workflows** (running locally) orchestrate the entire pipeline
- **Supabase** as the database backend (credentials stored as named n8n credentials, NOT environment variables)
- **Z-score anomaly detection**: Z > 2.0 AND deviation > 25% over 30-day rolling window
- **Claude API** (`claude-opus-4-5`) for AI enrichment via n8n HTTP nodes

**Supabase Tables:**
```
finops_anomalies
finops_ai_insights
finops_savings
finops_recommendations
finops_remediation_log
```

**Key Constraints:**
- Cannot deploy a Python FastAPI server (shared cluster restriction)
- n8n runs locally, not on OpenShift
- Supabase credentials are named n8n credentials

**MCP Server:** Also designed a **FastMCP-based MCP server** for the FinOps module to expose tools to Claude via Model Context Protocol.

---

### 4. 🤖 MLflow + RRCF Anomaly Detection Pipeline

**Goal:** Detect infrastructure anomalies from Kubernetes/OpenShift metrics using ML, track experiments with MLflow, and store results in Supabase.

**Data Flow:**
```
Metricbeat → Elasticsearch → RRCF Model → Supabase
                                  ↓
                              MLflow (experiment tracking + model registry)
```

**Algorithm:** RRCF (Robust Random Cut Forest) — an unsupervised streaming anomaly detection algorithm well-suited for time-series infrastructure metrics.

**Full Modular Codebase Produced (Python):**

| Module | Purpose |
|---|---|
| `data_loader.py` | Pull metrics from Elasticsearch |
| `preprocessor.py` | Feature engineering, normalization |
| `rrcf_detector.py` | RRCF anomaly scoring |
| `mlflow_tracker.py` | Log experiments, params, metrics to MLflow |
| `model_registry.py` | Register/promote models in MLflow Model Registry |
| `drift_monitor.py` | Detect data/concept drift over time |
| `supabase_writer.py` | Write anomalies + scores to Supabase |
| `orchestrator.py` | Main pipeline runner tying all modules |
| `cleanup.py` | Cleanup old experiments/runs in MLflow |

**MLflow deployed on OpenShift** in the `` namespace as part of the Observe layer.

---

### 5. 🗄️ SingleStore — Unified HTAP Data Layer (Design Phase)

Explored **SingleStore** as a unified data layer across all AIOps platform layers:

| Use Case | SingleStore Feature |
|---|---|
| Time-series metrics (Grafana, RRCF) | Columnstore |
| Alert memory / RAG for AI | Vector search |
| Real-time Kafka ingestion | Pipelines |
| Redis replacement (caching) | Rowstore |

This was an architectural design exploration — not yet fully implemented.

---

## 🛠️ Tech Stack Summary

| Category | Tools |
|---|---|
| **Platform** | OpenShift (shared cluster, `restricted-v2` SCC) |
| **Namespace** | `` |
| **Workflow Automation** | n8n (local) |
| **Database** | Supabase (PostgreSQL) |
| **ML Experiment Tracking** | MLflow |
| **Anomaly Detection** | RRCF (Python) |
| **Metrics Pipeline** | Metricbeat → Elasticsearch |
| **Observability** | Grafana, MLflow UI |
| **Auth** | Keycloak 24.0.4 |
| **GitOps / Remediation** | ArgoCD, Ansible |
| **AI Enrichment** | Claude API (claude-opus-4-5) |
| **MCP** | FastMCP |
| **Data Store (Explored)** | SingleStore |
| **Container Registry** | quay.io |

---

## 📌 My Working Style & Preferences

1. **Minimal first** — always give me the smallest working solution, then we expand
2. **No unnecessary restructuring** — if something works, don't suggest replacing it
3. **Practical > theoretical** — I want working code/configs, not long explanations
4. **Iterative** — we build step by step
5. **Roman Urdu/Hinglish is fine** — respond in whatever mix feels natural
6. **OpenShift constraints are real** — always account for `restricted-v2` SCC (no root, limited UIDs, no hostPath)
7. **No FastAPI server** — I cannot deploy Python web servers on the shared cluster

---

## 🚀 Where I Want to Continue From

I want to continue building the **AIOps Factory** platform forward. The immediate areas that need work:

1. **FinOps module** — refining n8n workflows, anomaly alerts, Supabase integration
2. **RRCF + MLflow pipeline** — testing, drift monitoring, model promotion logic
3. **Auto-Remediation layer** — connecting anomaly detection output to ArgoCD/Ansible remediation
4. **ValueOps** — ROI and savings tracking dashboard
5. **Platform integration** — tying all layers together end-to-end

Pick up from here and let's continue building. Ask me what specific part to tackle first if you need direction.

---

*This prompt was generated to onboard a fresh Claude instance with full project context for AIOps Factory internship work.*
