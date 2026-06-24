from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

from prism.lib.config import ENV_FILE, _parse_env_file

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore",
                                      case_sensitive=False)

    foundry_project_endpoint: str = ""
    foundry_model_name: str = "nano"
    foundry_embed_name: str = "embed"
    pexels_api_key: str = ""
    speech_resource_id: str = ""
    speech_region: str = "eastus2"
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

    @property
    def unsubscribe_url(self) -> str:
        # Same Function host as the feedback route, different path (/api/unsubscribe).
        if not self.feedback_url:
            return ""
        return self.feedback_url.rsplit("/", 1)[0] + "/unsubscribe"

    @property
    def preference_url(self) -> str:
        # Same Function host as the feedback route, different path (/api/preferences).
        if not self.feedback_url:
            return ""
        return self.feedback_url.rsplit("/", 1)[0] + "/preferences"

    @property
    def saved_url(self) -> str:
        # Same Function host as the feedback route, different path (/api/saved).
        if not self.feedback_url:
            return ""
        return self.feedback_url.rsplit("/", 1)[0] + "/saved"

    def email_address(self, var_name: str | None) -> str:
        if not var_name or var_name.upper() == "EMAIL_TO":
            return self.email_to
        return os.environ.get(var_name) or _parse_env_file(ENV_FILE).get(var_name, "")
