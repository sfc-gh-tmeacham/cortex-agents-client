# Plan: README environment-based restructure

## Proposed top-level heading structure

```
# cortex-agents-client

## Installation
  (uv + pip — note SiS uses pyproject.toml, covered below)

---

## Core Python API
  ### Authentication
    - PAT (recommended)
    - JWT (key-pair)
    - OAuth
    *(SiS credentials are injected automatically — see SiS section)*
  ### Quick start
  ### Multi-turn conversations
  ### Handling all event types
  ### Non-streaming run
  ### Agent management (CRUD)
  ### Thread management
  ### Forking conversations
  ### Exception handling

---

## External Streamlit
  ### Dependencies
  ### Secrets configuration
  ### Drop-in chatbot
  ### Manual integration
  ### Embedded mode
  ### File and audio attachments
  ### Client-side tool execution
  ### Working with table results
  ### Elicitation

---

## Streamlit-in-Snowflake (container runtime)
  ### Prerequisites — External Access Integrations
    - Cortex Agents API EAI
    - PyPI EAI
  ### Authentication
  ### Drop-in chatbot
  ### Manual integration
  ### Deploying the app
    - Workspaces (recommended)
    - SQL / Snowflake CLI
  ### RBAC and role considerations
    - How RBAC is enforced
    - Role switching
    - If you need role-selectable access

---

## Reference
  ### CortexAgentsClient parameters
  ### StreamlitChatbot parameters
  ### Secrets and environment variables
  ### Running tests
  ### Demo app
  ### Architecture
  ### Notes
```

## What moves where

| Current section | Destination |
|---|---|
| Installation | stays at top |
| Quick start | Core Python API |
| Authentication (PAT/JWT/OAuth) | Core Python API |
| Configuration reference → CortexAgentsClient | Reference |
| Configuration reference → StreamlitChatbot | Reference |
| Secrets and environment variables | Reference |
| Multi-turn conversations | Core Python API |
| Handling all event types | Core Python API |
| Non-streaming run | Core Python API |
| Agent management | Core Python API |
| Thread management | Core Python API |
| Forking conversations | Core Python API |
| Exception handling | Core Python API |
| Streamlit integration → Drop-in chatbot | External Streamlit |
| Streamlit integration → Manual integration | External Streamlit |
| Streamlit integration → Embedded mode | External Streamlit |
| Streamlit integration → File/audio | External Streamlit |
| Streamlit integration → Client-side tools | External Streamlit |
| Streamlit integration → Table results | External Streamlit |
| Streamlit integration → Elicitation | External Streamlit |
| Streamlit integration → SiS (Steps 1-3) | SiS section |
| Streamlit integration → Manual integration in SiS | SiS section |
| RBAC and role considerations | SiS section |
| Running tests | Reference |
| Demo app | Reference |
| Architecture | Reference |
| Notes | Reference |
