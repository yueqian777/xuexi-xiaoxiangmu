package com.intp.study.ai.service;

import com.intp.study.ai.model.AiGenerateCommand;
import com.intp.study.ai.model.AiGenerateResult;
import com.intp.study.ai.model.ApiProviderConfig;

public interface AiProviderClient {
    boolean supports(String providerType);

    AiGenerateResult generate(ApiProviderConfig provider, AiGenerateCommand command);
}
