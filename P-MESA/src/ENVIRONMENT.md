# Environment Configuration

This document explains the purpose and usage of the environment variables defined in `src/.env` for the P-MESA project.

## File Location
`src/.env` should contain only non-secret placeholders in the repository and real values only on your local machine or deployment environment.

## Variables
| Variable | Required | Description |
|----------|----------|-------------|
| `API_KEY` | Yes | Your API key for the chosen LLM provider (e.g., Azure OpenAI, OpenAI). Must NOT be committed. |
| `API_VERSION` | Optional (Azure) | API version string used by Azure OpenAI endpoints (e.g., `2024-02-15-preview`). Ignored for non-Azure clients. |
| `ENDPOINT` | Yes (Azure) | Base URL for the Azure OpenAI endpoint (e.g., `https://your-resource-name.openai.azure.com`). For non-Azure OpenAI you may omit or repurpose. |
| `MODEL_NAME` | Yes | Deployment or model identifier (e.g., `gpt-4o-mini`, `gpt-4o`, or the Azure deployment name). |

## Example
```
API_KEY="REPLACE_ME"
API_VERSION="2024-02-15-preview"
ENDPOINT="https://my-resource.openai.azure.com"
MODEL_NAME="gpt-4o-mini"
```

---
Last updated: 2025-10-29
