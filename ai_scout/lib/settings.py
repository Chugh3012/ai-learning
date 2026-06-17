from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_scout.lib.config import ENV_FILE, _parse_env_file

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore",
                                      case_sensitive=False)

    foundry_project_endpoint: str = ""
    foundry_model_name: str = "nano"
    foundry_embed_name: str = "embed"
    storage_account: str = ""
    blob_container: str = "knowledge"
    acs_endpoint: str = ""
    email_sender: str = ""
    email_to: str = ""
    feedback_url: str = ""
    feedback_storage: str = ""
    subscriber_storage: str = ""
    metrics_dce: str = ""
    metrics_dcr_rule_id: str = ""
    metrics_stream: str = "Custom-AiScoutMetrics_CL"

    def email_address(self, var_name: str | None) -> str:
        if not var_name or var_name.upper() == "EMAIL_TO":
            return self.email_to
        return os.environ.get(var_name) or _parse_env_file(ENV_FILE).get(var_name, "")
