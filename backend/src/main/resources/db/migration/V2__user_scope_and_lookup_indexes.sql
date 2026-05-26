CREATE INDEX IF NOT EXISTS idx_api_providers_user_sort
    ON api_providers(user_id, sort_order, provider_key);

CREATE INDEX IF NOT EXISTS idx_api_providers_user_provider
    ON api_providers(user_id, provider_key);

CREATE INDEX IF NOT EXISTS idx_ppt_slides_user_deck_number
    ON ppt_slides(user_id, deck_id, slide_number);
