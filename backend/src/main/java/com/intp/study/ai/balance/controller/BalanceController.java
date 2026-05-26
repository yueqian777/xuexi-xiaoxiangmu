package com.intp.study.ai.balance.controller;

import com.intp.study.ai.balance.dto.BalanceQueryRequest;
import com.intp.study.ai.balance.dto.BalanceResultDto;
import com.intp.study.ai.balance.service.BalanceQueryService;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/ai/providers/{providerKey}/balance-query")
public class BalanceController {
    private final BalanceQueryService balanceQueryService;

    public BalanceController(BalanceQueryService balanceQueryService) {
        this.balanceQueryService = balanceQueryService;
    }

    @PostMapping
    public BalanceResultDto query(@PathVariable String providerKey, @RequestBody(required = false) BalanceQueryRequest request) {
        return balanceQueryService.query(providerKey, request);
    }
}
